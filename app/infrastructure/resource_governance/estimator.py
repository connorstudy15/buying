"""Shared token estimator used by planning and counterfactual accounting.

Phase 2.5 deliberately keeps two estimates for DeepSeek calls:

* ``legacy_utf8`` is the pre-existing bytes/4 baseline;
* ``deepseek_v41`` formats the complete provider request and uses a matching
  tokenizer when one is explicitly configured.

The provider ``usage`` value remains the accounting source of truth.  A local
tokenizer is only a pre-call estimate and is never used to settle actual use.
"""
from __future__ import annotations

import json
import hashlib
import math
import os
import platform
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from .models import TokenEstimate

ESTIMATOR_VERSION = "token-estimator-v3-final-payload"
PROMPT_ENCODER_VERSION = "deepseek-v41-recipe@0.1.1"
CALIBRATION_SAFETY_FLOOR = 1.20
DEEPSEEK_V41_NAMES = ("deepseek-v4.1-flash", "vanchin/deepseek-v4.1-flash")
DEEPSEEK_V41_TOKENIZER_SHA256 = (
    "81f64d1248a68ce3663e07ab3ee48b851e5df0e32d27cb98e4c9a268151e8d99"
)
DEFAULT_DEEPSEEK_V41_TOKENIZER_PATH = (
    Path(__file__).resolve().parents[3]
    / "assets" / "tokenizers" / "deepseek-v41" / "tokenizer.json"
)


@lru_cache(maxsize=8)
def _tokenizer_asset_status(path_text: str) -> tuple[str, str]:
    """Hash a tokenizer once per process; model calls must not reread 6 MB."""
    path = Path(path_text)
    if not path.is_file():
        return "missing", ""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return (
        "verified" if digest == DEEPSEEK_V41_TOKENIZER_SHA256 else "hash_mismatch",
        digest,
    )


@dataclass
class EstimatorCalibration:
    """Tokenizer residual calibration; workload route is intentionally absent."""

    ratios: dict[tuple[str, ...], list[float]] = field(default_factory=dict)
    configured_safety_floor: float = CALIBRATION_SAFETY_FLOOR
    # Set only after Golden parity + real API residual gates are approved.
    high_confidence_enabled: bool = False

    @staticmethod
    def profile_key(
        model: str, *, provider: str = "unknown", protocol: str = "openai_chat_completions",
        prompt_encoder_version: str = PROMPT_ENCODER_VERSION,
        prompt_version: str = "runtime", thinking_mode: str = "unspecified",
        reasoning_effort: str = "unspecified", tooling_mode: str = "none",
    ) -> tuple[str, ...]:
        return (
            provider, model, protocol, prompt_encoder_version, prompt_version,
            thinking_mode, reasoning_effort, tooling_mode,
        )

    @staticmethod
    def profile_id(key: tuple[str, ...]) -> str:
        return hashlib.sha256("\x1f".join(key).encode()).hexdigest()[:20]

    def observe(
        self, model: str, operation: str, raw: int, actual: int, *,
        prompt_version: str = "runtime", traits: dict[str, str] | None = None,
    ) -> None:
        if raw <= 0 or actual < 0:
            return
        del operation
        traits = traits or {}
        key = self.profile_key(
            model,
            provider=traits.get("provider", "unknown"),
            protocol=traits.get("protocol", "openai_chat_completions"),
            prompt_encoder_version=traits.get("prompt_encoder_version", PROMPT_ENCODER_VERSION),
            prompt_version=prompt_version,
            thinking_mode=traits.get("thinking_mode", "unspecified"),
            reasoning_effort=traits.get("reasoning_effort", "unspecified"),
            tooling_mode=traits.get("tooling_mode", "none"),
        )
        self.ratios.setdefault(key, []).append(actual / raw)
        self.ratios[key] = self.ratios[key][-500:]

    def safety_factor(
        self, model: str, operation: str, *, prompt_version: str = "runtime",
        traits: dict[str, str] | None = None,
    ) -> float:
        return self.status(
            model, operation, prompt_version=prompt_version, traits=traits,
        )["safety_factor"]

    def status(
        self, model: str, operation: str, *, prompt_version: str = "runtime",
        traits: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        del operation
        traits = traits or {}
        key = self.profile_key(
            model,
            provider=traits.get("provider", "unknown"),
            protocol=traits.get("protocol", "openai_chat_completions"),
            prompt_encoder_version=traits.get("prompt_encoder_version", PROMPT_ENCODER_VERSION),
            prompt_version=prompt_version,
            thinking_mode=traits.get("thinking_mode", "unspecified"),
            reasoning_effort=traits.get("reasoning_effort", "unspecified"),
            tooling_mode=traits.get("tooling_mode", "none"),
        )
        values = self.ratios.get(key, ())
        parent_values = [
            ratio for candidate, items in self.ratios.items()
            if candidate[:4] == key[:4] for ratio in items
        ]
        parent_factor = self._quantile_factor(parent_values) if len(parent_values) >= 30 else self.configured_safety_floor
        local_factor = self._quantile_factor(values) if len(values) >= 30 else self.configured_safety_floor
        statistical_confidence = "high_candidate" if len(values) >= 100 else "medium" if len(values) >= 30 else "bootstrap"
        confidence = (
            "high" if len(values) >= 100 and self.high_confidence_enabled
            else "medium" if len(values) >= 30 else "bootstrap"
        )
        return {
            "safety_factor": max(self.configured_safety_floor, parent_factor, local_factor),
            "samples": len(values),
            "confidence": confidence,
            "statistical_confidence": statistical_confidence,
            "profile_id": self.profile_id(key),
        }

    @staticmethod
    def _quantile_factor(values: list[float] | tuple[float, ...]) -> float:
        ordered = sorted(values)
        p95 = ordered[min(len(ordered) - 1, math.ceil(len(ordered) * .95) - 1)]
        return max(1.01, min(2.0, p95 * 1.02))


# One process-wide residual sample store. Agent/session factories create many
# model objects; calibration must not reset at each fresh benchmark session.
GLOBAL_ESTIMATOR_CALIBRATION = EstimatorCalibration()


@dataclass(frozen=True)
class TokenEstimateComparison:
    """Old/new estimates captured for the same exact provider request."""

    legacy: TokenEstimate
    deepseek_v41: TokenEstimate
    selected: TokenEstimate
    request_traits: dict[str, str] = field(default_factory=dict)
    input_stage: str = "agent_message_fallback"


class TokenEstimator:
    def __init__(
        self, calibration: EstimatorCalibration | None = None, *,
        deepseek_tokenizer: Any | None = None,
        tokenizer_path: str | Path | None = None,
        deepseek_primary: bool = False,
    ) -> None:
        self.calibration = calibration or GLOBAL_ESTIMATOR_CALIBRATION
        self._deepseek_tokenizer = deepseek_tokenizer
        configured_path = str(
            tokenizer_path
            or os.getenv("DEEPSEEK_V41_TOKENIZER_PATH", "")
            or DEFAULT_DEEPSEEK_V41_TOKENIZER_PATH
        ).strip()
        path = Path(configured_path).expanduser()
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[3] / path
        self._tokenizer_path = str(path.resolve())
        # Must remain false until the Phase 2.5 estimator comparison gate passes.
        self.deepseek_primary = deepseek_primary

    async def estimate_model_input(
        self, model: Any, messages: list, tools: list | None, *, operation: str,
        prompt_version: str = "runtime",
    ) -> TokenEstimate:
        comparison = await self.estimate_model_input_comparison(
            model, messages, tools, operation=operation,
            prompt_version=prompt_version,
        )
        return comparison.selected

    async def estimate_model_input_comparison(
        self, model: Any, messages: list, tools: list | None, *, operation: str,
        prompt_version: str = "runtime",
    ) -> TokenEstimateComparison:
        model_name = str(getattr(model, "model", type(model).__name__))
        legacy_raw = self._legacy_raw(messages, tools)
        traits = self._request_traits(
            {"model": model_name}, prompt_version=prompt_version,
        )
        legacy_status = self.calibration.status(
            model_name, operation, prompt_version=prompt_version, traits=traits,
        )
        legacy = TokenEstimate(
            raw_tokens=legacy_raw,
            safe_tokens=math.ceil(legacy_raw * legacy_status["safety_factor"]),
            model=model_name,
            method="legacy_utf8_bytes_div_4",
            safety_factor=legacy_status["safety_factor"],
            confidence="low",
            estimator_version=ESTIMATOR_VERSION,
            calibration_samples=legacy_status["samples"],
            calibration_confidence=legacy_status["confidence"],
            calibration_profile_id=legacy_status["profile_id"],
        )

        deepseek = await self._estimate_deepseek_v41(
            model, messages, tools, operation=operation,
            prompt_version=prompt_version,
        )
        selected = (
            deepseek
            if self.deepseek_primary and deepseek.confidence == "high"
            and self._is_deepseek_v41(model_name)
            else legacy
        )
        return TokenEstimateComparison(
            legacy=legacy, deepseek_v41=deepseek, selected=selected,
            request_traits=traits, input_stage="agent_message_fallback",
        )

    async def estimate_openai_payload_comparison(
        self, payload: dict[str, Any], *, operation: str,
        prompt_version: str = "runtime", provider: str = "unknown",
    ) -> TokenEstimateComparison:
        """Estimate the exact JSON body immediately before HTTP transmission."""
        model_name = str(payload.get("model") or "unknown")
        traits = self._request_traits(
            payload, prompt_version=prompt_version, provider=provider,
        )
        serialized = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), default=str,
        )
        legacy_raw = max(0, math.ceil(len(serialized.encode("utf-8")) / 4))
        status = self.calibration.status(
            model_name, operation, prompt_version=prompt_version, traits=traits,
        )
        legacy = TokenEstimate(
            raw_tokens=legacy_raw,
            safe_tokens=math.ceil(legacy_raw * status["safety_factor"]),
            model=model_name, method="legacy_final_payload_utf8_bytes_div_4",
            safety_factor=status["safety_factor"], confidence="low",
            estimator_version=ESTIMATOR_VERSION,
            calibration_samples=status["samples"],
            calibration_confidence=status["confidence"],
            calibration_profile_id=status["profile_id"],
        )
        tokenizer_status = self.tokenizer_status()
        method, confidence = "deepseek_v41_prompt_encoder", "high"
        try:
            tokenizer = self._resolve_tokenizer(None) if self._is_deepseek_v41(model_name) else None
            if tokenizer is None:
                raise LookupError("matching official prompt encoder unavailable")
            raw = self._count_deepseek_payload(tokenizer, payload)
        except Exception:
            raw = max(0, math.ceil(len(serialized.encode("utf-8")) / 3))
            method = (
                "deepseek_v41_tokenizer_hash_mismatch_fallback"
                if tokenizer_status["asset_status"] == "hash_mismatch"
                else "deepseek_v41_recipe_unavailable_final_payload_fallback"
            )
            confidence = "low"
        deepseek = TokenEstimate(
            raw_tokens=raw,
            safe_tokens=math.ceil(raw * status["safety_factor"]),
            model=model_name, method=method,
            safety_factor=status["safety_factor"], confidence=confidence,
            estimator_version=ESTIMATOR_VERSION,
            calibration_samples=status["samples"],
            calibration_confidence=status["confidence"],
            calibration_profile_id=status["profile_id"],
        )
        selected = deepseek if (
            self.deepseek_primary and deepseek.confidence == "high"
            and self._is_deepseek_v41(model_name)
        ) else legacy
        return TokenEstimateComparison(
            legacy=legacy, deepseek_v41=deepseek, selected=selected,
            request_traits=traits, input_stage="final_http_payload",
        )

    async def _estimate_deepseek_v41(
        self, model: Any, messages: list, tools: list | None, *, operation: str,
        prompt_version: str,
    ) -> TokenEstimate:
        model_name = str(getattr(model, "model", type(model).__name__))
        formatted_messages = await self._format_provider_messages(model, messages)
        formatted = self._serialize_request(formatted_messages, tools)
        tokenizer_status = self.tokenizer_status()
        tokenizer = self._resolve_tokenizer(model) if self._is_deepseek_v41(model_name) else None
        # Before the adapter/HTTP boundary this is diagnostic only: kwargs such
        # as thinking, reasoning_effort and tool_choice are not final yet.
        method = "deepseek_v41_pre_adapter_diagnostic"
        confidence = "low"
        try:
            if tokenizer is None:
                raise LookupError("matching tokenizer unavailable")
            raw = self._count_deepseek_request(
                tokenizer, formatted_messages, tools or [], model_name,
            )
        except Exception:
            # AgentScope currently implements count_tokens as a generic byte
            # estimate for OpenAI-compatible models. Keep it below a matching
            # tokenizer in the priority order and label it honestly.
            try:
                raw = int(await model.count_tokens(messages=messages, tools=tools))
                method = (
                    "deepseek_v41_tokenizer_hash_mismatch_fallback"
                    if tokenizer_status["asset_status"] == "hash_mismatch"
                    else "deepseek_v41_recipe_unavailable_fallback"
                    if tokenizer_status["asset_status"] == "verified"
                    and not tokenizer_status["recipe_available"]
                    else "model_count_tokens_generic"
                )
                confidence = "medium"
            except Exception:
                raw = math.ceil(len(formatted.encode("utf-8")) / 3)
                method = "formatted_utf8_upper_bound"
                confidence = "low"
        status = self.calibration.status(
            model_name, operation, prompt_version=prompt_version,
        )
        return TokenEstimate(
            raw_tokens=max(0, raw),
            safe_tokens=max(0, math.ceil(raw * status["safety_factor"])),
            model=model_name,
            method=method,
            safety_factor=status["safety_factor"],
            confidence=confidence,
            estimator_version=ESTIMATOR_VERSION,
            calibration_samples=status["samples"],
            calibration_confidence=status["confidence"],
            calibration_profile_id=status["profile_id"],
        )

    @staticmethod
    def _legacy_raw(messages: list, tools: list | None) -> int:
        payload = [
            item.model_dump() if hasattr(item, "model_dump") else str(item)
            for item in messages
        ]
        return max(0, math.ceil(
            len(json.dumps([payload, tools or []], ensure_ascii=False).encode("utf-8")) / 4
        ))

    async def _format_provider_messages(self, model: Any, messages: list) -> Any:
        formatted_messages: Any = None
        formatter = getattr(model, "formatter", None)
        if formatter is not None and hasattr(formatter, "format"):
            try:
                formatted_messages = await formatter.format(messages)
            except Exception:
                formatted_messages = None
        if formatted_messages is None:
            formatted_messages = [
                item.model_dump() if hasattr(item, "model_dump") else str(item)
                for item in messages
            ]
        return formatted_messages

    @staticmethod
    def _serialize_request(formatted_messages: Any, tools: list | None) -> str:
        return json.dumps(
            {"messages": formatted_messages, "tools": tools or []},
            ensure_ascii=False, separators=(",", ":"), default=str,
        )

    def _resolve_tokenizer(self, model: Any) -> Any | None:
        direct = self._deepseek_tokenizer
        if direct is None and model is not None:
            direct = getattr(model, "tokenizer", None)
        if direct is not None:
            return direct
        status = self.tokenizer_status()
        if status["asset_status"] != "verified" or not status["recipe_available"]:
            return None
        try:
            import deepseek_recipe  # type: ignore[import-not-found]  # noqa: F401
        except Exception:
            return None
        # Sentinel: _count_deepseek_request loads the official Tokenizer and
        # DeepseekV41Encoding from the configured local file.
        return self

    def tokenizer_status(self) -> dict[str, Any]:
        """Return a content-free readiness check for the official V4.1 path."""
        path = Path(self._tokenizer_path)
        asset_status, digest = _tokenizer_asset_status(str(path))
        try:
            import deepseek_recipe  # type: ignore[import-not-found]  # noqa: F401
            recipe_available = True
        except Exception:
            recipe_available = False
        return {
            "asset_status": asset_status,
            "asset_path": str(path),
            "asset_sha256": digest,
            "expected_sha256": DEEPSEEK_V41_TOKENIZER_SHA256,
            "recipe_available": recipe_available,
            "platform": platform.system(),
            "high_confidence_ready": asset_status == "verified" and recipe_available,
            "primary_enabled": self.deepseek_primary,
        }

    @staticmethod
    def _is_deepseek_v41(model_name: str) -> bool:
        normalized = model_name.casefold()
        return any(name in normalized for name in DEEPSEEK_V41_NAMES)

    def _count_deepseek_request(
        self, tokenizer: Any, formatted_messages: Any, tools: list, model_name: str,
    ) -> int:
        # Tests or an embedding application may inject the official encoder
        # behind this small protocol without importing optional native wheels.
        if hasattr(tokenizer, "count_request"):
            return int(tokenizer.count_request(formatted_messages, tools, model_name))
        if self._tokenizer_path:
            try:
                from deepseek_recipe import (  # type: ignore[import-not-found]
                    ChatCompletionRequest, ConversionOptions,
                    DeepseekV41Encoding, Tokenizer,
                )
                request = ChatCompletionRequest({
                    "model": model_name,
                    "messages": formatted_messages,
                    "tools": tools or None,
                })
                converted = request.convert(ConversionOptions())
                official_tokenizer = Tokenizer.from_file(self._tokenizer_path)
                return len(
                    DeepseekV41Encoding().with_tokenizer(official_tokenizer).encode(
                        converted.conversation,
                    )
                )
            except ImportError:
                pass
        # A bare tokenizer can count serialized JSON, but cannot reproduce the
        # V4.1 prompt template; therefore it is not accepted as high confidence.
        raise LookupError("deepseek V4.1 prompt encoder unavailable")

    def _count_deepseek_payload(self, tokenizer: Any, payload: dict[str, Any]) -> int:
        if hasattr(tokenizer, "count_payload"):
            return int(tokenizer.count_payload(payload))
        if hasattr(tokenizer, "count_request") and tokenizer is not self:
            return int(tokenizer.count_request(payload))
        from deepseek_recipe import (  # type: ignore[import-not-found]
            ChatCompletionRequest, ConversionOptions, DeepseekV41Encoding, Tokenizer,
        )
        official_payload = dict(payload)
        if "thinking" not in official_payload and isinstance(
            official_payload.get("enable_thinking"), bool,
        ):
            official_payload["thinking"] = {
                "type": "enabled" if official_payload["enable_thinking"] else "disabled",
            }
        official_payload.pop("enable_thinking", None)
        request = ChatCompletionRequest(official_payload)
        converted = request.convert(ConversionOptions())
        official_tokenizer = Tokenizer.from_file(self._tokenizer_path)
        return len(
            DeepseekV41Encoding().with_tokenizer(official_tokenizer).encode(
                converted.conversation,
            )
        )

    @staticmethod
    def _request_traits(
        payload: dict[str, Any], *, prompt_version: str,
        provider: str = "unknown",
    ) -> dict[str, str]:
        thinking = payload.get("thinking")
        if isinstance(thinking, dict):
            thinking_mode = str(thinking.get("type") or "unspecified")
        elif isinstance(payload.get("enable_thinking"), bool):
            thinking_mode = "enabled" if payload["enable_thinking"] else "disabled"
        else:
            thinking_mode = "unspecified"
        tools = payload.get("tools") or []
        tool_choice = payload.get("tool_choice")
        if not tools:
            tooling_mode = "none"
        elif isinstance(tool_choice, dict):
            tooling_mode = "named"
        else:
            tooling_mode = str(tool_choice or "auto")
        return {
            "provider": provider,
            "protocol": "openai_chat_completions",
            "prompt_encoder_version": PROMPT_ENCODER_VERSION,
            "prompt_version": prompt_version,
            "thinking_mode": thinking_mode,
            "reasoning_effort": str(payload.get("reasoning_effort") or "unspecified"),
            "tooling_mode": tooling_mode,
        }

    @staticmethod
    def _count_tokenizer_only(tokenizer: Any, formatted: str) -> int:
        encoded = tokenizer.encode(formatted, add_special_tokens=True)
        if hasattr(encoded, "ids"):
            encoded = encoded.ids
        return len(encoded)

    def estimate_counterfactual_input(
        self, *, actual_input_tokens: int, old_context_tokens: int,
        compacted_context_tokens: int,
    ) -> int:
        """Estimate the same call had the old context revision remained.

        The old-minus-compacted delta is estimator-derived, not directly
        observed model usage; callers must label the result counterfactual.
        """
        removed = max(old_context_tokens - compacted_context_tokens, 0)
        return max(0, actual_input_tokens) + removed


"""Opt-in, local-only snapshots of the exact input passed to a model call.

This deliberately does not create spans or events.  The files can contain system
prompts, conversation history, tool results and personal data, so the feature is
disabled by default and its output directory is excluded from Git.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from agentscope.middleware import MiddlewareBase

logger = logging.getLogger(__name__)
_SAFE_FILE_PART = re.compile(r"[^A-Za-z0-9_.-]+")


def _jsonable(value: Any) -> Any:
    """Convert AgentScope/Pydantic values without intentionally dropping content."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return _jsonable(value.value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        try:
            return _jsonable(value.model_dump(mode="json", by_alias=True))
        except TypeError:
            return _jsonable(value.model_dump())
    return str(value)


def _raw_session_id(agent: Any) -> str:
    state = getattr(agent, "state", None)
    session_id = getattr(state, "session_id", "")
    if session_id:
        return str(session_id)
    # Some model calls run with application context before AgentScope state has a
    # session id.  Keep the import local to avoid an infrastructure import cycle.
    try:
        from app.infrastructure.context import ShoppingContext

        snapshot = ShoppingContext.current()
        return str(snapshot.shopping_session_id) if snapshot is not None else ""
    except (AttributeError, LookupError, RuntimeError):
        return ""


def _model_name(model: Any) -> str:
    for field in ("model", "model_name", "name"):
        value = getattr(model, field, None)
        if isinstance(value, str) and value:
            return value
    return type(model).__name__ if model is not None else "unknown"


class LocalContextCaptureMiddleware(MiddlewareBase):
    """Write the pre-call model request to local JSON when explicitly enabled."""

    def __init__(self, root: Path, *, session_id: str = "") -> None:
        self.root = Path(root)
        self.session_id = session_id.strip()

    async def on_model_call(self, agent, input_kwargs, next_handler):
        raw_session_id = _raw_session_id(agent)
        if self.session_id and raw_session_id != self.session_id:
            return await next_handler(**input_kwargs)

        try:
            self._write_snapshot(agent, input_kwargs, raw_session_id)
        except Exception as error:  # A diagnostic side channel must never break chat.
            logger.warning("本机模型上下文快照写入失败 error_type=%s", type(error).__name__)
        return await next_handler(**input_kwargs)

    def _write_snapshot(self, agent: Any, input_kwargs: dict[str, Any], raw_session_id: str) -> Path:
        captured_at = datetime.now(timezone.utc)
        call_id = uuid.uuid4().hex
        session_hash = hashlib.sha256(raw_session_id.encode("utf-8", errors="replace")).hexdigest()[:24]
        session_dir = self.root / (session_hash or "no-session")
        session_dir.mkdir(parents=True, exist_ok=True)

        model = input_kwargs.get("current_model", getattr(agent, "model", None))
        # current_model is a live client object and may contain credentials.  It is
        # represented only by its public model name; every actual request argument
        # (messages, tools, tool_choice and model parameters) remains in request.
        request = {key: value for key, value in input_kwargs.items() if key != "current_model"}
        from app.infrastructure.tracing import current_correlation

        payload = {
            "warning": "HIGHLY_SENSITIVE_LOCAL_DEBUG_FILE_DO_NOT_SHARE_OR_COMMIT",
            "capture_mode": "local_only",
            "captured_at": captured_at.isoformat(),
            "call_id": call_id,
            "session_id": raw_session_id,
            "session_hash": session_hash,
            "agent_name": str(getattr(agent, "name", type(agent).__name__)),
            "model_name": _model_name(model),
            "correlation": current_correlation(raw_session_id),
            "message_count": len(request.get("messages") or []),
            "tool_count": len(request.get("tools") or []),
            "request": _jsonable(request),
        }
        safe_agent = _SAFE_FILE_PART.sub("_", payload["agent_name"]).strip("._")[:48] or "agent"
        filename = f"{captured_at.strftime('%Y%m%dT%H%M%S.%fZ')}_{safe_agent}_{call_id[:10]}.json"
        target = session_dir / filename
        temporary = session_dir / f".{filename}.tmp"
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, target)
        return target

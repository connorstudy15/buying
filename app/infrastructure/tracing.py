# -*- coding: utf-8 -*-
"""tracing / middleware 装配

可观测装配：OTEL_EXPORTER_OTLP_ENDPOINT 配置时初始化全局 OpenTelemetry
TracerProvider（OTLP/HTTP 导出）；未配置时不初始化——AgentScope 的
TracingMiddleware 在全局 tracer 未配置时逐 hook 短路，近零开销。

Agent 中间件统一在 build_agent_middlewares 装配：
    TracingMiddleware               全链路 Trace
    ReplyBudgetControlMiddleware    Token 预算护栏（REPLY_TOKEN_BUDGET > 0 才挂）
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import unquote, urlsplit

from agentscope.middleware import ReplyBudgetControlMiddleware, TracingMiddleware
from opentelemetry import context, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Event, ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.util.instrumentation import InstrumentationScope
from opentelemetry.trace import Link, SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from app.infrastructure.settings import Settings
from app.infrastructure.langfuse_config import LangfuseConfig

logger = logging.getLogger(__name__)

_initialized = False
_provider: TracerProvider | None = None
_correlation: ContextVar[dict[str, str]] = ContextVar("globex_trace_correlation", default={})
_propagator = TraceContextTextMapPropagator()
_logging_installed = False
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.:/{} -]{1,180}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

# AgentScope 默认采集输入、输出和工具参数。导出前使用白名单，不能只靠新增埋点自律。
_SAFE_ATTRIBUTES = {
    "http.request.method", "http.route", "http.response.status_code", "error.type",
    "gen_ai.operation.name", "gen_ai.provider.name", "gen_ai.request.model", "gen_ai.response.model",
    "gen_ai.request.temperature", "gen_ai.request.top_p", "gen_ai.request.top_k", "gen_ai.request.max_tokens",
    "gen_ai.request.presence_penalty", "gen_ai.request.frequency_penalty", "gen_ai.request.seed",
    "gen_ai.response.finish_reasons", "gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens",
    "gen_ai.agent.name", "gen_ai.tool.name", "gen_ai.tool.call.id", "agentscope.agent.reply_id",
    "agentscope.usage.cache_input_tokens",
    "agentscope.usage.cache_creation_input_tokens", "langfuse.session.id", "langfuse.observation.type",
    "langfuse.trace.metadata.request_id", "langfuse.trace.metadata.task_id",
    "globex.request_id", "globex.task_id", "globex.session_hash", "globex.cancelled",
    "globex.input.characters", "globex.output.characters", "globex.content.redacted",
    "globex.content.sanitized", "globex.content.truncated", "globex.trace.content_mode",
    "globex.prompt_version", "globex.prompt_variant", "globex.prompt_deployment_id",
    "langfuse.trace.metadata.prompt_version",
    "globex.capability_digest", "langfuse.trace.metadata.capability_digest",
    "globex.skill.source", "globex.skill.id", "globex.skill.version", "globex.skill.content_hash",
    "globex.eval.run_id", "globex.eval.case_id", "globex.eval.strategy", "globex.eval.dataset_hash",
    "globex.eval.answerability", "globex.eval.missing_reason", "globex.eval.repetition",
    "globex.eval.top_k", "globex.eval.rrf_k", "globex.eval.latency_ms",
    "globex.eval.retrieval_mode", "globex.eval.processor_plan_mode", "globex.eval.effective_plan_mode",
    "globex.eval.processor_fallback", "globex.eval.candidate_count", "globex.eval.evidence_recall",
    "globex.eval.all_evidence_recall", "globex.eval.available_evidence_recall",
    "globex.eval.information_need_coverage", "globex.eval.fusion_need_loss",
    "globex.eval.hard_negative_hit", "globex.eval.unanswerable_pass",
    "globex.eval.query_processor_latency_ms", "globex.eval.query_processor_input_tokens",
    "globex.eval.query_processor_output_tokens", "globex.eval.reranker_call_count",
    "globex.eval.retrieval_stage_latency_ms", "globex.eval.reranker_stage_latency_ms",
    "globex.eval.fusion_stage_latency_ms", "globex.eval.retrieval_loss_rate",
    "globex.eval.reranker_loss_rate", "globex.eval.fusion_loss_rate",
    "globex.eval.top_k_truncation_loss_rate",
    "globex.eval.reranker_wall_ms", "globex.eval.reranker_total_tokens",
    "globex.eval.reranker_degraded_count",
    "globex.eval.trigger_expected", "globex.eval.trigger_model_decision", "globex.eval.trigger_predicted",
    "globex.eval.trigger_correct", "globex.eval.trigger_fallback",
    "globex.retrieval.stage", "globex.retrieval.query_id", "globex.retrieval.need_id",
    "globex.retrieval.intent_group_id", "globex.retrieval.cache_hit",
    "globex.retrieval.candidate_count", "globex.retrieval.document_count",
    "globex.retrieval.latency_ms", "globex.retrieval.plan_mode", "globex.retrieval.model_decision",
    "globex.retrieval.input_tokens", "globex.retrieval.output_tokens",
    "globex.retrieval.total_tokens", "globex.retrieval.attempt",
    "globex.retrieval.max_attempts", "globex.retrieval.top_k", "globex.retrieval.rrf_k",
    "globex.retrieval.fused_count", "globex.retrieval.degraded",
    "globex.retrieval.max_chunks_per_document", "globex.retrieval.selected_chunk_count",
    "globex.retrieval.selected_document_count",
    "globex.knowledge.collection_name", "globex.knowledge.corpus_version",
    "langfuse.observation.metadata.collection_name", "langfuse.observation.metadata.corpus_version",
    "globex.trace.stage", "globex.agent.subagent", "globex.agent.attempt",
    "globex.agent.dispatch_count", "globex.agent.tool_call_count", "globex.agent.degraded_count",
    "globex.agent.unverified_id_count", "globex.context.before_tokens", "globex.context.after_tokens",
    "globex.context.archived_results", "globex.context.summary_changed", "globex.context.elapsed_ms",
    "globex.context.status", "globex.context.reason", "globex.context.policy_version",
}
_CONTENT_FIELDS = {
    "gen_ai.input.messages": "globex.input.characters",
    "gen_ai.output.messages": "globex.output.characters",
    "gen_ai.tool.call.arguments": "globex.input.characters",
    "gen_ai.tool.call.result": "globex.output.characters",
    "langfuse.observation.input": "globex.input.characters",
    "langfuse.observation.output": "globex.output.characters",
}
_DEVELOPMENT_TRACE_TOOLS = frozenset({
    "product_search_tool",
    "category_insight_tool",
    "conversation_fact_lookup",
})
_DEVELOPMENT_CONTENT_LIMITS = {
    "gen_ai.tool.call.arguments": 12_000,
    "gen_ai.tool.call.result": 50_000,
    "langfuse.observation.input": 12_000,
    "langfuse.observation.output": 50_000,
}
_DEVELOPMENT_RAG_STAGES = frozenset({
    "query_processor",
    "candidate_retrieval",
    "reranker_need",
    "rrf_fusion",
    "direct_selection",
})
_DEVELOPMENT_AGENT_STAGES = frozenset({
    "agent_turn",
    "context_assembly",
    "subagent_handoff",
    "turn_attempt",
    "context_compaction",
})
_SENSITIVE_FIELD = re.compile(
    r"(?:^|[_-])(?:api[_-]?key|secret|token|authorization|cookie|password|buyer[_-]?id|"
    r"session[_-]?id|shipping[_-]?address|address|phone|mobile|e-?mail)(?:$|[_-])",
    re.IGNORECASE,
)
_SENSITIVE_TEXT = (
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [REDACTED]"),
    (re.compile(r"(?i)\b(?:sk|pk)-[A-Za-z0-9._-]{8,}"), "[REDACTED_KEY]"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[REDACTED_PHONE]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
)


def _safe_id(value: object) -> str:
    return value if isinstance(value, str) and _SAFE_ID.fullmatch(value) else ""


def _session_hash(session_id: str) -> str:
    return "sha256:" + hashlib.sha256(session_id.encode("utf-8", errors="replace")).hexdigest()[:24]


def _shopping_session() -> str:
    # 避免把应用上下文导入成 eventbus 的循环依赖。
    from app.infrastructure.context import ShoppingContext
    try:
        snapshot = ShoppingContext.current()
        return snapshot.shopping_session_id
    except (RuntimeError, LookupError, AttributeError):
        return ""


def current_correlation(session_id: str = "") -> dict[str, str]:
    result = dict(_correlation.get())
    session_id = session_id or _shopping_session()
    if session_id:
        result["session_id"] = _session_hash(session_id)
    from app.infrastructure.context import ShoppingContext
    snapshot = ShoppingContext.current()
    if snapshot is not None and snapshot.prompt_version:
        result.update(prompt_version=snapshot.prompt_version, prompt_variant=snapshot.prompt_variant,
                      prompt_deployment_id=snapshot.prompt_deployment_id)
    if snapshot is not None and snapshot.capability_digest:
        result["capability_digest"] = snapshot.capability_digest
    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        result["trace_id"] = f"{span_context.trace_id:032x}"
        result["span_id"] = f"{span_context.span_id:016x}"
    return {key: value for key, value in result.items() if value}


def _span_correlation(values: dict[str, str]) -> dict[str, str]:
    result = {}
    for key in ("request_id", "task_id"):
        if values.get(key):
            result[f"globex.{key}"] = values[key]
            result[f"langfuse.trace.metadata.{key}"] = values[key]
    if values.get("session_id"):
        result["globex.session_hash"] = values["session_id"]
        result["langfuse.session.id"] = values["session_id"]
    for key in ("prompt_version", "prompt_variant", "prompt_deployment_id", "capability_digest"):
        if values.get(key):
            result[f"globex.{key}"] = values[key]
    if values.get("prompt_version"):
        result["langfuse.trace.metadata.prompt_version"] = values["prompt_version"]
    if values.get("capability_digest"):
        result["langfuse.trace.metadata.capability_digest"] = values["capability_digest"]
    return result


def record_prompt_assignment() -> None:
    """分组发生于 API/worker 根 span 创建之后，补齐根 span 与后续子 span 的版本关联。"""
    trace.get_current_span().set_attributes(_span_correlation(current_correlation()))


@contextmanager
def correlate(*, request_id: str = "", task_id: str = "", session_id: str = ""):
    values = dict(_correlation.get())
    if request_id:
        values["request_id"] = _safe_id(request_id)
    if task_id:
        values["task_id"] = _safe_id(task_id)
    if session_id:
        values["session_id"] = _session_hash(session_id)
    token = _correlation.set(values)
    try:
        trace.get_current_span().set_attributes(_span_correlation(values))
        yield
    finally:
        _correlation.reset(token)


def inject_task_context(*, session_id: str, task_id: str) -> dict[str, str]:
    carrier: dict[str, str] = {}
    values = {**_correlation.get(), "task_id": _safe_id(task_id), "session_id": _session_hash(session_id)}
    _correlation.set(values)
    trace.get_current_span().set_attributes(_span_correlation(values))
    _propagator.inject(carrier)
    return {"traceparent": carrier.get("traceparent", ""), "tracestate": carrier.get("tracestate", ""),
            "request_id": values.get("request_id", "")}


@contextmanager
def trace_worker_task(task):
    # 只传播 W3C trace 字段，不接收或转发任意 baggage/业务正文。
    carrier = {key: value for key in ("traceparent", "tracestate")
               if isinstance(value := getattr(task, key, ""), str) and value}
    parent = _propagator.extract(carrier, context=context.Context())
    with correlate(request_id=getattr(task, "request_id", ""), task_id=task.task_id, session_id=task.shopping_session_id):
        with trace.get_tracer(__name__).start_as_current_span(
            "commerce.intent.consume", context=parent, kind=SpanKind.CONSUMER,
            record_exception=False, set_status_on_exception=False,
        ) as span:
            span.set_attributes(_span_correlation(current_correlation()))
            try:
                yield span
            except BaseException as error:
                span.set_attribute("error.type", type(error).__name__)
                span.set_status(Status(StatusCode.ERROR))
                if isinstance(error, asyncio.CancelledError):
                    span.set_attribute("globex.cancelled", True)
                raise


def install_log_correlation() -> None:
    global _logging_installed
    if _logging_installed:
        return
    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        values = current_correlation()
        for key in ("request_id", "task_id", "session_id", "trace_id", "span_id", "prompt_version", "capability_digest"):
            setattr(record, key, values.get(key, "-"))
        return record

    logging.setLogRecordFactory(factory)
    _logging_installed = True


class CorrelationSpanProcessor(SpanProcessor):
    """在当前上下文还存在时给所有 AgentScope 子 span 加相同的可检索关联属性。"""

    def on_start(self, span, parent_context=None) -> None:
        span.set_attributes(_span_correlation(current_correlation()))


def _redact_development_value(value):
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _SENSITIVE_FIELD.search(str(key)) else _redact_development_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_development_value(item) for item in value]
    if isinstance(value, str):
        for pattern, replacement in _SENSITIVE_TEXT:
            value = pattern.sub(replacement, value)
        return value
    return value


def _sanitize_development_payload(value, limit: int) -> tuple[str, bool]:
    """把只读工具 I/O 变成 Langfuse 可展示的、有界且脱敏的 JSON/文本。"""
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except (TypeError, ValueError):
            payload = value
    else:
        payload = value
    payload = _redact_development_value(payload)
    if isinstance(payload, str):
        rendered = payload
    else:
        try:
            rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
        except (TypeError, ValueError):
            rendered = str(payload)
    # JSON 解析失败时仍执行文本级掩码；例如 SDK 传来 Python repr。
    rendered = _redact_development_value(rendered)
    truncated = len(rendered) > limit
    if truncated:
        rendered = rendered[:limit] + f"…[TRUNCATED original_chars={len(rendered)}]"
    return rendered, truncated


def _sanitize_attributes(attributes, *, content_mode: str = "off") -> dict:
    result = {}
    tool_name = (attributes or {}).get("gen_ai.tool.name", "")
    development_tool = content_mode == "development" and tool_name in _DEVELOPMENT_TRACE_TOOLS
    retrieval_stage = (attributes or {}).get("globex.retrieval.stage", "")
    trace_stage = (attributes or {}).get("globex.trace.stage", "")
    development_rag = content_mode == "development" and retrieval_stage in _DEVELOPMENT_RAG_STAGES
    development_agent = content_mode == "development" and trace_stage in _DEVELOPMENT_AGENT_STAGES
    for key, value in (attributes or {}).items():
        if key in _SAFE_ATTRIBUTES:
            # 名称是固定技术标签；异常正文、业务字段和自由文本没有白名单入口。
            if isinstance(value, str):
                if not _SAFE_NAME.fullmatch(value):
                    continue
            elif isinstance(value, (tuple, list)):
                if not all(isinstance(item, str) and _SAFE_NAME.fullmatch(item) for item in value):
                    continue
            result[key] = value
        elif key in _CONTENT_FIELDS:
            result[_CONTENT_FIELDS[key]] = len(value) if isinstance(value, (str, tuple, list)) else 0
            expose_tool = development_tool and key.startswith("gen_ai.tool.call.")
            expose_observation = (development_rag or development_agent) and key.startswith("langfuse.observation.")
            if (expose_tool or expose_observation) and key in _DEVELOPMENT_CONTENT_LIMITS:
                rendered, truncated = _sanitize_development_payload(value, _DEVELOPMENT_CONTENT_LIMITS[key])
                result[key] = rendered
                result["globex.content.sanitized"] = True
                if truncated:
                    result["globex.content.truncated"] = True
            else:
                result["globex.content.redacted"] = True
    if content_mode != "off":
        result["globex.trace.content_mode"] = content_mode
    return result


def sanitize_span(span: ReadableSpan, *, content_mode: str = "off") -> ReadableSpan:
    attributes = _sanitize_attributes(span.attributes, content_mode=content_mode)
    operation = attributes.get("gen_ai.operation.name")
    if operation in {"chat", "invoke_agent", "execute_tool"}:
        attributes["langfuse.observation.type"] = {"chat": "generation", "invoke_agent": "agent", "execute_tool": "tool"}[operation]
    events = []
    for event in span.events:
        if event.name == "exception":
            exception_type = (event.attributes or {}).get("exception.type", "Exception")
            if not isinstance(exception_type, str) or not _SAFE_NAME.fullmatch(exception_type):
                exception_type = "Exception"
            events.append(Event("exception", {"exception.type": exception_type}, event.timestamp))
    resource = Resource({key: value for key, value in span.resource.attributes.items()
                         if key in {"service.name", "telemetry.sdk.name", "telemetry.sdk.language", "telemetry.sdk.version"}
                         and isinstance(value, str) and _SAFE_NAME.fullmatch(value)})
    scope = span.instrumentation_scope
    clean_scope = InstrumentationScope(
        scope.name if _SAFE_NAME.fullmatch(scope.name) else "instrumentation",
        scope.version if scope.version and _SAFE_NAME.fullmatch(scope.version) else None,
    ) if scope else None
    return ReadableSpan(
        name=span.name if _SAFE_NAME.fullmatch(span.name) else "operation",
        context=span.context, parent=span.parent, resource=resource, attributes=attributes,
        events=events, links=[Link(link.context, _sanitize_attributes(link.attributes)) for link in span.links],
        kind=span.kind, status=Status(span.status.status_code), start_time=span.start_time, end_time=span.end_time,
        instrumentation_scope=clean_scope,
    )


class SanitizingSpanExporter(SpanExporter):
    def __init__(self, exporter: SpanExporter, *, content_mode: str = "off") -> None:
        self._exporter = exporter
        self._content_mode = content_mode

    def export(self, spans) -> SpanExportResult:
        try:
            return self._exporter.export([sanitize_span(span, content_mode=self._content_mode) for span in spans])
        except Exception as error:
            # 不记录异常正文，以免导出器把含认证信息的配置或远端响应写进日志。
            logger.warning("OTLP 导出失败（%s）", type(error).__name__)
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        self._exporter.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._exporter.force_flush(timeout_millis)


def _export_settings(settings: Settings) -> tuple[str, dict[str, str]]:
    langfuse = LangfuseConfig(settings.langfuse_base_url, settings.langfuse_public_key,
                             settings.langfuse_secret_key)
    endpoint = settings.otlp_traces_endpoint or settings.otlp_endpoint
    if not endpoint:
        endpoint = langfuse.otlp_traces_endpoint
    elif not settings.otlp_traces_endpoint and not endpoint.rstrip("/").endswith("/v1/traces"):
        endpoint = endpoint.rstrip("/") + "/v1/traces"
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("OTLP 地址必须为无内嵌凭据、查询参数或片段的 HTTP(S) 地址")
    headers = {}
    # 显式 OTLP 目标优先，绝不能向另一个 collector 自动转发 Langfuse 密钥。
    if not langfuse.missing_fields():
        try:
            if endpoint == langfuse.otlp_traces_endpoint:
                headers = {"Authorization": langfuse.authorization_header,
                           "x-langfuse-ingestion-version": "4"}
        except ValueError:
            if not (settings.otlp_traces_endpoint or settings.otlp_endpoint):
                raise
    for item in (settings.otlp_traces_headers or settings.otlp_headers).split(","):
        if not item.strip():
            continue
        name, separator, value = item.partition("=")
        name, value = unquote(name.strip()), unquote(value.strip())
        if not separator or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name) or "\r" in value or "\n" in value:
            raise ValueError("OTLP 认证头格式无效")
        headers = {key: item for key, item in headers.items() if key.lower() != name.lower()}
        headers[name] = value
    return endpoint, headers

_BUDGET_HINT = (
    "<system-reminder>本次会话已达到 Token 预算上限。请立即停止调用工具，"
    "基于当前已获得的信息给买家一个明确的收尾回复（如实说明信息可能不完整）。</system-reminder>"
)


class _ExporterLogFilter(logging.Filter):
    def filter(self, record) -> bool:
        # 上游接收器失败响应可能回显认证/请求信息，禁止按 exporter 默认方式完整写日志。
        record.msg = "OTLP 传输告警：请检查接收端连通性与配置（响应正文已隐藏）"
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        return True


def create_tracer_provider(settings: Settings) -> TracerProvider:
    """构造可独立测试的 provider，不替换进程全局对象。"""
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    endpoint, headers = _export_settings(settings)
    if settings.otlp_timeout_seconds <= 0:
        raise ValueError("OTLP 超时必须为正数")
    exporter_logger = logging.getLogger("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    if not any(isinstance(item, _ExporterLogFilter) for item in exporter_logger.filters):
        exporter_logger.addFilter(_ExporterLogFilter())
    provider = TracerProvider(resource=Resource.create({"service.name": settings.otel_service_name}))
    provider.add_span_processor(CorrelationSpanProcessor())
    provider.add_span_processor(BatchSpanProcessor(SanitizingSpanExporter(OTLPSpanExporter(
        endpoint=endpoint, headers=headers, timeout=settings.otlp_timeout_seconds,
    ), content_mode=settings.trace_content_mode), max_queue_size=1024, max_export_batch_size=128, schedule_delay_millis=1000))
    return provider


def setup_tracing(settings: Settings) -> None:
    """配置无效或未配置都不影响业务；绝不记录地址中的秘密或认证头。"""
    global _initialized, _provider
    install_log_correlation()
    if _initialized or not (settings.otlp_traces_endpoint or settings.otlp_endpoint
                           or settings.langfuse_base_url or settings.langfuse_public_key
                           or settings.langfuse_secret_key):
        return
    if not isinstance(trace.get_tracer_provider(), trace.ProxyTracerProvider):
        logger.warning("已有全局 OTel Provider，本应用未替换或重复配置导出器")
        return
    try:
        provider = create_tracer_provider(settings)
        trace.set_tracer_provider(provider)
        _provider, _initialized = provider, True
        logger.info("OTel tracing 已启用，内容模式=%s，脱敏过滤已生效", settings.trace_content_mode)
    except Exception as error:
        logger.warning("OTel tracing 初始化失败，业务继续运行（%s）", type(error).__name__)


def shutdown_tracing() -> None:
    if _provider is not None:
        _provider.shutdown()


class TracingASGIMiddleware:
    """纯 ASGI 生命周期包含 SSE 的最后一帧，不读取或缓存请求/响应正文。"""

    def __init__(self, app) -> None:
        self.app = app
        install_log_correlation()

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.decode("latin-1").lower(): value.decode("latin-1")
                   for key, value in scope.get("headers", []) if key.lower() in {b"traceparent", b"tracestate"}}
        parent = _propagator.extract(headers, context=context.Context())
        request_id = uuid.uuid4().hex
        method = scope.get("method", "HTTP")
        with correlate(request_id=request_id):
            with trace.get_tracer(__name__).start_as_current_span(
                f"HTTP {method}", context=parent, kind=SpanKind.SERVER,
                attributes={"http.request.method": method}, record_exception=False, set_status_on_exception=False,
            ) as span:
                status = 500

                async def traced_send(message):
                    nonlocal status
                    if message["type"] == "http.response.start":
                        status = message["status"]
                        route = getattr(scope.get("route"), "path", "unmatched")
                        span.update_name(f"{method} {route}")
                        span.set_attribute("http.route", route)
                        span.set_attribute("http.response.status_code", status)
                        if status >= 500:
                            span.set_status(Status(StatusCode.ERROR))
                        response_headers = [(key, value) for key, value in message.get("headers", [])
                                            if key.lower() not in {b"x-request-id", b"x-trace-id"}]
                        response_headers.append((b"x-request-id", request_id.encode()))
                        trace_id = current_correlation().get("trace_id")
                        if trace_id:
                            response_headers.append((b"x-trace-id", trace_id.encode()))
                        message = {**message, "headers": response_headers}
                    await send(message)

                try:
                    await self.app(scope, receive, traced_send)
                except BaseException as error:
                    span.set_attribute("error.type", type(error).__name__)
                    span.set_status(Status(StatusCode.ERROR))
                    if isinstance(error, asyncio.CancelledError):
                        span.set_attribute("globex.cancelled", True)
                    raise
                finally:
                    logger.info("HTTP 请求结束 method=%s status=%s", method, status)


def build_agent_middlewares(settings: Settings) -> list:
    """全部 Agent 统一的中间件列表（Trace + 可选 Token 预算）。"""
    from app.infrastructure.context_compaction import EvidenceCompactionMiddleware
    from app.infrastructure.persistence.context_evidence import ContextEvidenceStore
    middlewares: list = [TracingMiddleware(), EvidenceCompactionMiddleware(
        ContextEvidenceStore(settings.data_dir / "context_evidence.db"))]
    if settings.context_strategy not in {'legacy', 'layered'}:
        raise ValueError('CONTEXT_STRATEGY 仅支持 legacy/layered')
    if settings.context_pruning_timing not in {'after_use', 'pressure'}:
        raise ValueError('CONTEXT_PRUNING_TIMING 必须是 after_use 或 pressure，入口有损只供实验')
    if settings.context_strategy == 'layered':
        from app.infrastructure.context_governance import LayeredContextMiddleware
        middlewares[1] = LayeredContextMiddleware(ContextEvidenceStore(settings.data_dir / 'context_evidence.db'),
            product_tokens=settings.context_product_tokens, target_tokens=settings.context_target_tokens, timing=settings.context_pruning_timing)
    if settings.reply_token_budget > 0:
        middlewares.append(
            ReplyBudgetControlMiddleware(
                token_budget=settings.reply_token_budget,
                hint_message=_BUDGET_HINT,
            ),
        )
    return middlewares

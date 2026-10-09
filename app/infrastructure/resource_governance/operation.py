"""Context-local operation identity shared by agents and HTTP clients."""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from .models import ContextScope


@dataclass(frozen=True)
class ExecutionIdentity:
    flow_id: str = "main"
    tool_call_id: str | None = None


_execution = ContextVar("globex_execution_identity", default=ExecutionIdentity())


def current_execution() -> ExecutionIdentity:
    return _execution.get()


@contextmanager
def execution_identity(*, flow_id: str, tool_call_id: str | None = None):
    token = _execution.set(ExecutionIdentity(flow_id, tool_call_id))
    try:
        yield _execution.get()
    finally:
        _execution.reset(token)


@dataclass
class OperationContext:
    logical_call_id: str
    operation: str
    component: str
    context_scope: ContextScope
    attempt: int = 1
    # Populated immediately before the OpenAI-compatible HTTP request is sent.
    # Payload content remains request-local and is never traced or persisted.
    pre_call_comparison: Any | None = None
    request_traits: dict[str, str] | None = None
    information_need_id: str | None = None


_operation: ContextVar[OperationContext | None] = ContextVar(
    "globex_resource_operation", default=None,
)


def current_operation() -> OperationContext | None:
    return _operation.get()


@contextmanager
def resource_operation(
    operation: str, *, component: str, context_scope: ContextScope,
    logical_call_id: str | None = None,
    information_need_id: str | None = None,
):
    context = OperationContext(
        logical_call_id=logical_call_id or uuid.uuid4().hex,
        operation=operation,
        component=component,
        context_scope=context_scope,
        information_need_id=information_need_id,
    )
    token = _operation.set(context)
    try:
        yield context
    finally:
        _operation.reset(token)


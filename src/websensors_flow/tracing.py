"""Lightweight backend-agnostic tracing primitives."""

from __future__ import annotations

import uuid
from time import perf_counter
from typing import Any, Callable

from websensors_flow.events import PipelineEvent


class TraceSpan:
    """Context manager that emits span start/completion/failure events."""

    def __init__(
        self,
        *,
        name: str,
        trace_id: str,
        parent_span_id: str | None,
        emit: Callable[[PipelineEvent], None],
        event_factory: Callable[..., PipelineEvent],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.trace_id = trace_id
        self.span_id = uuid.uuid4().hex[:16]
        self.parent_span_id = parent_span_id
        self.emit = emit
        self.event_factory = event_factory
        self.metadata = metadata or {}
        self._started = 0.0

    def __enter__(self) -> "TraceSpan":
        self._started = perf_counter()
        self.emit(self.event_factory(
            event_type="trace_started",
            status="running",
            text=self.name,
            trace_id=self.trace_id,
            span_id=self.span_id,
            parent_span_id=self.parent_span_id,
            metadata={"span_name": self.name, **self.metadata},
        ))
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        duration = perf_counter() - self._started
        if exc is None:
            self.emit(self.event_factory(
                event_type="trace_completed",
                status="success",
                text=self.name,
                duration_seconds=duration,
                trace_id=self.trace_id,
                span_id=self.span_id,
                parent_span_id=self.parent_span_id,
                metadata={"span_name": self.name, **self.metadata},
            ))
        else:
            self.emit(self.event_factory(
                event_type="trace_failed",
                status="failed",
                text=self.name,
                duration_seconds=duration,
                trace_id=self.trace_id,
                span_id=self.span_id,
                parent_span_id=self.parent_span_id,
                error_type=exc_type.__name__ if exc_type else None,
                error_message=str(exc),
                metadata={"span_name": self.name, **self.metadata},
            ))

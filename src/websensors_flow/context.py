"""Pipeline context passed to every user-defined step."""

from __future__ import annotations

import uuid
from typing import Any, Callable

from websensors_flow.config import FlowSettings
from websensors_flow.events import PipelineEvent
from websensors_flow.logger import PipelineLogger
from websensors_flow.progress import ProgressTracker
from websensors_flow.tracing import TraceSpan


class PipelineContext:
    """Execution context available to user steps."""

    def __init__(
        self,
        *,
        settings: FlowSettings,
        run_id: str,
        pipeline_name: str,
        logger: PipelineLogger | None = None,
        emit: Callable[[PipelineEvent], None] | None = None,
    ):
        self.settings = settings
        self.config = settings
        self.run_id = run_id
        self.pipeline_name = pipeline_name
        self.environment = settings.environment.name
        self.current_step_name: str | None = None
        self.current_step_index: int | None = None
        self.step_config: dict[str, Any] = {}
        self.step_configs: dict[str, dict[str, Any]] = settings.step_configs
        self.state: dict[str, Any] = {"models": []}
        self.logger = logger or PipelineLogger(
            pipeline_name=pipeline_name,
            run_id=run_id,
            environment=settings.environment.name,
        )
        self.log = self.logger
        self._emit = emit
        self.trace_id = uuid.uuid4().hex

    def set_current_step(self, step_name: str, step_index: int) -> None:
        self.current_step_name = step_name
        self.current_step_index = step_index
        self.step_config = self.settings.get_step_config(step_name)
        self.logger.bind_step(step_name=step_name, step_index=step_index)

    def clear_current_step(self) -> None:
        self.current_step_name = None
        self.current_step_index = None
        self.step_config = {}
        self.logger.bind_step(step_name=None, step_index=None)

    def get_step_config(self, step_name: str | None = None) -> dict[str, Any]:
        if step_name is None:
            return dict(self.step_config)
        return self.settings.get_step_config(step_name)

    def _event(self, **kwargs: Any) -> PipelineEvent:
        return PipelineEvent(
            pipeline_name=self.pipeline_name,
            run_id=self.run_id,
            environment=self.environment,
            step_name=self.current_step_name,
            step_index=self.current_step_index,
            trace_id=kwargs.pop("trace_id", self.trace_id),
            **kwargs,
        )

    def progress(self, *, total: int, description: str, unit: str = "items", every: int = 1) -> ProgressTracker:
        """Create a loop progress reporter with elapsed time, rate, and ETA."""
        if self._emit is None:
            raise RuntimeError("Progress reporting is unavailable because the context has no event emitter.")
        return ProgressTracker(
            total=total,
            description=description,
            unit=unit,
            every=every,
            emit=self._emit,
            event_factory=self._event,
        )

    def trace(self, name: str, *, metadata: dict[str, Any] | None = None, parent_span_id: str | None = None) -> TraceSpan:
        """Create a trace span visible to all configured observers."""
        if self._emit is None:
            raise RuntimeError("Tracing is unavailable because the context has no event emitter.")
        return TraceSpan(
            name=name,
            trace_id=self.trace_id,
            parent_span_id=parent_span_id,
            emit=self._emit,
            event_factory=self._event,
            metadata=metadata,
        )

    def register_model(
        self,
        name: str,
        *,
        provider: str | None = None,
        role: str | None = None,
        endpoint: str | None = None,
        version: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Register a model used by the current step and emit an observability event."""
        record = {
            "name": name,
            "provider": provider,
            "role": role,
            "endpoint": endpoint,
            "version": version,
            **(metadata or {}),
        }
        clean = {k: v for k, v in record.items() if v not in (None, "")}
        if clean not in self.state["models"]:
            self.state["models"].append(clean)
        if self._emit is not None:
            self._emit(self._event(
                event_type="model_registered",
                status="running",
                text=f"Model in use: {name}",
                params={k: v for k, v in clean.items() if k in {"name", "provider", "role", "version"}},
                metadata={k: v for k, v in clean.items() if k not in {"name", "provider", "role", "version"}},
            ))

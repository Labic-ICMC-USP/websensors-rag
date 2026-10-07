"""Step-facing logging facade."""

from __future__ import annotations

import traceback
from datetime import datetime, timezone
from typing import Any, Callable

from websensors_flow.events import PipelineEvent


class PipelineLogger:
    """Small logging object available inside every step.

    The step developer writes structured messages through this object. The
    object does not expose Graylog, MLflow, console handlers, or any backend
    detail. The pipeline decides where each event is published.
    """

    def __init__(
        self,
        *,
        pipeline_name: str,
        run_id: str,
        environment: str,
        emit: Callable[[PipelineEvent], None] | None = None,
    ):
        self.pipeline_name = pipeline_name
        self.run_id = run_id
        self.environment = environment
        self._emit = emit
        self.step_name: str | None = None
        self.step_index: int | None = None

    def bind_step(self, *, step_name: str | None, step_index: int | None) -> None:
        """Attach the current step identity to future log events."""

        self.step_name = step_name
        self.step_index = step_index

    def debug(self, message: str, **kwargs: Any) -> None:
        """Emit a debug message."""

        self.log("DEBUG", message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        """Emit an informational message."""

        self.log("INFO", message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        """Emit a warning message."""

        self.log("WARNING", message, **kwargs)

    def error(self, message: str, *, exc: Exception | None = None, **kwargs: Any) -> None:
        """Emit an error message with optional exception details."""

        metadata = dict(kwargs.pop("metadata", {}) or {})
        if exc is not None:
            metadata.update(
                {
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "traceback_text": traceback.format_exc(),
                }
            )
        self.log("ERROR", message, metadata=metadata, **kwargs)

    def log(
        self,
        level: str,
        message: str,
        *,
        metrics: dict[str, int | float | bool] | None = None,
        params: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        artifacts: dict[str, str] | None = None,
    ) -> None:
        """Emit a structured user log event."""

        if self._emit is None:
            return
        event = PipelineEvent(
            event_type="user_log",
            pipeline_name=self.pipeline_name,
            run_id=self.run_id,
            environment=self.environment,
            timestamp=datetime.now(timezone.utc),
            step_name=self.step_name,
            step_index=self.step_index,
            status="running",
            level=level.upper(),
            text=message,
            metrics=metrics or {},
            params=params or {},
            metadata=metadata or {},
            artifacts=artifacts or {},
        )
        self._emit(event)

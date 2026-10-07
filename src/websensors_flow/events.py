"""Internal event models emitted by the pipeline engine."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from websensors_flow.result import MetricRecord


class PipelineEvent(BaseModel):
    """Structured event sent to observers."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    event_type: str
    pipeline_name: str
    run_id: str
    environment: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    level: str = "INFO"
    step_name: str | None = None
    step_index: int | None = None
    status: str | None = None
    duration_seconds: float | None = None
    text: str | None = None
    metrics: dict[str, int | float | bool] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    metric_records: list[MetricRecord] = Field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None
    traceback_text: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None

    def as_log_dict(self) -> dict[str, Any]:
        """Return a compact dictionary for structured log backends."""

        data = self.model_dump(mode="json")
        return {key: value for key, value in data.items() if value not in (None, {}, [])}

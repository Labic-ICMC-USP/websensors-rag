"""Pydantic report models for pipeline execution."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from websensors_flow.result import MetricRecord


class StepExecutionRecord(BaseModel):
    """Execution summary for one step."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    step_name: str
    step_index: int
    status: str
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    text: str | None = None
    metrics: dict[str, int | float | bool] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    metric_records: list[MetricRecord] = Field(default_factory=list)
    input_type: str | None = None
    output_type: str | None = None
    has_output: bool = False
    error_type: str | None = None
    error_message: str | None = None
    traceback_text: str | None = None


class ExecutionReport(BaseModel):
    """Complete execution report for a pipeline run."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    pipeline_name: str
    run_id: str
    environment: str
    project_version: str | None = None
    status: str = "running"
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    steps: list[StepExecutionRecord] = Field(default_factory=list)
    metrics: dict[str, int | float | bool] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def complete(self, status: str) -> None:
        """Mark the report as finished."""

        self.status = status
        self.finished_at = datetime.now(timezone.utc)
        self.duration_seconds = (self.finished_at - self.started_at).total_seconds()
        self.metrics.update(
            {
                "pipeline_success": 1 if status == "success" else 0,
                "pipeline_failed": 1 if status == "failed" else 0,
                "steps_total": len(self.steps),
                "steps_success": sum(1 for step in self.steps if step.status == "success"),
                "steps_failed": sum(1 for step in self.steps if step.status == "failed"),
                "metrics_count": sum(len(step.metrics) for step in self.steps),
                "params_count": sum(len(step.params) for step in self.steps),
                "artifacts_count": sum(len(step.artifacts) for step in self.steps),
                "metric_records_count": sum(len(step.metric_records) for step in self.steps),
                "warnings_count": sum(len(step.warnings) for step in self.steps),
            }
        )

    def to_markdown(self) -> str:
        """Render the report as Markdown."""

        lines = [
            f"# Pipeline Run Report",
            "",
            f"- **Pipeline:** `{self.pipeline_name}`",
            f"- **Run ID:** `{self.run_id}`",
            f"- **Environment:** `{self.environment}`",
            f"- **Status:** `{self.status}`",
            f"- **Duration seconds:** `{self.duration_seconds if self.duration_seconds is not None else '-'}`",
            "",
            "## Steps",
            "",
        ]
        for step in self.steps:
            lines.extend(
                [
                    f"### {step.step_index}. {step.step_name}",
                    "",
                    f"- **Status:** `{step.status}`",
                    f"- **Duration seconds:** `{step.duration_seconds:.6f}`",
                    f"- **Input type:** `{step.input_type or '-'}`",
                    f"- **Output type:** `{step.output_type or '-'}`",
                    "",
                ]
            )
            if step.text:
                lines.extend(["**Text**", "", step.text, ""])
            if step.metrics:
                lines.extend(["**Metrics**", ""])
                for key, value in step.metrics.items():
                    lines.append(f"- `{key}`: `{value}`")
                lines.append("")
            if step.params:
                lines.extend(["**Params**", ""])
                for key, value in step.params.items():
                    lines.append(f"- `{key}`: `{value}`")
                lines.append("")
            if step.artifacts:
                lines.extend(["**Artifacts**", ""])
                for key, value in step.artifacts.items():
                    lines.append(f"- `{key}`: `{value}`")
                lines.append("")
            if step.metric_records:
                lines.extend(["**Metric records**", ""])
                for record in step.metric_records:
                    label = record.params.get("model_name") or record.params.get("name") or record.name
                    lines.append(f"- `{record.name}`: `{label}`")
                    if record.metrics:
                        for key, value in record.metrics.items():
                            lines.append(f"  - `{key}`: `{value}`")
                lines.append("")
            if step.error_type:
                lines.extend(
                    [
                        "**Error**",
                        "",
                        f"- `{step.error_type}`: {step.error_message}",
                        "",
                    ]
                )
        return "\n".join(lines)


class PipelineRunResult(BaseModel):
    """Return value from a pipeline execution.

    The result is returned for both successful and failed user-step runs when
    ``runtime.raise_on_failure`` is false. The all-or-nothing policy is still
    preserved because failed runs stop immediately and later steps are not
    executed.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    output: Any = None
    has_output: bool = False
    report: ExecutionReport
    failure: Any = None

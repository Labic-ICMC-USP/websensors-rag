"""Pydantic result models for step outputs, metric records, and failures.

The framework is object-agnostic for step input/output, but it is strict about
observability. A successful step must return a :class:`StepResult` containing a
human-readable text and a dictionary of numeric metrics.

For repeated comparable observations produced inside one step, such as one
record per tested machine-learning model, a step can also return
``metric_records``. The step still does not call MLflow, Graylog, or any other
observer directly. It only returns structured observability data. Observers
then decide how to publish those records.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

MetricValue = int | float | bool


class MetricRecord(BaseModel):
    """Repeated structured observation emitted by a step.

    A ``MetricRecord`` is useful when a single step compares several entities
    and each entity must appear as a comparable row in an observability backend.

    Examples include:

    - one record per candidate model tested by GridSearchCV;
    - one record per data source collected by an ingestion step;
    - one record per label/class evaluated by a classifier;
    - one record per external API/tool called by an agent.

    The user step only returns these records. It does not call MLflow.
    The MLflow observer can publish each record as a nested run, creating
    columns such as ``params.model_name`` and ``metrics.cv_f1_macro``.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = Field(min_length=1)
    metrics: dict[str, MetricValue] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("MetricRecord.name must be a non-empty string.")
        return value.strip()

    @field_validator("metrics")
    @classmethod
    def metrics_must_be_numeric(cls, value: dict[str, MetricValue]) -> dict[str, MetricValue]:
        for key, metric in value.items():
            if not isinstance(metric, (int, float, bool)):
                raise ValueError(
                    f"MetricRecord metric '{key}' must be int, float, or bool. "
                    "Use params or metadata for non-numeric values."
                )
        return value


class StepResult(BaseModel):
    """Standard successful return value for every pipeline step.

    Attributes
    ----------
    output:
        Optional object to pass to the next step. The framework does not inspect
        or serialize this object. It can be any Python object.
    has_output:
        Whether the pipeline should pass ``output`` as the input of the next
        step. This flag exists because ``None`` may be a valid output.
    text:
        Mandatory human-readable summary of what the step did. It is written to
        reports and logged to observability backends.
    metrics:
        Mandatory numeric metrics for the step as a whole. Only numeric and
        boolean values are accepted because MLflow metrics are numeric.
    params:
        Parameters used by the step. These are logged to MLflow as parameters.
    metadata:
        Non-numeric, auxiliary information used in reports and logs.
    artifacts:
        Mapping from artifact name to local path. Observers may upload these
        files to MLflow or mention them in reports.
    warnings:
        Human-readable warnings produced by the step.
    metric_records:
        Optional repeated observations emitted by the step. Each record has its
        own params, metrics, metadata, and artifacts. This enables model-level
        comparison in MLflow without the user step importing or calling MLflow.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    output: Any = None
    has_output: bool = False
    text: str = Field(min_length=1)
    metrics: dict[str, MetricValue] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    metric_records: list[MetricRecord] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("StepResult.text must be a non-empty string.")
        return value.strip()

    @field_validator("metrics")
    @classmethod
    def metrics_must_be_numeric(cls, value: dict[str, MetricValue]) -> dict[str, MetricValue]:
        for key, metric in value.items():
            if not isinstance(metric, (int, float, bool)):
                raise ValueError(
                    f"Metric '{key}' must be int, float, or bool. "
                    "Use params or metadata for non-numeric values."
                )
        return value


class StepFailure(BaseModel):
    """Structured failure created by the framework when a step fails."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    step_name: str
    step_index: int
    text: str
    error_type: str
    error_message: str
    traceback_text: str
    duration_seconds: float
    input_type: str | None = None
    metrics: dict[str, MetricValue] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

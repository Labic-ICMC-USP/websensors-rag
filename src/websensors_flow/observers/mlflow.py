"""MLflow observer for parameters, metrics, artifacts, and metric records."""

from __future__ import annotations

import io
import json
import logging
import os
import socket
import tempfile
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

from websensors_flow.config import FlowSettings, MLflowConfig
from websensors_flow.events import PipelineEvent
from websensors_flow.exceptions import ObserverError, PreflightCheckError
from websensors_flow.observers.base import PipelineObserver
from websensors_flow.result import MetricRecord


class MLflowObserver(PipelineObserver):
    """Record pipeline execution in MLflow."""

    name = "mlflow"

    def __init__(self, config: MLflowConfig, *, settings: FlowSettings):
        self.config = config
        self.settings = settings
        self._mlflow = None
        self._run_active = False
        self._tmpdir: tempfile.TemporaryDirectory[str] | None = None
        self._events: list[dict[str, Any]] = []
        self._event_index = 0
        self._logged_params: dict[str, str] = {}
        self._active_spans: dict[str, Any] = {}

    def _configure_mlflow_terminal_output(self) -> None:
        """Keep MLflow messages out of the terminal UI."""

        os.environ.setdefault("MLFLOW_DISABLE_ENV_CREATION", "true")
        os.environ.setdefault("MLFLOW_ENABLE_SYSTEM_METRICS_LOGGING", "true")
        os.environ.setdefault("MLFLOW_LOGGING_LEVEL", "ERROR")
        logging.getLogger("mlflow").setLevel(logging.ERROR)
        logging.getLogger("mlflow.tracking").setLevel(logging.ERROR)
        logging.getLogger("mlflow.utils").setLevel(logging.ERROR)

    def validate_ready(self) -> None:
        self._configure_mlflow_terminal_output()
        try:
            import mlflow  # type: ignore
            from mlflow.tracking import MlflowClient  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise PreflightCheckError("MLflow preflight failed because the 'mlflow' package is not installed.") from exc

        self._mlflow = mlflow
        try:
            if self.config.http_request_timeout:
                os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"] = str(self.config.http_request_timeout)
            if self.config.auth.enabled:
                if self.config.auth.username:
                    os.environ["MLFLOW_TRACKING_USERNAME"] = self.config.auth.username
                if self.config.auth.password:
                    os.environ["MLFLOW_TRACKING_PASSWORD"] = self.config.auth.password
                if self.config.auth.token:
                    os.environ["MLFLOW_TRACKING_TOKEN"] = self.config.auth.token

            self._check_tracking_uri_socket()
            with self._quiet_mlflow():
                mlflow.set_tracking_uri(self.config.tracking_uri)
                client = MlflowClient(tracking_uri=self.config.tracking_uri)
                client.search_experiments(max_results=1)
                mlflow.set_experiment(self.config.experiment_name)
        except PreflightCheckError:
            raise
        except Exception as exc:
            raise PreflightCheckError(
                "MLflow preflight failed because the tracking server could not be reached at "
                f"{self.config.tracking_uri}."
            ) from exc

    def _check_tracking_uri_socket(self) -> None:
        parsed = urlparse(str(self.config.tracking_uri or ""))
        if parsed.scheme not in {"http", "https"}:
            return
        host = parsed.hostname
        if not host:
            raise PreflightCheckError("MLflow preflight failed because the tracking URI has no host.")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            with socket.create_connection((host, port), timeout=float(self.config.connect_timeout_seconds)):
                pass
        except OSError as exc:
            raise PreflightCheckError(
                "MLflow preflight failed because no TCP connection could be opened to "
                f"{host}:{port} within {self.config.connect_timeout_seconds} seconds."
            ) from exc

    def preflight_probe(self, event: PipelineEvent) -> None:
        if self._mlflow is None:
            raise ObserverError("MLflow observer was not initialized.")

        run_name = f"websensors-flow-preflight:{event.pipeline_name}:{event.run_id}"
        run_started = False
        try:
            with self._quiet_mlflow():
                self._start_run_quiet(run_name=run_name, nested=True)
                run_started = True
                self._mlflow.set_tags(
                    {
                        "run_type": "preflight_probe",
                        "pipeline_name": event.pipeline_name,
                        "run_id": event.run_id,
                        "environment": event.environment,
                        "observer_probe": "true",
                    }
                )
                self._mlflow.log_param("preflight.project.name", event.pipeline_name)
                self._mlflow.log_param("preflight.environment", event.environment)
                self._mlflow.log_metric("preflight.probe", 1)
                self._mlflow.log_metric("preflight.steps_total", float(event.metadata.get("steps_total", 0)))
                self._mlflow.end_run(status="FINISHED")
        except Exception as exc:
            if run_started:
                try:
                    with self._quiet_mlflow():
                        self._mlflow.end_run(status="FAILED")
                except Exception:
                    pass
            raise PreflightCheckError(
                "MLflow preflight probe failed because a test run could not be written to the tracking server."
            ) from exc

    def on_event(self, event: PipelineEvent) -> None:
        if self._mlflow is None:
            raise ObserverError("MLflow observer was not initialized.")
        self._append_event(event)
        try:
            if event.event_type == "pipeline_started":
                self._start_run(event)
            elif event.event_type == "step_started":
                self._log_step_started(event)
            elif event.event_type == "step_completed":
                self._log_step_success(event)
            elif event.event_type == "step_failed":
                self._log_step_failure(event)
            elif event.event_type == "user_log":
                self._log_user_message(event)
            elif event.event_type == "progress":
                self._log_progress(event)
            elif event.event_type == "model_registered":
                self._log_model_registered(event)
            elif event.event_type == "trace_started":
                self._start_trace_span(event)
            elif event.event_type in {"trace_completed", "trace_failed"}:
                self._end_trace_span(event)
            elif event.event_type == "pipeline_completed":
                self._log_pipeline_completed(event)
            elif event.event_type == "pipeline_failed":
                self._log_pipeline_failed(event)
        except Exception as exc:
            raise ObserverError(f"MLflow observer failed while handling event '{event.event_type}'.") from exc

    def _start_run(self, event: PipelineEvent) -> None:
        assert self._mlflow is not None
        run_name = self.config.run_name or f"{event.pipeline_name}:{event.environment}:{event.run_id}"
        with self._quiet_mlflow():
            self._start_run_quiet(run_name=run_name)
            self._run_active = True
            self._tmpdir = tempfile.TemporaryDirectory(prefix="websensors_flow_mlflow_")
            self._mlflow.set_tags(
                {
                    "pipeline_name": event.pipeline_name,
                    "run_id": event.run_id,
                    "environment": event.environment,
                    "project_version": self.settings.project.version,
                    "error_policy": "all_or_nothing",
                    "run_type": "pipeline",
                    "flow_source_path": self.settings.source_path or "",
                }
            )
            for key, value in self.settings.environment.tags.items():
                self._mlflow.set_tag(f"environment.{key}", value)
            self._mlflow.log_params(
                {
                    "project.name": self.settings.project.name,
                    "project.version": self.settings.project.version,
                    "environment.name": self.settings.environment.name,
                    "runtime.fail_fast": self.settings.runtime.fail_fast,
                    "runtime.raise_on_failure": self.settings.runtime.raise_on_failure,
                    "runtime.include_traceback": self.settings.runtime.include_traceback,
                    "steps.total": len(self.settings.steps),
                    "observability.graylog.enabled": self.settings.observability.graylog.enabled,
                    "observability.mlflow.enabled": self.settings.observability.mlflow.enabled,
                }
            )
            for key, value in self.settings.pipeline.params.items():
                self._log_param_safe(f"pipeline.params.{key}", value)
            self._log_settings_artifacts()

    def _log_step_started(self, event: PipelineEvent) -> None:
        assert self._mlflow is not None
        prefix = self._safe_name(event.step_name or "step")
        self._mlflow.log_metric(f"{prefix}.started", 1)
        self._log_metadata_artifact(event, subdir="step_started")

    def _log_step_success(self, event: PipelineEvent) -> None:
        assert self._mlflow is not None
        prefix = self._safe_name(event.step_name or "step")
        if event.duration_seconds is not None:
            self._mlflow.log_metric(f"{prefix}.duration_seconds", event.duration_seconds)
        self._mlflow.log_metric(f"{prefix}.success", 1)
        self._mlflow.log_metric(f"{prefix}.failed", 0)
        self._mlflow.log_metric(f"{prefix}.metric_records", len(event.metric_records))
        self._mlflow.log_metric(f"{prefix}.artifacts", len(event.artifacts))
        self._mlflow.log_metric(f"{prefix}.warnings", len(event.warnings))
        for key, value in event.metrics.items():
            self._log_metric_safe(f"{prefix}.{key}", value)
        for key, value in event.params.items():
            self._log_param_safe(f"{prefix}.{key}", value)
        self._log_metadata_tags(event, prefix=f"{prefix}.metadata")
        self._log_text_artifact(event, subdir="steps")
        self._log_metadata_artifact(event, subdir="steps")
        self._log_declared_artifacts(event)
        self._log_dataset_inputs(event)
        self._log_model_from_artifacts(event)
        self._log_metric_records(event)
        self._log_metric_records_table(event)

    def _log_step_failure(self, event: PipelineEvent) -> None:
        assert self._mlflow is not None
        prefix = self._safe_name(event.step_name or "step")
        if event.duration_seconds is not None:
            self._mlflow.log_metric(f"{prefix}.duration_seconds", event.duration_seconds)
        self._mlflow.log_metric(f"{prefix}.success", 0)
        self._mlflow.log_metric(f"{prefix}.failed", 1)
        if event.error_type:
            self._mlflow.set_tag("failed_step", event.step_name or "")
            self._mlflow.set_tag("error_type", event.error_type)
        self._log_text_artifact(event, subdir="errors")
        self._log_metadata_artifact(event, subdir="errors")
        if event.traceback_text:
            self._log_text_file(
                f"Traceback for {event.step_name}\n\n{event.traceback_text}",
                artifact_path=f"errors/{event.step_name}_traceback.txt",
            )

    def _log_user_message(self, event: PipelineEvent) -> None:
        assert self._mlflow is not None
        prefix = self._safe_name(event.step_name or "pipeline")
        self._mlflow.log_metric(f"{prefix}.user_log_events", 1, step=self._event_index)
        for key, value in event.metrics.items():
            self._log_metric_safe(f"{prefix}.{key}", value)
        for key, value in event.params.items():
            self._log_param_safe(f"{prefix}.{key}", value)
        self._log_metadata_tags(event, prefix=f"{prefix}.log_metadata")
        self._log_text_artifact(event, subdir="logs")
        self._log_metadata_artifact(event, subdir="logs")
        self._log_declared_artifacts(event)

    def _log_progress(self, event: PipelineEvent) -> None:
        assert self._mlflow is not None
        prefix = self._safe_name(event.step_name or "pipeline")
        for key in ("progress_percent", "progress_current", "progress_total"):
            if key in event.metrics:
                self._log_metric_safe(f"{prefix}.{key}", event.metrics[key])
        eta = event.metadata.get("eta_seconds")
        if eta is not None:
            self._log_metric_safe(f"{prefix}.progress_eta_seconds", float(eta))

    def _log_model_registered(self, event: PipelineEvent) -> None:
        assert self._mlflow is not None
        prefix = self._safe_name(event.step_name or "pipeline")
        index = sum(1 for item in self._events if item.get("event_type") == "model_registered")
        for key, value in event.params.items():
            self._log_param_safe(f"{prefix}.model_{index}.{key}", value)
        for key, value in event.metadata.items():
            self._set_tag_safe(f"{prefix}.model_{index}.{key}", value)

    def _start_trace_span(self, event: PipelineEvent) -> None:
        assert self._mlflow is not None
        if not event.span_id:
            return
        start_span = getattr(self._mlflow, "start_span_no_context", None)
        if callable(start_span):
            try:
                span = start_span(name=event.text or event.metadata.get("span_name") or "span")
                for key, value in event.metadata.items():
                    try:
                        span.set_attribute(str(key), value)
                    except Exception:
                        pass
                self._active_spans[event.span_id] = span
            except Exception:
                pass

    def _end_trace_span(self, event: PipelineEvent) -> None:
        assert self._mlflow is not None
        if event.duration_seconds is not None:
            prefix = self._safe_name(event.step_name or "pipeline")
            span_name = self._safe_name(str(event.metadata.get("span_name") or event.text or "span"))
            self._log_metric_safe(f"{prefix}.trace.{span_name}.duration_seconds", event.duration_seconds)
        span = self._active_spans.pop(event.span_id or "", None)
        if span is not None:
            try:
                if event.event_type == "trace_failed":
                    span.set_attribute("error_type", event.error_type or "")
                    span.set_attribute("error_message", event.error_message or "")
                span.end()
            except Exception:
                pass

    def _log_pipeline_completed(self, event: PipelineEvent) -> None:
        assert self._mlflow is not None
        self._mlflow.log_metric("pipeline.success", 1)
        self._mlflow.log_metric("pipeline.failed", 0)
        if event.duration_seconds is not None:
            self._mlflow.log_metric("pipeline.duration_seconds", event.duration_seconds)
        for key, value in event.metrics.items():
            self._log_metric_safe(f"pipeline.{key}", value)
        self._mlflow.set_tag("pipeline_status", "success")
        self._log_metadata_artifact(event, subdir="pipeline")

    def _log_pipeline_failed(self, event: PipelineEvent) -> None:
        assert self._mlflow is not None
        self._mlflow.log_metric("pipeline.success", 0)
        self._mlflow.log_metric("pipeline.failed", 1)
        if event.duration_seconds is not None:
            self._mlflow.log_metric("pipeline.duration_seconds", event.duration_seconds)
        for key, value in event.metrics.items():
            self._log_metric_safe(f"pipeline.{key}", value)
        self._mlflow.set_tag("pipeline_status", "failed")
        if event.error_type:
            self._mlflow.set_tag("pipeline_error_type", event.error_type)
        self._log_metadata_artifact(event, subdir="pipeline")

    def _metric_name(self, step_name: str | None, key: str) -> str:
        prefix = step_name or "pipeline"
        return f"{self._safe_name(prefix)}.{self._safe_name(key)}"

    @staticmethod
    def _safe_name(value: str) -> str:
        cleaned = str(value).replace(" ", "_").replace("/", "_").replace(":", "_")
        cleaned = cleaned.replace(".", "_").replace("-", "_")
        return "".join(char for char in cleaned if char.isalnum() or char == "_")[:240]

    def _log_metric_records(self, event: PipelineEvent) -> None:
        for index, record in enumerate(event.metric_records, start=1):
            self._log_metric_record(event, record, index=index)

    def _log_metric_record(self, event: PipelineEvent, record: MetricRecord, *, index: int) -> None:
        assert self._mlflow is not None
        entity_name = record.params.get("model_name") or record.params.get("class_name") or record.params.get("name") or record.params.get("id") or str(index)
        run_name = f"{event.step_name or 'step'}:{record.name}:{entity_name}"
        with self._nested_run(run_name=run_name):
            self._mlflow.set_tags(
                {
                    "run_type": "metric_record",
                    "record_type": record.name,
                    "parent_pipeline_name": event.pipeline_name,
                    "parent_run_id": event.run_id,
                    "step_name": event.step_name or "",
                    "step_index": str(event.step_index or ""),
                    "environment": event.environment,
                }
            )
            self._mlflow.log_param("record_name", record.name)
            self._mlflow.log_param("record_index", index)
            for key, value in record.params.items():
                self._log_param_safe(key, value)
            for key, value in record.metrics.items():
                self._log_metric_safe(key, value)
            for key, value in record.metadata.items():
                self._set_tag_safe(key, value)
            self._log_record_artifacts(event, record)

    def _log_metric_records_table(self, event: PipelineEvent) -> None:
        if not event.metric_records:
            return
        rows = []
        for index, record in enumerate(event.metric_records, start=1):
            rows.append(
                {
                    "index": index,
                    "name": record.name,
                    "params": record.params,
                    "metrics": record.metrics,
                    "metadata": record.metadata,
                    "artifacts": record.artifacts,
                }
            )
        self._log_json_file(rows, artifact_path=f"metric_records/{event.step_name}/records.json")


    def _start_run_quiet(self, *, run_name: str, nested: bool = False):
        assert self._mlflow is not None
        kwargs = {"run_name": run_name, "nested": nested}
        try:
            return self._mlflow.start_run(**kwargs, log_system_metrics=True)
        except TypeError:
            return self._mlflow.start_run(**kwargs)

    def _log_dataset_inputs(self, event: PipelineEvent) -> None:
        assert self._mlflow is not None
        try:
            import pandas as pd
        except Exception:
            pd = None
        for record in event.metric_records:
            if record.name != "dataset":
                continue
            dataset_name = str(record.params.get("dataset_name") or record.params.get("name") or event.step_name or "dataset")
            dataset_source = str(record.params.get("source") or record.artifacts.get("dataset_sample") or "")
            artifact_path = record.artifacts.get("dataset_sample") or record.artifacts.get("dataframe_sample")
            try:
                dataset = None
                if pd is not None and artifact_path and Path(artifact_path).exists():
                    dataframe = pd.read_csv(artifact_path)
                    dataset = self._mlflow.data.from_pandas(dataframe, source=dataset_source or artifact_path, name=dataset_name)
                elif dataset_source:
                    dataset = self._mlflow.data.from_numpy([], source=dataset_source, name=dataset_name)
                if dataset is not None:
                    with self._quiet_mlflow():
                        self._mlflow.log_input(dataset, context=str(record.metadata.get("context", event.step_name or "training")))
            except Exception:
                continue

    def _log_model_from_artifacts(self, event: PipelineEvent) -> None:
        assert self._mlflow is not None
        model_path = event.artifacts.get("model_bundle") or event.artifacts.get("model")
        if not model_path or not Path(model_path).exists():
            return
        try:
            import joblib
            import mlflow.sklearn
        except Exception:
            return
        try:
            bundle = joblib.load(model_path)
            model = bundle.get("model") if isinstance(bundle, dict) else bundle
            if model is None:
                return
            with self._quiet_mlflow():
                try:
                    mlflow.sklearn.log_model(
                        sk_model=model,
                        name="model",
                        registered_model_name=str(event.metadata.get("registered_model_name") or self.settings.project.name),
                    )
                except TypeError:
                    mlflow.sklearn.log_model(
                        sk_model=model,
                        artifact_path="model",
                        registered_model_name=str(event.metadata.get("registered_model_name") or self.settings.project.name),
                    )
        except Exception:
            return

    @contextmanager
    def _nested_run(self, *, run_name: str) -> Iterator[None]:
        assert self._mlflow is not None
        parent_params = self._logged_params
        self._logged_params = {}
        with self._quiet_mlflow():
            run_context = self._start_run_quiet(run_name=run_name, nested=True)
        try:
            if hasattr(run_context, "__enter__") and hasattr(run_context, "__exit__"):
                with self._quiet_mlflow():
                    with run_context:
                        yield
            else:  # pragma: no cover
                try:
                    yield
                finally:
                    with self._quiet_mlflow():
                        self._mlflow.end_run(status="FINISHED")
        finally:
            self._logged_params = parent_params

    def _append_event(self, event: PipelineEvent) -> None:
        self._event_index += 1
        data = event.model_dump(mode="json")
        data["event_index"] = self._event_index
        self._events.append(data)

    def _log_settings_artifacts(self) -> None:
        self._log_json_file(self.settings.model_dump(mode="json"), artifact_path="configuration/flow_settings.json")
        for step in self.settings.steps:
            self._log_json_file(step.config, artifact_path=f"configuration/steps/{step.name}.json")

    def _log_text_artifact(self, event: PipelineEvent, *, subdir: str) -> None:
        if not event.text:
            return
        name = self._artifact_safe_name(event.step_name or f"{event.event_type}_{self._event_index}")
        text = f"# {name}\n\n{event.text}\n"
        self._log_text_file(text, artifact_path=f"{subdir}/{name}_{self._event_index}.md")

    def _log_metadata_artifact(self, event: PipelineEvent, *, subdir: str) -> None:
        data = event.model_dump(mode="json")
        name = self._artifact_safe_name(event.step_name or event.event_type)
        self._log_json_file(data, artifact_path=f"{subdir}/{name}_{self._event_index}.json")

    def _log_text_file(self, text: str, *, artifact_path: str) -> None:
        assert self._mlflow is not None
        if self._tmpdir is None:
            return
        tmp_root = Path(self._tmpdir.name)
        local_file = tmp_root / artifact_path
        local_file.parent.mkdir(parents=True, exist_ok=True)
        local_file.write_text(text, encoding="utf-8")
        with self._quiet_mlflow():
            self._mlflow.log_artifact(str(local_file), artifact_path=str(Path(artifact_path).parent))

    def _log_json_file(self, data: Any, *, artifact_path: str) -> None:
        text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        self._log_text_file(text, artifact_path=artifact_path)

    def _log_declared_artifacts(self, event: PipelineEvent) -> None:
        assert self._mlflow is not None
        for artifact_name, path in event.artifacts.items():
            artifact_path = Path(path)
            if artifact_path.exists() and artifact_path.is_file():
                with self._quiet_mlflow():
                    self._mlflow.log_artifact(
                        str(artifact_path),
                        artifact_path=f"user_artifacts/{event.step_name}/{self._artifact_safe_name(artifact_name)}",
                    )

    def _log_record_artifacts(self, event: PipelineEvent, record: MetricRecord) -> None:
        assert self._mlflow is not None
        for artifact_name, path in record.artifacts.items():
            artifact_path = Path(path)
            if artifact_path.exists() and artifact_path.is_file():
                with self._quiet_mlflow():
                    self._mlflow.log_artifact(
                        str(artifact_path),
                        artifact_path=f"metric_records/{event.step_name}/{record.name}/{self._artifact_safe_name(artifact_name)}",
                    )

    def _log_metadata_tags(self, event: PipelineEvent, *, prefix: str) -> None:
        for key, value in event.metadata.items():
            if isinstance(value, (dict, list, tuple, set)):
                continue
            self._set_tag_safe(f"{prefix}.{key}", value)

    def _log_metric_safe(self, key: str, value: Any) -> None:
        assert self._mlflow is not None
        if not isinstance(value, (int, float, bool)):
            return
        with self._quiet_mlflow():
            self._mlflow.log_metric(self._safe_name(key), float(value))

    def _log_param_safe(self, key: str, value: Any) -> None:
        assert self._mlflow is not None
        safe_key = self._safe_name(key)
        safe_value = self._stringify(value, limit=500)
        previous = self._logged_params.get(safe_key)
        if previous is not None:
            if previous == safe_value:
                return
            safe_key = self._safe_name(f"{safe_key}__event_{self._event_index}")
        self._logged_params[safe_key] = safe_value
        with self._quiet_mlflow():
            self._mlflow.log_param(safe_key, safe_value)

    def _set_tag_safe(self, key: str, value: Any) -> None:
        assert self._mlflow is not None
        with self._quiet_mlflow():
            self._mlflow.set_tag(self._safe_name(key), self._stringify(value, limit=5000))

    @staticmethod
    def _stringify(value: Any, *, limit: int) -> str:
        if isinstance(value, (dict, list, tuple, set)):
            text = json.dumps(value, ensure_ascii=False, default=str)
        else:
            text = str(value)
        return text if len(text) <= limit else text[: limit - 3] + "..."

    @staticmethod
    def _artifact_safe_name(value: str) -> str:
        cleaned = str(value).replace("/", "_").replace("\\", "_").replace(":", "_")
        return "".join(char for char in cleaned if char.isalnum() or char in {"_", "-", "."})[:120]

    @contextmanager
    def _quiet_mlflow(self) -> Iterator[None]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            yield

    def close(self, status: str) -> None:
        if self._mlflow is not None and self._run_active:
            mlflow_status = "FINISHED" if status == "success" else "FAILED"
            try:
                self._log_json_file(self._events, artifact_path="events/events.json")
            except Exception:
                pass
            with self._quiet_mlflow():
                self._mlflow.end_run(status=mlflow_status)
            self._run_active = False
        if self._tmpdir is not None:
            self._tmpdir.cleanup()
            self._tmpdir = None

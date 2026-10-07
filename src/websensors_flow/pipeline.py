"""All-or-nothing object-agnostic pipeline engine."""

from __future__ import annotations

import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from websensors_flow.config import FlowSettings
from websensors_flow.context import PipelineContext
from websensors_flow.events import PipelineEvent
from websensors_flow.exceptions import ObserverError, PipelineExecutionError, PreflightCheckError
from websensors_flow.logger import PipelineLogger
from websensors_flow.observers import ConsoleObserver, GraylogObserver, MLflowObserver, PipelineObserver, ReportObserver
from websensors_flow.report import ExecutionReport, PipelineRunResult, StepExecutionRecord
from websensors_flow.result import StepFailure
from websensors_flow.step import PipelineStep


def _type_name(value: Any) -> str:
    """Return a safe type name for reports and logs."""

    return type(value).__name__


def _enabled_text(value: bool) -> str:
    """Return a terminal-friendly enabled flag."""

    return "enabled" if value else "disabled"


class WebSensorsPipeline:
    """Object-agnostic, all-or-nothing pipeline runner."""

    def __init__(
        self,
        *,
        settings: FlowSettings,
        observers: list[PipelineObserver],
        run_id: str | None = None,
    ):
        self.settings = settings
        self.pipeline_name = settings.project.name
        self.run_id = run_id or uuid.uuid4().hex
        self.steps: list[PipelineStep] = []
        self.observers = observers
        self.report = ExecutionReport(
            pipeline_name=self.pipeline_name,
            run_id=self.run_id,
            environment=settings.environment.name,
            project_version=settings.project.version,
        )
        self.logger = PipelineLogger(
            pipeline_name=self.pipeline_name,
            run_id=self.run_id,
            environment=settings.environment.name,
            emit=self._notify_user_log,
        )
        self.context = PipelineContext(
            settings=settings,
            run_id=self.run_id,
            pipeline_name=self.pipeline_name,
            logger=self.logger,
            emit=self._notify,
        )

    def add(self, step: PipelineStep) -> "WebSensorsPipeline":
        """Append a step to the pipeline."""

        if not isinstance(step, PipelineStep):
            raise TypeError("Pipeline steps must extend PipelineStep.")
        self.steps.append(step)
        return self

    def run(self, input: Any = None) -> PipelineRunResult:
        """Run the pipeline and return a structured result."""

        if not self.steps:
            raise PipelineExecutionError("Cannot run a pipeline without steps.")

        current_input = input
        has_output = False
        pipeline_start = perf_counter()
        status = "failed"

        try:
            self._preflight_check()
            self._notify(
                PipelineEvent(
                    event_type="pipeline_started",
                    pipeline_name=self.pipeline_name,
                    run_id=self.run_id,
                    environment=self.settings.environment.name,
                    status="running",
                    metadata={
                        "project_version": self.settings.project.version,
                        "steps_total": len(self.steps),
                        "trace_id": self.context.trace_id,
                    },
                )
            )

            for index, step in enumerate(self.steps, start=1):
                current_input, has_output = self._run_step(
                    step=step,
                    index=index,
                    current_input=current_input,
                    has_current_output=has_output,
                )

            self.report.complete("success")
            status = "success"
            self._notify(
                PipelineEvent(
                    event_type="pipeline_completed",
                    pipeline_name=self.pipeline_name,
                    run_id=self.run_id,
                    environment=self.settings.environment.name,
                    status="success",
                    duration_seconds=perf_counter() - pipeline_start,
                    metrics=self.report.metrics,
                )
            )
            return PipelineRunResult(output=current_input, has_output=has_output, report=self.report)

        except PreflightCheckError as exc:
            failure = self._preflight_failure(exc, pipeline_start)
            if self.settings.runtime.raise_on_failure:
                raise PreflightCheckError(failure.text) from exc
            return PipelineRunResult(output=current_input, has_output=has_output, report=self.report, failure=failure)

        except ObserverError as exc:
            failure = self._observer_failure(exc, pipeline_start)
            if self.settings.runtime.raise_on_failure:
                raise PipelineExecutionError(failure.text, failure=failure) from exc
            return PipelineRunResult(output=current_input, has_output=has_output, report=self.report, failure=failure)

        except PipelineExecutionError as exc:
            if self.settings.runtime.raise_on_failure:
                raise
            return PipelineRunResult(output=current_input, has_output=has_output, report=self.report, failure=exc.failure)

        except Exception as exc:
            failure = self._pipeline_level_failure(exc, pipeline_start)
            if self.settings.runtime.raise_on_failure:
                raise PipelineExecutionError(str(exc), failure=failure) from exc
            return PipelineRunResult(output=current_input, has_output=has_output, report=self.report, failure=failure)

        finally:
            self.context.clear_current_step()
            self._close_observers(status)

    def _preflight_check(self) -> None:
        """Validate configuration, check observers, and write probe events."""

        if not self.observers:
            raise PreflightCheckError("Preflight failed because no observer was configured.")

        self._notify_console_only(
            PipelineEvent(
                event_type="preflight_configuration",
                pipeline_name=self.pipeline_name,
                run_id=self.run_id,
                environment=self.settings.environment.name,
                status="running",
                metadata=self._configuration_summary(),
            )
        )

        for observer in self.observers:
            started = perf_counter()
            self._notify_preflight_status(
                observer.name,
                phase="validate_ready",
                status="running",
                action="Checking observer configuration.",
                target=self._observer_target(observer),
            )
            try:
                observer.validate_ready()
                self._notify_preflight_status(
                    observer.name,
                    phase="validate_ready",
                    status="ok",
                    action="Observer configuration is ready.",
                    target=self._observer_target(observer),
                    duration_seconds=perf_counter() - started,
                )
            except PreflightCheckError as exc:
                self._notify_preflight_status(
                    observer.name,
                    phase="validate_ready",
                    status="failed",
                    action="Observer configuration failed.",
                    target=self._observer_target(observer),
                    duration_seconds=perf_counter() - started,
                    error=str(exc),
                )
                raise
            except ObserverError as exc:
                self._notify_preflight_status(
                    observer.name,
                    phase="validate_ready",
                    status="failed",
                    action="Observer configuration failed.",
                    target=self._observer_target(observer),
                    duration_seconds=perf_counter() - started,
                    error=str(exc),
                )
                raise PreflightCheckError(f"Preflight failed in observer '{observer.name}': {exc}") from exc
            except Exception as exc:
                self._notify_preflight_status(
                    observer.name,
                    phase="validate_ready",
                    status="failed",
                    action="Observer configuration failed.",
                    target=self._observer_target(observer),
                    duration_seconds=perf_counter() - started,
                    error=str(exc),
                )
                raise PreflightCheckError(f"Preflight failed in observer '{observer.name}': {exc}") from exc

        probe_event = PipelineEvent(
            event_type="preflight_probe",
            pipeline_name=self.pipeline_name,
            run_id=self.run_id,
            environment=self.settings.environment.name,
            status="running",
            text="WebSensors Flow preflight probe.",
            metrics={"preflight_probe": 1},
            params={
                "project.name": self.settings.project.name,
                "project.version": self.settings.project.version,
                "environment.name": self.settings.environment.name,
            },
            metadata={
                "steps_total": len(self.steps),
                "observer_probe": True,
            },
        )
        for observer in self.observers:
            started = perf_counter()
            self._notify_preflight_status(
                observer.name,
                phase="probe",
                status="running",
                action="Sending preflight probe.",
                target=self._observer_target(observer),
            )
            try:
                observer.preflight_probe(probe_event)
                self._notify_preflight_status(
                    observer.name,
                    phase="probe",
                    status="ok",
                    action="Preflight probe was accepted.",
                    target=self._observer_target(observer),
                    duration_seconds=perf_counter() - started,
                )
            except PreflightCheckError as exc:
                self._notify_preflight_status(
                    observer.name,
                    phase="probe",
                    status="failed",
                    action="Preflight probe failed.",
                    target=self._observer_target(observer),
                    duration_seconds=perf_counter() - started,
                    error=str(exc),
                )
                raise
            except ObserverError as exc:
                self._notify_preflight_status(
                    observer.name,
                    phase="probe",
                    status="failed",
                    action="Preflight probe failed.",
                    target=self._observer_target(observer),
                    duration_seconds=perf_counter() - started,
                    error=str(exc),
                )
                raise PreflightCheckError(f"Preflight probe failed in observer '{observer.name}': {exc}") from exc
            except Exception as exc:
                self._notify_preflight_status(
                    observer.name,
                    phase="probe",
                    status="failed",
                    action="Preflight probe failed.",
                    target=self._observer_target(observer),
                    duration_seconds=perf_counter() - started,
                    error=str(exc),
                )
                raise PreflightCheckError(f"Preflight probe failed in observer '{observer.name}': {exc}") from exc

    def _configuration_summary(self) -> dict[str, Any]:
        mlflow = self.settings.observability.mlflow
        graylog = self.settings.observability.graylog
        api = self.settings.api
        runtime = self.settings.runtime
        environment = self.settings.environment

        return {
            "config_file": self.settings.source_path or "-",
            "run_id": self.run_id,
            "project": self.settings.project.name,
            "project_version": self.settings.project.version,
            "environment": environment.name,
            "deployment_id": environment.deployment_id or "-",
            "owner": environment.owner or "-",
            "report_dir": runtime.report_dir,
            "raise_on_failure": runtime.raise_on_failure,
            "include_traceback": runtime.include_traceback,
            "console": _enabled_text(runtime.console.enabled),
            "api": _enabled_text(api.enabled),
            "api_endpoint": api.endpoint,
            "api_host": api.host,
            "api_port": api.port,
            "graylog": _enabled_text(graylog.enabled),
            "graylog_host": graylog.host or "-",
            "graylog_port": graylog.port or "-",
            "graylog_protocol": graylog.protocol,
            "graylog_facility": graylog.facility,
            "graylog_timeout": f"{graylog.connect_timeout_seconds}s",
            "graylog_auth": self._auth_summary(graylog.auth.enabled, graylog.auth.username, graylog.auth.password, graylog.auth.token),
            "mlflow": _enabled_text(mlflow.enabled),
            "mlflow_tracking_uri": mlflow.tracking_uri or "-",
            "mlflow_experiment": mlflow.experiment_name or "-",
            "mlflow_run_name": mlflow.run_name or "-",
            "mlflow_timeout": f"{mlflow.connect_timeout_seconds}s connect, {mlflow.http_request_timeout}s HTTP",
            "mlflow_auth": self._auth_summary(mlflow.auth.enabled, mlflow.auth.username, mlflow.auth.password, mlflow.auth.token),
            "pipeline_params": dict(self.settings.pipeline.params),
            "steps": [
                {
                    "index": index,
                    "name": definition.name,
                    "class_path": definition.class_path or "-",
                    "enabled": definition.enabled,
                    "config_keys": sorted(definition.config.keys()),
                }
                for index, definition in enumerate(self.settings.steps, start=1)
            ],
            "observers": [observer.name for observer in self.observers],
        }

    @staticmethod
    def _auth_summary(enabled: bool, username: str | None, password: str | None, token: str | None) -> str:
        if not enabled:
            return "disabled"
        values: list[str] = []
        if username:
            values.append("username")
        if password:
            values.append("password")
        if token:
            values.append("token")
        return "provided: " + ", ".join(values) if values else "enabled without resolved credential"

    def _notify_preflight_status(
        self,
        observer_name: str,
        *,
        phase: str,
        status: str,
        action: str,
        target: str | None = None,
        duration_seconds: float | None = None,
        error: str | None = None,
    ) -> None:
        self._notify_console_only(
            PipelineEvent(
                event_type="preflight_observer_status",
                pipeline_name=self.pipeline_name,
                run_id=self.run_id,
                environment=self.settings.environment.name,
                level="ERROR" if status == "failed" else "INFO",
                status=status,
                text=f"{observer_name} {phase} {status}.",
                metadata={
                    "observer": observer_name,
                    "phase": phase,
                    "action": action,
                    "target": target or "",
                    "duration_seconds": duration_seconds,
                    "error": error or "",
                },
            )
        )

    def _observer_target(self, observer: PipelineObserver) -> str:
        config = getattr(observer, "config", None)
        if observer.name == "graylog" and config is not None:
            return f"{getattr(config, 'host', '-')}:{getattr(config, 'port', '-')}"
        if observer.name == "mlflow" and config is not None:
            return str(getattr(config, "tracking_uri", "-"))
        if observer.name == "console":
            return "terminal"
        if observer.name == "report":
            return self.settings.runtime.report_dir
        return ""

    def _run_step(
        self,
        *,
        step: PipelineStep,
        index: int,
        current_input: Any,
        has_current_output: bool,
    ) -> tuple[Any, bool]:
        self.context.set_current_step(step.step_name, index)
        started_at = datetime.now(timezone.utc)
        step_start = perf_counter()
        input_type = _type_name(current_input)

        self._notify(
            PipelineEvent(
                event_type="step_started",
                pipeline_name=self.pipeline_name,
                run_id=self.run_id,
                environment=self.settings.environment.name,
                step_name=step.step_name,
                step_index=index,
                status="running",
                metadata={"input_type": input_type, "has_current_output": has_current_output, **step.describe()},
            )
        )

        try:
            with self.context.trace(f"step:{step.step_name}", metadata={"step_index": index}):
                step.setup(self.context)
                result = step.run(current_input, self.context)
                step.teardown(self.context)
            self._register_models_from_result(result)
            finished_at = datetime.now(timezone.utc)
            duration_seconds = perf_counter() - step_start
            output_type = _type_name(result.output) if result.has_output else None

            record = StepExecutionRecord(
                step_name=step.step_name,
                step_index=index,
                status="success",
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration_seconds,
                text=result.text,
                metrics=result.metrics,
                params=result.params,
                metadata=result.metadata,
                artifacts=result.artifacts,
                warnings=result.warnings,
                metric_records=result.metric_records,
                input_type=input_type,
                output_type=output_type,
                has_output=result.has_output,
            )
            self.report.steps.append(record)

            event_metrics = dict(result.metrics)
            event_metrics.update(
                {
                    "duration_seconds": duration_seconds,
                    "warnings_count": len(result.warnings),
                    "has_output": int(result.has_output),
                }
            )
            self._notify(
                PipelineEvent(
                    event_type="step_completed",
                    pipeline_name=self.pipeline_name,
                    run_id=self.run_id,
                    environment=self.settings.environment.name,
                    step_name=step.step_name,
                    step_index=index,
                    status="success",
                    duration_seconds=duration_seconds,
                    text=result.text,
                    metrics=event_metrics,
                    params=result.params,
                    metadata={**result.metadata, "input_type": input_type, "output_type": output_type},
                    artifacts=result.artifacts,
                    warnings=result.warnings,
                    metric_records=result.metric_records,
                )
            )
            if result.has_output:
                return result.output, True
            return current_input, has_current_output

        except Exception as exc:
            try:
                step.teardown(self.context)
            except Exception:
                pass
            failure = self._step_failure(step, index, started_at, step_start, input_type, exc)
            self._notify_step_and_pipeline_failure(failure)
            raise PipelineExecutionError(failure.text, failure=failure) from exc


    def _register_models_from_result(self, result: Any) -> None:
        """Best-effort automatic registration of model identifiers returned by a step."""

        candidate_keys = {
            "model", "model_name", "model_id", "llm_model", "embedding_model",
            "reranker_model", "teacher_model", "student_model", "estimator", "algorithm",
        }
        seen: set[str] = set()
        mappings = [getattr(result, "params", {}) or {}, getattr(result, "metadata", {}) or {}]
        for record in getattr(result, "metric_records", []) or []:
            mappings.append(getattr(record, "params", {}) or {})
        for mapping in mappings:
            provider = mapping.get("provider") or mapping.get("model_provider")
            role = mapping.get("role") or mapping.get("model_role")
            endpoint = mapping.get("endpoint") or mapping.get("base_url")
            for key, value in mapping.items():
                if key not in candidate_keys or value in (None, ""):
                    continue
                name = str(value)
                signature = f"{name}|{provider}|{role}|{endpoint}"
                if signature in seen:
                    continue
                seen.add(signature)
                self.context.register_model(name, provider=str(provider) if provider else None, role=str(role) if role else None, endpoint=str(endpoint) if endpoint else None, metadata={"detected_from": key})

    def _step_failure(
        self,
        step: PipelineStep,
        index: int,
        started_at: datetime,
        step_start: float,
        input_type: str,
        exc: Exception,
    ) -> StepFailure:
        duration_seconds = perf_counter() - step_start
        traceback_text = traceback.format_exc()
        text = f"Step '{step.step_name}' failed with {type(exc).__name__}: {exc}"
        failure = StepFailure(
            step_name=step.step_name,
            step_index=index,
            text=text,
            error_type=type(exc).__name__,
            error_message=str(exc),
            traceback_text=traceback_text,
            duration_seconds=duration_seconds,
            input_type=input_type,
            metrics={"success": 0, "failed": 1, "duration_seconds": duration_seconds},
            metadata={"error_origin": "user_step", "input_type": input_type},
        )
        self.report.steps.append(
            StepExecutionRecord(
                step_name=step.step_name,
                step_index=index,
                status="failed",
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                duration_seconds=duration_seconds,
                text=text,
                metrics=failure.metrics,
                metadata=failure.metadata,
                input_type=input_type,
                error_type=failure.error_type,
                error_message=failure.error_message,
                traceback_text=failure.traceback_text if self.settings.runtime.include_traceback else None,
            )
        )
        self.report.complete("failed")
        return failure

    def _notify_step_and_pipeline_failure(self, failure: StepFailure) -> None:
        self._notify(
            PipelineEvent(
                event_type="step_failed",
                pipeline_name=self.pipeline_name,
                run_id=self.run_id,
                environment=self.settings.environment.name,
                step_name=failure.step_name,
                step_index=failure.step_index,
                status="failed",
                duration_seconds=failure.duration_seconds,
                text=failure.text,
                metrics=failure.metrics,
                metadata=failure.metadata,
                error_type=failure.error_type,
                error_message=failure.error_message,
                traceback_text=failure.traceback_text if self.settings.runtime.include_traceback else None,
            )
        )
        self._notify(
            PipelineEvent(
                event_type="pipeline_failed",
                pipeline_name=self.pipeline_name,
                run_id=self.run_id,
                environment=self.settings.environment.name,
                status="failed",
                duration_seconds=self.report.duration_seconds,
                metrics=self.report.metrics,
                error_type=failure.error_type,
                error_message=failure.error_message,
                traceback_text=failure.traceback_text if self.settings.runtime.include_traceback else None,
            )
        )

    def _preflight_failure(self, exc: Exception, pipeline_start: float) -> StepFailure:
        failure = StepFailure(
            step_name="preflight",
            step_index=0,
            text=f"Preflight failed before executing user steps: {exc}",
            error_type=type(exc).__name__,
            error_message=str(exc),
            traceback_text=traceback.format_exc(),
            duration_seconds=perf_counter() - pipeline_start,
            input_type=None,
            metrics={"success": 0, "failed": 1},
            metadata={"error_origin": "preflight"},
        )
        self.report.steps.append(
            StepExecutionRecord(
                step_name="preflight",
                step_index=0,
                status="failed",
                started_at=self.report.started_at,
                finished_at=datetime.now(timezone.utc),
                duration_seconds=failure.duration_seconds,
                text=failure.text,
                metrics=failure.metrics,
                metadata=failure.metadata,
                error_type=failure.error_type,
                error_message=failure.error_message,
                traceback_text=failure.traceback_text if self.settings.runtime.include_traceback else None,
            )
        )
        self.report.complete("failed")
        self._notify_console_only(
            PipelineEvent(
                event_type="preflight_failed",
                pipeline_name=self.pipeline_name,
                run_id=self.run_id,
                environment=self.settings.environment.name,
                status="failed",
                duration_seconds=failure.duration_seconds,
                text=failure.text,
                metrics=self.report.metrics,
                error_type=failure.error_type,
                error_message=failure.error_message,
            )
        )
        self._write_report_files()
        return failure

    def _observer_failure(self, exc: Exception, pipeline_start: float) -> StepFailure:
        self.report.complete("failed")
        failure = StepFailure(
            step_name="observability",
            step_index=0,
            text=f"Observability failed during the run: {exc}",
            error_type=type(exc).__name__,
            error_message=str(exc),
            traceback_text=traceback.format_exc(),
            duration_seconds=perf_counter() - pipeline_start,
            metrics={"success": 0, "failed": 1},
            metadata={"error_origin": "observer"},
        )
        self._notify_console_only(
            PipelineEvent(
                event_type="pipeline_failed",
                pipeline_name=self.pipeline_name,
                run_id=self.run_id,
                environment=self.settings.environment.name,
                status="failed",
                duration_seconds=failure.duration_seconds,
                metrics=self.report.metrics,
                error_type=failure.error_type,
                error_message=failure.error_message,
            )
        )
        self._write_report_files()
        return failure

    def _pipeline_level_failure(self, exc: Exception, pipeline_start: float) -> StepFailure:
        self.report.complete("failed")
        failure = StepFailure(
            step_name="pipeline",
            step_index=0,
            text=f"Pipeline failed before or outside user steps with {type(exc).__name__}: {exc}",
            error_type=type(exc).__name__,
            error_message=str(exc),
            traceback_text=traceback.format_exc(),
            duration_seconds=perf_counter() - pipeline_start,
            metrics={"success": 0, "failed": 1},
            metadata={"error_origin": "pipeline"},
        )
        try:
            self._notify(
                PipelineEvent(
                    event_type="pipeline_failed",
                    pipeline_name=self.pipeline_name,
                    run_id=self.run_id,
                    environment=self.settings.environment.name,
                    status="failed",
                    duration_seconds=failure.duration_seconds,
                    metrics=self.report.metrics,
                    error_type=failure.error_type,
                    error_message=failure.error_message,
                    traceback_text=failure.traceback_text if self.settings.runtime.include_traceback else None,
                )
            )
        except Exception:
            self._notify_console_only(
                PipelineEvent(
                    event_type="pipeline_failed",
                    pipeline_name=self.pipeline_name,
                    run_id=self.run_id,
                    environment=self.settings.environment.name,
                    status="failed",
                    duration_seconds=failure.duration_seconds,
                    metrics=self.report.metrics,
                    error_type=failure.error_type,
                    error_message=failure.error_message,
                )
            )
        self._write_report_files()
        return failure

    def _notify_user_log(self, event: PipelineEvent) -> None:
        try:
            self._notify(event)
        except Exception:
            self._notify_console_only(event)

    def _notify(self, event: PipelineEvent) -> None:
        if event.trace_id is None:
            event.trace_id = self.context.trace_id
        for observer in self.observers:
            try:
                observer.on_event(event)
            except Exception as exc:
                if isinstance(exc, ObserverError):
                    raise
                raise ObserverError(f"Observer '{observer.name}' failed for event '{event.event_type}': {exc}") from exc

    def _notify_console_only(self, event: PipelineEvent) -> None:
        for observer in self.observers:
            if observer.name == "console":
                try:
                    observer.on_event(event)
                except Exception:
                    pass

    def _write_report_files(self) -> None:
        try:
            run_dir = Path(self.settings.runtime.report_dir) / self.report.run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "execution_report.json").write_text(self.report.model_dump_json(indent=2), encoding="utf-8")
            (run_dir / "execution_report.md").write_text(self.report.to_markdown(), encoding="utf-8")
        except Exception:
            pass

    def _close_observers(self, status: str) -> None:
        for observer in self.observers:
            try:
                observer.close(status)
            except Exception:
                pass


def build_pipeline_from_settings(
    settings: FlowSettings,
    *,
    include_console: bool = True,
    run_id: str | None = None,
    extra_observers: list[PipelineObserver] | None = None,
) -> WebSensorsPipeline:
    """Create a pipeline with local reports and active observers."""

    report = ExecutionReport(
        pipeline_name=settings.project.name,
        run_id=run_id or uuid.uuid4().hex,
        environment=settings.environment.name,
        project_version=settings.project.version,
    )
    observers: list[PipelineObserver] = []
    if include_console and settings.runtime.console.enabled:
        observers.append(
            ConsoleObserver(
                enabled=settings.runtime.console.enabled,
                progress=settings.runtime.console.progress,
                show_metrics=settings.runtime.console.show_metrics,
                report_dir=settings.runtime.report_dir,
            )
        )
    observers.append(ReportObserver(settings=settings, report=report))
    if settings.observability.graylog.enabled:
        observers.append(GraylogObserver(settings.observability.graylog))
    if settings.observability.mlflow.enabled:
        observers.append(MLflowObserver(settings.observability.mlflow, settings=settings))
    if extra_observers:
        observers.extend(extra_observers)

    pipeline = WebSensorsPipeline(settings=settings, observers=observers, run_id=report.run_id)
    pipeline.report = report
    return pipeline

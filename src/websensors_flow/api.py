"""FastAPI application factory for agent-friendly asynchronous flow execution."""

import re
import threading
import uuid
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

from websensors_flow.config import FlowSettings
from websensors_flow.events import PipelineEvent
from websensors_flow.observers.base import PipelineObserver
from websensors_flow.runner import run_configured_flow


_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
RunStatus = Literal["queued", "running", "success", "failed"]

_TYPE_MAP: dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict[str, Any],
    "array": list[Any],
}


class GenericRunRequest(BaseModel):
    input: Any = Field(
        default=None,
        description="Input consumed by the first step of the flow. Use null when the flow reads its own configured source.",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional runtime parameter overrides. Omit this field when no override is needed.",
    )


class NextAction(BaseModel):
    operation: str = Field(description="OpenAPI operationId of the recommended next tool call.")
    method: Literal["GET", "POST"]
    path: str = Field(description="Relative API path for the recommended next call.")
    description: str = Field(description="Short instruction explaining when and why to call the operation.")


class StartRunResponse(BaseModel):
    token: str = Field(description="Execution token. Preserve it for every follow-up call about this run.")
    run_id: str = Field(description="Run identifier. It is identical to token.")
    status: RunStatus
    terminal: bool = Field(description="True only when the run has completed or failed.")
    message: str = Field(description="Human- and LLM-readable summary of the current state.")
    status_url: str
    events_url: str
    next_action: NextAction | None = None


class FlowDescriptor(BaseModel):
    name: str
    description: str
    environment: str
    execution_mode: Literal["asynchronous"] = "asynchronous"
    steps: list[str]
    input_schema: dict[str, Any]
    result_description: str | None = None
    instructions: list[str]
    operations: dict[str, str]


class RunStatusResponse(BaseModel):
    token: str
    run_id: str
    status: RunStatus
    terminal: bool
    message: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    updated_at: str
    progress: dict[str, Any]
    trace_id: str | None = None
    models: list[dict[str, Any]] = Field(default_factory=list)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    next_action: NextAction | None = None


class RunEventsResponse(BaseModel):
    token: str
    status: RunStatus
    message: str
    count: int
    events: list[dict[str, Any]]
    next_action: NextAction | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    flow: str
    environment: str
    describe_endpoint: str
    run_endpoint: str
    openapi: str = "/openapi.json"


class JobStore:
    """Thread-safe in-memory execution registry used by the API process."""

    def __init__(self, *, event_history_limit: int = 1000) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}
        self.event_history_limit = max(10, int(event_history_limit))
        self._lock = threading.RLock()

    def create(self, token: str, payload: dict[str, Any], *, steps_total: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            if token in self.jobs:
                raise ValueError("Execution token already exists.")
            self.jobs[token] = {
                "token": token,
                "run_id": token,
                "status": "queued",
                "created_at": now,
                "started_at": None,
                "finished_at": None,
                "updated_at": now,
                "payload": payload,
                "pipeline": {
                    "steps_total": steps_total,
                    "steps_completed": 0,
                    "percent": 0.0,
                    "current_step": None,
                    "current_step_index": None,
                    "elapsed_seconds": 0.0,
                    "eta_seconds": None,
                },
                "progress": None,
                "trace_id": None,
                "models": [],
                "report": None,
                "failure": None,
                "output": None,
                "events": [],
            }

    def update(self, token: str, **values: Any) -> None:
        with self._lock:
            if token in self.jobs:
                self.jobs[token].update(values)
                self.jobs[token]["updated_at"] = datetime.now(timezone.utc).isoformat()

    def append_event(self, token: str, event: PipelineEvent) -> None:
        with self._lock:
            job = self.jobs.get(token)
            if job is None:
                return
            event_data = event.model_dump(mode="json", exclude_none=True)
            job["events"].append(event_data)
            if len(job["events"]) > self.event_history_limit:
                del job["events"][:-self.event_history_limit]
            job["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._apply_event(job, event)

    def _apply_event(self, job: dict[str, Any], event: PipelineEvent) -> None:
        pipeline = job["pipeline"]
        if event.trace_id:
            job["trace_id"] = event.trace_id
        if event.event_type == "pipeline_started":
            job["status"] = "running"
            job["started_at"] = event.timestamp.isoformat()
            pipeline["steps_total"] = int(event.metadata.get("steps_total", pipeline["steps_total"]) or 0)
        elif event.event_type == "step_started":
            pipeline["current_step"] = event.step_name
            pipeline["current_step_index"] = event.step_index
            job["progress"] = None
        elif event.event_type == "step_completed":
            pipeline["steps_completed"] = max(pipeline["steps_completed"], int(event.step_index or 0))
            total = max(int(pipeline["steps_total"] or 0), 1)
            pipeline["percent"] = round((pipeline["steps_completed"] / total) * 100.0, 2)
            completed_durations = [
                float(e.get("duration_seconds") or 0)
                for e in job["events"]
                if e.get("event_type") == "step_completed"
            ]
            pipeline["elapsed_seconds"] = round(sum(completed_durations), 3)
            remaining_steps = max(int(pipeline["steps_total"] or 0) - pipeline["steps_completed"], 0)
            average_step = (sum(completed_durations) / len(completed_durations)) if completed_durations else 0.0
            pipeline["eta_seconds"] = round(average_step * remaining_steps, 3) if remaining_steps else 0.0
            job["progress"] = None
        elif event.event_type == "progress":
            job["progress"] = dict(event.metadata)
            total_steps = max(int(pipeline["steps_total"] or 0), 1)
            step_index = int(event.step_index or pipeline.get("current_step_index") or 1)
            loop_percent = float(event.metadata.get("percent") or 0.0)
            completed_equivalent = max(step_index - 1, 0) + min(max(loop_percent, 0.0), 100.0) / 100.0
            pipeline["percent"] = round(min((completed_equivalent / total_steps) * 100.0, 100.0), 2)
            loop_eta = event.metadata.get("eta_seconds")
            if loop_eta is not None:
                completed_durations = [
                    float(e.get("duration_seconds") or 0)
                    for e in job["events"]
                    if e.get("event_type") == "step_completed"
                ]
                average_step = (sum(completed_durations) / len(completed_durations)) if completed_durations else 0.0
                steps_after_current = max(total_steps - step_index, 0)
                pipeline["eta_seconds"] = round(float(loop_eta) + average_step * steps_after_current, 3)
        elif event.event_type == "model_registered":
            model = {**event.params, **event.metadata}
            if model not in job["models"]:
                job["models"].append(model)
        elif event.event_type == "pipeline_completed":
            job["status"] = "success"
            job["finished_at"] = event.timestamp.isoformat()
            pipeline["percent"] = 100.0
            pipeline["current_step"] = None
            pipeline["current_step_index"] = None
            pipeline["elapsed_seconds"] = round(float(event.duration_seconds or pipeline["elapsed_seconds"]), 3)
            pipeline["eta_seconds"] = 0.0
            job["progress"] = None
        elif event.event_type in {"pipeline_failed", "preflight_failed"}:
            job["status"] = "failed"
            job["finished_at"] = event.timestamp.isoformat()
            pipeline["eta_seconds"] = None
            job["progress"] = None

    def get(self, token: str, *, include_events: bool = False) -> dict[str, Any] | None:
        with self._lock:
            job = self.jobs.get(token)
            if job is None:
                return None
            result = dict(job)
            result["pipeline"] = dict(job["pipeline"])
            result["models"] = list(job["models"])
            if include_events:
                result["events"] = list(job["events"])
            else:
                result.pop("events", None)
            return result

    def events(self, token: str) -> list[dict[str, Any]] | None:
        with self._lock:
            job = self.jobs.get(token)
            return None if job is None else list(job["events"])


class JobStatusObserver(PipelineObserver):
    """Observer that projects live pipeline events into the API JobStore."""

    name = "api_status"

    def __init__(self, store: JobStore, token: str) -> None:
        self.store = store
        self.token = token

    def on_event(self, event: PipelineEvent) -> None:
        self.store.append_event(self.token, event)


def _request_model_from_settings(settings: FlowSettings) -> type[BaseModel]:
    if not settings.api.input_fields:
        return GenericRunRequest
    fields: dict[str, tuple[Any, Any]] = {}
    for name, field_config in settings.api.input_fields.items():
        python_type = _TYPE_MAP[field_config.type]
        default = ... if field_config.required and field_config.default is None else field_config.default
        description = field_config.description or f"Input field '{name}' consumed by this flow."
        field_kwargs: dict[str, Any] = {"description": description}
        if field_config.examples:
            field_kwargs["examples"] = field_config.examples
        fields[name] = (python_type, Field(default=default, **field_kwargs))
    fields["params"] = (
        dict[str, Any],
        Field(default_factory=dict, description="Optional runtime parameter overrides. Omit when no override is needed."),
    )
    model = create_model("FlowRunRequest", __module__=__name__, **fields)
    model.model_rebuild(force=True)
    return model


def _safe_output(output: Any) -> Any:
    if output is None or isinstance(output, (str, int, float, bool)):
        return output
    if isinstance(output, list):
        return [_safe_output(value) for value in output]
    if isinstance(output, dict):
        return {str(key): _safe_output(value) for key, value in output.items()}
    return repr(output)


def _status_message(job: dict[str, Any]) -> str:
    status = job["status"]
    pipeline = job["pipeline"]
    if status == "queued":
        return "The flow was accepted and is waiting for an execution worker."
    if status == "running":
        step = pipeline.get("current_step")
        percent = float(pipeline.get("percent") or 0.0)
        if step:
            return f"The flow is running step '{step}' and is approximately {percent:.1f}% complete."
        return f"The flow is running and is approximately {percent:.1f}% complete."
    if status == "success":
        return "The flow completed successfully. The final result is available in result."
    failure = job.get("failure") or {}
    error_message = failure.get("error_message") or "No additional error message was recorded."
    return f"The flow failed. Error: {error_message}"


def _next_action(token: str, status: str) -> NextAction | None:
    if status in {"queued", "running"}:
        return NextAction(
            operation="get_flow_run_status",
            method="GET",
            path=f"/runs/{token}",
            description="Call this operation again with the same token until terminal is true.",
        )
    return None


def _project_status(job: dict[str, Any]) -> dict[str, Any]:
    pipeline = job["pipeline"]
    status = job["status"]
    progress = {
        "percent": pipeline.get("percent", 0.0),
        "steps_completed": pipeline.get("steps_completed", 0),
        "steps_total": pipeline.get("steps_total", 0),
        "current_step": pipeline.get("current_step"),
        "current_step_index": pipeline.get("current_step_index"),
        "elapsed_seconds": pipeline.get("elapsed_seconds", 0.0),
        "eta_seconds": pipeline.get("eta_seconds"),
        "loop": job.get("progress"),
    }
    result = None
    if status == "success":
        result = {
            "output": job.get("output"),
            "report": job.get("report"),
        }
    return {
        "token": job["token"],
        "run_id": job["run_id"],
        "status": status,
        "terminal": status in {"success", "failed"},
        "message": _status_message(job),
        "created_at": job["created_at"],
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "updated_at": job["updated_at"],
        "progress": progress,
        "trace_id": job.get("trace_id"),
        "models": job.get("models", []),
        "result": result,
        "error": job.get("failure") if status == "failed" else None,
        "next_action": _next_action(job["token"], status),
    }


def _event_message(event: dict[str, Any]) -> str:
    event_type = event.get("event_type", "event")
    step = event.get("step_name")
    if event_type == "pipeline_started":
        return "Flow execution started."
    if event_type == "pipeline_completed":
        return "Flow execution completed successfully."
    if event_type in {"pipeline_failed", "preflight_failed"}:
        return "Flow execution failed."
    if event_type == "step_started" and step:
        return f"Step '{step}' started."
    if event_type == "step_completed" and step:
        return f"Step '{step}' completed."
    if event_type == "progress" and step:
        percent = (event.get("metadata") or {}).get("percent")
        return f"Step '{step}' reported {percent}% progress." if percent is not None else f"Step '{step}' reported progress."
    if event_type == "model_registered":
        model = (event.get("params") or {}).get("name", "a model")
        return f"The flow registered model '{model}'."
    return event.get("text") or f"Flow event: {event_type}."


def create_app(settings: FlowSettings):
    """Create an OpenAPI service designed for programmatic and LLM tool use."""

    try:
        from fastapi import Body, FastAPI, Header, HTTPException, Query
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("FastAPI is required for API mode. Install websensors-flow with the 'api' extra.") from exc

    executor = ThreadPoolExecutor(max_workers=settings.api.workers)
    store = JobStore(event_history_limit=settings.api.event_history_limit)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        executor.shutdown(wait=True, cancel_futures=False)

    flow_description = settings.api.description or settings.project.description or f"Execute the {settings.project.name} flow."
    app = FastAPI(
        title=settings.api.title,
        description=(
            f"{flow_description}\n\n"
            "This API is asynchronous. Start a flow, preserve the returned token, and use the status operation "
            "until `terminal` is true. The OpenAPI operation IDs are stable and intended for tool-calling clients."
        ),
        version=settings.api.version or settings.project.version,
        lifespan=lifespan,
        openapi_tags=[
            {"name": "flow", "description": "Discover what the configured flow does and what input it expects."},
            {"name": "execution", "description": "Start a flow and monitor its asynchronous execution."},
            {"name": "diagnostics", "description": "Inspect recent execution events when additional detail is needed."},
            {"name": "service", "description": "Service health information."},
        ],
    )
    RequestModel = _request_model_from_settings(settings)
    steps_total = len([step for step in settings.steps if step.enabled])
    app.state.job_store = store
    app.state.executor = executor

    def execute_job(token: str, input_payload: Any, params: dict[str, Any]) -> None:
        store.update(token, status="running", started_at=datetime.now(timezone.utc).isoformat())
        observer = JobStatusObserver(store, token)
        try:
            result = run_configured_flow(
                settings,
                input=input_payload,
                params=params,
                run_id=token,
                extra_observers=[observer],
            )
            update: dict[str, Any] = {
                "status": result.report.status,
                "report": result.report.model_dump(mode="json"),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }
            if result.failure is not None:
                update["failure"] = result.failure.model_dump(mode="json")
            if settings.api.return_output:
                update["output"] = _safe_output(result.output)
            store.update(token, **update)
        except Exception as exc:
            store.update(
                token,
                status="failed",
                finished_at=datetime.now(timezone.utc).isoformat(),
                failure={
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "suggestion": "Inspect get_flow_run_events for the latest execution events and trace_id for correlated logs.",
                },
            )

    @app.get(
        "/health",
        tags=["service"],
        operation_id="check_flow_service_health",
        summary="Check flow service health",
        description="Use this operation only to verify that the flow service is reachable.",
        response_model=HealthResponse,
        include_in_schema=False,
    )
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "flow": settings.project.name,
            "environment": settings.environment.name,
            "describe_endpoint": "/flow",
            "run_endpoint": settings.api.endpoint,
            "openapi": "/openapi.json",
        }

    @app.get(
        "/flow",
        tags=["flow"],
        operation_id="describe_flow",
        summary="Describe the available flow",
        description=(
            "Return the purpose, expected input schema, ordered step names, and calling instructions for this flow. "
            "Call this when the tool client needs to understand the flow before starting it."
        ),
        response_model=FlowDescriptor,
    )
    def describe_flow() -> dict[str, Any]:
        return {
            "name": settings.project.name,
            "description": flow_description,
            "environment": settings.environment.name,
            "execution_mode": "asynchronous",
            "steps": [step.name for step in settings.steps if step.enabled],
            "input_schema": RequestModel.model_json_schema(),
            "result_description": settings.api.result_description,
            "instructions": [
                *settings.api.instructions,
                "Call start_flow_run with the flow input.",
                "Preserve the returned token exactly.",
                "Call get_flow_run_status with that token until terminal is true.",
                "Call get_flow_run_events only when more execution detail is useful.",
            ],
            "operations": {
                "start": "start_flow_run",
                "status": "get_flow_run_status",
                "events": "get_flow_run_events",
            },
        }

    @app.post(
        settings.api.endpoint,
        status_code=202,
        tags=["execution"],
        operation_id="start_flow_run",
        summary=f"Start {settings.project.name}",
        description=(
            f"Start the asynchronous flow '{settings.project.name}'. {flow_description} "
            "The response returns a token immediately. Preserve that token and call get_flow_run_status until terminal is true. "
            "Do not invent a token unless the caller explicitly needs a stable client-supplied identifier."
        ),
        response_model=StartRunResponse,
    )
    def start_run(
        request: RequestModel = Body(..., description="Validated input for the configured flow."),
        x_run_token: str | None = Header(
            default=None,
            alias="X-Run-Token",
            description="Optional caller-defined execution token. Usually omit this header and use the generated token returned by the API.",
        ),
    ) -> dict[str, Any]:
        payload = request.model_dump()
        params = payload.pop("params", {}) or {}
        input_payload = payload.get("input") if set(payload.keys()) == {"input"} else payload
        token = (x_run_token or uuid.uuid4().hex).strip()
        if not _TOKEN_PATTERN.fullmatch(token):
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Invalid execution token.",
                    "constraint": "Use 1-128 characters: letters, numbers, dot, underscore, colon, or hyphen.",
                },
            )
        try:
            store.create(token, payload={"input": input_payload, "params": params}, steps_total=steps_total)
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "The requested execution token is already in use.",
                    "suggestion": "Use the existing token to inspect that run, or omit X-Run-Token to generate a new token.",
                },
            ) from exc
        executor.submit(execute_job, token, input_payload, params)
        return {
            "token": token,
            "run_id": token,
            "status": "queued",
            "terminal": False,
            "message": "The flow was accepted for asynchronous execution. Preserve the token and check its status.",
            "status_url": f"/runs/{token}",
            "events_url": f"/runs/{token}/events",
            "next_action": _next_action(token, "queued"),
        }

    @app.get(
        "/runs/{token}",
        tags=["execution"],
        operation_id="get_flow_run_status",
        summary="Get flow run status",
        description=(
            "Return a concise semantic status for one flow execution. Use the exact token returned by start_flow_run. "
            "When terminal is false, follow next_action and call this operation again later. When terminal is true, "
            "read result on success or error on failure."
        ),
        response_model=RunStatusResponse,
    )
    def get_run(token: str) -> dict[str, Any]:
        job = store.get(token)
        if job is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "message": "Execution token not found.",
                    "token": token,
                    "suggestion": "Use the exact token returned by start_flow_run.",
                },
            )
        return _project_status(job)

    @app.get(
        "/runs/{token}/events",
        tags=["diagnostics"],
        operation_id="get_flow_run_events",
        summary="Get recent flow run events",
        description=(
            "Return recent execution events for diagnostics or detailed reasoning about a run. "
            "Normally call get_flow_run_status first; use this operation when step-level progress, registered models, or failure context is needed."
        ),
        response_model=RunEventsResponse,
    )
    def get_run_events(
        token: str,
        limit: int = Query(default=20, ge=1, le=store.event_history_limit, description="Maximum number of most recent events to return."),
    ) -> dict[str, Any]:
        events = store.events(token)
        if events is None:
            raise HTTPException(
                status_code=404,
                detail={"message": "Execution token not found.", "token": token},
            )
        job = store.get(token)
        assert job is not None
        selected = events[-limit:]
        semantic_events = [{**event, "message": _event_message(event)} for event in selected]
        status = job["status"]
        return {
            "token": token,
            "status": status,
            "message": f"Returned {len(semantic_events)} most recent event(s) for this flow run.",
            "events": semantic_events,
            "count": len(semantic_events),
            "next_action": _next_action(token, status),
        }

    @app.get(
        "/status/{token}",
        tags=["execution"],
        deprecated=True,
        include_in_schema=False,
    )
    def get_status_compat(token: str) -> dict[str, Any]:
        job = store.get(token)
        if job is None:
            raise HTTPException(status_code=404, detail="Execution token not found.")
        return _project_status(job)

    return app

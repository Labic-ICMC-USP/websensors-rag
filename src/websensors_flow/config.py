"""Configuration models and YAML loading utilities for WebSensors Flow."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from websensors_flow.exceptions import ConfigurationError


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge two dictionaries recursively and return a new dictionary."""

    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _load_yaml_file(path: Path) -> dict[str, Any]:
    """Read a YAML file and return an empty dictionary when it has no content."""

    if not path.exists():
        raise ConfigurationError(f"YAML file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigurationError(f"YAML file must contain a mapping at the top level: {path}")
    return data


def _resolve_value(
    value: Any,
    env_name: str | None,
    *,
    required: bool,
    field_name: str,
) -> Any:
    """Resolve a configuration value using YAML first and environment second."""

    if value not in (None, ""):
        if env_name:
            os.environ[env_name] = str(value)
        return value

    if env_name:
        env_value = os.getenv(env_name)
        if env_value not in (None, ""):
            return env_value

    if required:
        hint = f" or define environment variable '{env_name}'" if env_name else ""
        raise ConfigurationError(f"Missing required configuration for '{field_name}'. Set it in YAML{hint}.")
    return value


class AuthConfig(BaseModel):
    """Optional authentication values for external services.

    Secrets may be written directly in YAML for local tests or referenced through
    environment variables for deployment. When a YAML value is present, it is
    exported to the configured environment variable before the client starts.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    username: str | None = None
    username_env: str | None = None
    password: str | None = None
    password_env: str | None = None
    token: str | None = None
    token_env: str | None = None

    def resolve(self, *, prefix: str) -> "AuthConfig":
        """Resolve credentials and validate that enabled authentication is complete."""

        data = self.model_dump()
        defaults = {
            "username_env": f"{prefix}_USERNAME",
            "password_env": f"{prefix}_PASSWORD",
            "token_env": f"{prefix}_TOKEN",
        }
        for key, default in defaults.items():
            if not data.get(key):
                data[key] = default

        data["username"] = _resolve_value(
            self.username,
            data["username_env"],
            required=False,
            field_name=f"{prefix.lower()}.auth.username",
        )
        data["password"] = _resolve_value(
            self.password,
            data["password_env"],
            required=False,
            field_name=f"{prefix.lower()}.auth.password",
        )
        data["token"] = _resolve_value(
            self.token,
            data["token_env"],
            required=False,
            field_name=f"{prefix.lower()}.auth.token",
        )

        resolved = AuthConfig(**data)
        if resolved.enabled:
            has_token = bool(resolved.token)
            has_user_password = bool(resolved.username and resolved.password)
            if not has_token and not has_user_password:
                raise ConfigurationError(
                    f"Authentication is enabled for {prefix.lower()}, but no token or username/password was provided."
                )
        return resolved


class ProjectConfig(BaseModel):
    """Static identification metadata for the flow."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str = "0.1.0"
    description: str | None = None


class EnvironmentConfig(BaseModel):
    """Deployment context attached to reports and logs."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1)
    deployment_id: str | None = None
    owner: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class ConsoleConfig(BaseModel):
    """Console output options."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    progress: bool = True
    show_metrics: bool = True


class RuntimeConfig(BaseModel):
    """Runtime behavior controlled by the framework."""

    model_config = ConfigDict(extra="forbid")

    report_dir: str = "./reports"
    fail_fast: bool = True
    include_traceback: bool = True
    raise_on_failure: bool = False
    console: ConsoleConfig = Field(default_factory=ConsoleConfig)

    @field_validator("fail_fast")
    @classmethod
    def fail_fast_must_be_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("WebSensors Flow uses an all-or-nothing policy. fail_fast must be true.")
        return value


class MLflowConfig(BaseModel):
    """MLflow tracking configuration."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    tracking_uri: str | None = None
    tracking_uri_env: str = "MLFLOW_TRACKING_URI"
    experiment_name: str | None = None
    experiment_name_env: str = "MLFLOW_EXPERIMENT_NAME"
    run_name: str | None = None
    artifact_location: str | None = None
    http_request_timeout: int | None = 3
    http_request_timeout_env: str = "MLFLOW_HTTP_REQUEST_TIMEOUT"
    connect_timeout_seconds: float = 3.0
    auth: AuthConfig = Field(default_factory=AuthConfig)

    def resolve(self) -> "MLflowConfig":
        """Resolve MLflow settings only when the observer is enabled."""

        data = self.model_dump()
        if not self.enabled:
            return MLflowConfig(**data)

        data["tracking_uri"] = _resolve_value(
            self.tracking_uri,
            self.tracking_uri_env,
            required=True,
            field_name="observability.mlflow.tracking_uri",
        )
        data["experiment_name"] = _resolve_value(
            self.experiment_name,
            self.experiment_name_env,
            required=True,
            field_name="observability.mlflow.experiment_name",
        )
        data["http_request_timeout"] = int(
            _resolve_value(
                self.http_request_timeout,
                self.http_request_timeout_env,
                required=False,
                field_name="observability.mlflow.http_request_timeout",
            )
            or 5
        )
        data["auth"] = self.auth.resolve(prefix="MLFLOW_TRACKING").model_dump()
        return MLflowConfig(**data)


class GraylogConfig(BaseModel):
    """Graylog GELF TCP configuration."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    host: str | None = None
    host_env: str = "GRAYLOG_HOST"
    port: int | None = None
    port_env: str = "GRAYLOG_PORT"
    protocol: Literal["tcp"] = "tcp"
    protocol_env: str = "GRAYLOG_PROTOCOL"
    facility: str = "websensors-flow"
    level: str = "INFO"
    localname: str | None = None
    connect_timeout_seconds: float = 3.0
    auth: AuthConfig = Field(default_factory=AuthConfig)

    @field_validator("port")
    @classmethod
    def validate_port(cls, value: int | None) -> int | None:
        if value is not None and not (1 <= int(value) <= 65535):
            raise ValueError("Graylog port must be between 1 and 65535.")
        return value

    def resolve(self) -> "GraylogConfig":
        """Resolve Graylog settings only when the observer is enabled."""

        data = self.model_dump()
        if not self.enabled:
            return GraylogConfig(**data)

        data["host"] = _resolve_value(
            self.host,
            self.host_env,
            required=True,
            field_name="observability.graylog.host",
        )
        port_value = _resolve_value(
            self.port,
            self.port_env,
            required=True,
            field_name="observability.graylog.port",
        )
        data["port"] = int(port_value)
        data["protocol"] = _resolve_value(
            self.protocol,
            self.protocol_env,
            required=True,
            field_name="observability.graylog.protocol",
        )
        data["auth"] = self.auth.resolve(prefix="GRAYLOG").model_dump()
        return GraylogConfig(**data)


class ObservabilityConfig(BaseModel):
    """Optional external observability configuration."""

    model_config = ConfigDict(extra="forbid")

    mlflow: MLflowConfig = Field(default_factory=MLflowConfig)
    graylog: GraylogConfig = Field(default_factory=GraylogConfig)

    def resolve(self) -> "ObservabilityConfig":
        return ObservabilityConfig(
            mlflow=self.mlflow.resolve(),
            graylog=self.graylog.resolve(),
        )


class PipelineConfig(BaseModel):
    """User-controlled parameters for all steps."""

    model_config = ConfigDict(extra="allow")

    params: dict[str, Any] = Field(default_factory=dict)


class StepDefinition(BaseModel):
    """Definition of one step used by automatic runners and the API mode."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    class_path: str | None = None
    enabled: bool = True
    config_path: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class ApiFieldConfig(BaseModel):
    """Field exposed by the FastAPI request schema."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["string", "integer", "number", "boolean", "object", "array"] = "string"
    required: bool = False
    default: Any = None
    description: str | None = None
    examples: list[Any] = Field(default_factory=list)


class ApiConfig(BaseModel):
    """FastAPI runner configuration."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    title: str = "WebSensors Flow API"
    description: str | None = None
    version: str = "0.1.0"
    host: str = "127.0.0.1"
    port: int = 8000
    endpoint: str = "/runs"
    workers: int = 2
    return_output: bool = False
    event_history_limit: int = 1000
    input_fields: dict[str, ApiFieldConfig] = Field(default_factory=dict)
    instructions: list[str] = Field(default_factory=list)
    result_description: str | None = None


class FlowSettings(BaseModel):
    """Validated configuration for a WebSensors Flow project."""

    model_config = ConfigDict(extra="forbid")

    source_path: str | None = None
    project: ProjectConfig
    environment: EnvironmentConfig
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    steps: list[StepDefinition] = Field(default_factory=list)
    api: ApiConfig = Field(default_factory=ApiConfig)

    def resolve_external_values(self) -> "FlowSettings":
        """Resolve service values and credentials from YAML or environment."""

        data = self.model_dump()
        data["observability"] = self.observability.resolve().model_dump()
        return FlowSettings(**data)

    @property
    def step_configs(self) -> dict[str, dict[str, Any]]:
        """Return all step configurations indexed by step name."""

        return {step.name: step.config for step in self.steps if step.enabled}

    def get_step_config(self, step_name: str) -> dict[str, Any]:
        """Return the configuration dictionary for one step."""

        return copy.deepcopy(self.step_configs.get(step_name, {}))


def _load_step_configs(raw: dict[str, Any], *, base_dir: Path) -> dict[str, Any]:
    """Load external YAML files referenced by the steps section."""

    steps = raw.get("steps", []) or []
    if not isinstance(steps, list):
        raise ConfigurationError("The 'steps' section must be a list.")

    loaded_steps: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            raise ConfigurationError("Each item in the 'steps' section must be a mapping.")
        step_data = copy.deepcopy(step)
        inline_config = step_data.get("config") or {}
        if inline_config and not isinstance(inline_config, dict):
            raise ConfigurationError(f"Step config must be a mapping for step '{step_data.get('name', '?')}'.")

        file_config: dict[str, Any] = {}
        config_path = step_data.get("config_path")
        if config_path:
            path = Path(config_path)
            if not path.is_absolute():
                path = base_dir / path
            file_config = _load_yaml_file(path)
        step_data["config"] = deep_merge(file_config, inline_config)
        loaded_steps.append(step_data)

    raw["steps"] = loaded_steps
    return raw


def load_settings(path: str | Path) -> FlowSettings:
    """Load, resolve, and validate a WebSensors Flow YAML file."""

    path = Path(path)
    if not path.exists():
        raise ConfigurationError(f"Configuration file not found: {path}")

    raw = _load_yaml_file(path)
    raw = _load_step_configs(raw, base_dir=path.parent)
    raw["source_path"] = str(path)

    try:
        settings = FlowSettings.model_validate(raw)
        return settings.resolve_external_values()
    except ValidationError as exc:
        raise ConfigurationError(str(exc)) from exc

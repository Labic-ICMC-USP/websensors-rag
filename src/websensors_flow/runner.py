"""Utilities for loading and running configured flows."""

from __future__ import annotations

import importlib
from typing import Any

from websensors_flow.config import FlowSettings, StepDefinition, deep_merge
from websensors_flow.exceptions import ConfigurationError
from websensors_flow.pipeline import WebSensorsPipeline, build_pipeline_from_settings
from websensors_flow.report import PipelineRunResult
from websensors_flow.step import PipelineStep
from websensors_flow.observers.base import PipelineObserver


def import_step_class(class_path: str) -> type[PipelineStep]:
    """Import a PipelineStep subclass from a dotted class path."""

    module_name, _, class_name = class_path.rpartition(".")
    if not module_name or not class_name:
        raise ConfigurationError(f"Invalid step class path: {class_path}")
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    if not issubclass(cls, PipelineStep):
        raise ConfigurationError(f"Step class must extend PipelineStep: {class_path}")
    return cls


def instantiate_step(definition: StepDefinition) -> PipelineStep:
    """Instantiate one step declared in the YAML file."""

    if not definition.class_path:
        raise ConfigurationError(f"Step '{definition.name}' does not define class_path.")
    cls = import_step_class(definition.class_path)
    step = cls()
    if step.name is None:
        step.name = definition.name
    elif step.step_name != definition.name:
        step.name = definition.name
    return step


def build_configured_steps(settings: FlowSettings) -> list[PipelineStep]:
    """Create all enabled steps declared in the flow YAML file."""

    return [instantiate_step(definition) for definition in settings.steps if definition.enabled]


def build_configured_pipeline(
    settings: FlowSettings,
    *,
    include_console: bool = True,
    run_id: str | None = None,
    extra_observers: list[PipelineObserver] | None = None,
) -> WebSensorsPipeline:
    """Build a pipeline and attach all steps declared in YAML."""

    pipeline = build_pipeline_from_settings(settings, include_console=include_console, run_id=run_id, extra_observers=extra_observers)
    for step in build_configured_steps(settings):
        pipeline.add(step)
    return pipeline


def run_configured_flow(
    settings: FlowSettings,
    *,
    input: Any = None,
    params: dict[str, Any] | None = None,
    run_id: str | None = None,
    extra_observers: list[PipelineObserver] | None = None,
) -> PipelineRunResult:
    """Run a flow declared entirely in YAML."""

    run_settings = settings.model_copy(deep=True)
    if params:
        run_settings.pipeline.params = deep_merge(run_settings.pipeline.params, params)
    pipeline = build_configured_pipeline(run_settings, run_id=run_id, extra_observers=extra_observers)
    return pipeline.run(input=input)

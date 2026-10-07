"""Base class for user-defined pipeline steps."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from websensors_flow.context import PipelineContext
from websensors_flow.exceptions import StepContractError
from websensors_flow.result import StepResult


class PipelineStep(ABC):
    """Base class for a pipeline step.

    Users should extend this class and implement :meth:`execute`.

    The framework calls :meth:`run`, which wraps ``execute`` and validates that
    the returned value is a :class:`StepResult`. This template-method pattern
    prevents each user step from bypassing the observability contract.
    """

    name: str | None = None

    def setup(self, context: PipelineContext) -> None:
        """Optional setup hook executed before ``execute``."""

    @abstractmethod
    def execute(self, input: Any, context: PipelineContext) -> StepResult:
        """Execute the step.

        Parameters
        ----------
        input:
            Any object produced by the previous step. The framework does not
            inspect it.
        context:
            Lightweight execution context containing settings, run id, current
            step, environment, and small state.
        """

    def teardown(self, context: PipelineContext) -> None:
        """Optional teardown hook executed after ``execute``."""

    def describe(self) -> dict[str, Any]:
        """Return optional static step description for reports."""

        return {}

    def run(self, input: Any, context: PipelineContext) -> StepResult:
        """Run and validate the user step."""

        result = self.execute(input, context)
        if not isinstance(result, StepResult):
            raise StepContractError(
                f"Step '{self.step_name}' must return StepResult, got {type(result).__name__}."
            )
        return result

    @property
    def step_name(self) -> str:
        """Return the public name of this step."""

        return self.name or self.__class__.__name__

"""Custom exceptions used by WebSensors Flow."""

from __future__ import annotations

from typing import Optional


class WebSensorsFlowError(Exception):
    """Base class for all framework errors."""


class ConfigurationError(WebSensorsFlowError):
    """Raised when the YAML configuration or environment is invalid."""


class StepContractError(WebSensorsFlowError):
    """Raised when a user-defined step violates the framework contract."""


class ObserverError(WebSensorsFlowError):
    """Raised when an active observer cannot start or cannot record an event."""


class PreflightCheckError(ObserverError):
    """Raised when an active observer is not ready before the run starts."""


class PipelineExecutionError(WebSensorsFlowError):
    """Raised when the all-or-nothing pipeline fails."""

    def __init__(self, message: str, failure: Optional[object] = None):
        super().__init__(message)
        self.failure = failure

"""Observer interfaces."""

from __future__ import annotations

from websensors_flow.events import PipelineEvent


class PipelineObserver:
    """Base observer used by the pipeline event bus."""

    name = "base"

    def validate_ready(self) -> None:
        """Validate that the observer can be used before the first step starts."""

    def preflight_probe(self, event: PipelineEvent) -> None:
        """Send a real preflight event before the first user step starts."""

    def on_event(self, event: PipelineEvent) -> None:
        """Receive a pipeline event."""

    def close(self, status: str) -> None:
        """Close resources after a pipeline run."""

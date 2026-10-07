"""Step-level loop progress and ETA reporting."""

from __future__ import annotations

from time import perf_counter
from typing import Any, Callable

from websensors_flow.events import PipelineEvent


class ProgressTracker:
    """Emit backend-agnostic progress events for loops inside a pipeline step."""

    def __init__(
        self,
        *,
        total: int,
        description: str,
        unit: str,
        emit: Callable[[PipelineEvent], None],
        event_factory: Callable[..., PipelineEvent],
        every: int = 1,
    ) -> None:
        if total <= 0:
            raise ValueError("Progress total must be greater than zero.")
        self.total = int(total)
        self.description = description
        self.unit = unit
        self.emit = emit
        self.event_factory = event_factory
        self.every = max(int(every), 1)
        self.current = 0
        self._started = perf_counter()
        self._last_emitted = -1
        self._emit("started")

    def update(self, advance: int = 1, *, metadata: dict[str, Any] | None = None) -> None:
        self.current = min(self.total, self.current + int(advance))
        if self.current == self.total or self.current - self._last_emitted >= self.every:
            self._emit("running", extra_metadata=metadata)

    def set(self, current: int, *, metadata: dict[str, Any] | None = None) -> None:
        self.current = min(self.total, max(0, int(current)))
        self._emit("running", extra_metadata=metadata)

    def close(self) -> None:
        self.current = self.total
        self._emit("completed")

    def __enter__(self) -> "ProgressTracker":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc is None:
            self.close()

    def _emit(self, status: str, *, extra_metadata: dict[str, Any] | None = None) -> None:
        elapsed = max(perf_counter() - self._started, 0.0)
        rate = self.current / elapsed if elapsed > 0 and self.current > 0 else 0.0
        remaining = max(self.total - self.current, 0)
        eta = remaining / rate if rate > 0 else None
        percent = (self.current / self.total) * 100.0
        metadata = {
            "description": self.description,
            "unit": self.unit,
            "current": self.current,
            "total": self.total,
            "percent": round(percent, 2),
            "elapsed_seconds": round(elapsed, 3),
            "rate_per_second": round(rate, 3),
            "eta_seconds": round(eta, 3) if eta is not None else None,
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        self.emit(
            self.event_factory(
                event_type="progress",
                status=status,
                text=self.description,
                metrics={
                    "progress_percent": percent,
                    "progress_current": self.current,
                    "progress_total": self.total,
                },
                metadata=metadata,
            )
        )
        self._last_emitted = self.current

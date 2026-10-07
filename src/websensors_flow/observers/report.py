"""Local report observer."""

from __future__ import annotations

from pathlib import Path

from websensors_flow.config import FlowSettings
from websensors_flow.events import PipelineEvent
from websensors_flow.observers.base import PipelineObserver
from websensors_flow.report import ExecutionReport


class ReportObserver(PipelineObserver):
    """Write JSON and Markdown reports to the configured report directory."""

    name = "report"

    def __init__(self, *, settings: FlowSettings, report: ExecutionReport):
        self.settings = settings
        self.report = report
        self.report_dir = Path(settings.runtime.report_dir)

    def validate_ready(self) -> None:
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def on_event(self, event: PipelineEvent) -> None:
        if event.event_type in {"pipeline_completed", "pipeline_failed"}:
            self._write_reports()

    def _write_reports(self) -> None:
        run_dir = self.report_dir / self.report.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "execution_report.json").write_text(self.report.model_dump_json(indent=2), encoding="utf-8")
        (run_dir / "execution_report.md").write_text(self.report.to_markdown(), encoding="utf-8")

"""Observador de terminal para execução detalhada do pipeline."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from websensors_flow.events import PipelineEvent
from websensors_flow.observers.base import PipelineObserver

try:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
except Exception:  # pragma: no cover
    box = None  # type: ignore
    Console = None  # type: ignore
    Panel = None  # type: ignore
    Table = None  # type: ignore


class ConsoleObserver(PipelineObserver):
    """Apresenta steps, progresso, métricas, ETA e resumo final no terminal."""

    name = "console"

    def __init__(self, *, enabled: bool = True, progress: bool = True, show_metrics: bool = True, report_dir: str | None = None):
        self.enabled = enabled
        self.progress = progress
        self.show_metrics = show_metrics
        self.report_dir = report_dir
        self._steps_total = 0
        self._steps_done = 0
        self._elapsed_steps = 0.0
        self._pipeline_started_at: float | None = None
        self._step_rows: list[tuple[int, str, str, float]] = []
        self._console = Console(highlight=False, soft_wrap=True) if Console is not None else None

    def validate_ready(self) -> None:
        return None

    def preflight_probe(self, event: PipelineEvent) -> None:
        return None

    def on_event(self, event: PipelineEvent) -> None:
        if not self.enabled:
            return
        handler = getattr(self, f"_on_{event.event_type}", None)
        if handler is not None:
            handler(event)

    def close(self, status: str) -> None:
        return None

    def _eta_flow(self) -> str:
        remaining = max(self._steps_total - self._steps_done, 0)
        if remaining == 0:
            return "0.0s"
        if self._steps_done == 0:
            return "calculando"
        average = self._elapsed_steps / self._steps_done
        return f"{average * remaining:.1f}s"

    def _on_preflight_configuration(self, event: PipelineEvent) -> None:
        self._title("WebSensors Flow RAG")
        self._write(self._configuration_table(event.metadata))
        self._section("Validação da execução")

    def _on_preflight_observer_status(self, event: PipelineEvent) -> None:
        fields = {
            "fase": event.metadata.get("phase", ""),
            "destino": event.metadata.get("target", ""),
            "duração": self._duration(event.metadata.get("duration_seconds")),
        }
        if event.metadata.get("error"):
            fields["erro"] = event.metadata.get("error")
        self._write(self._status_panel(str(event.status or "INFO").upper(), "observabilidade", str(event.metadata.get("observer", "observador")), str(event.metadata.get("action", "")), fields))

    def _on_pipeline_started(self, event: PipelineEvent) -> None:
        self._steps_total = int(event.metadata.get("steps_total", 0) or 0)
        self._steps_done = 0
        self._elapsed_steps = 0.0
        self._pipeline_started_at = perf_counter()
        self._step_rows = []
        self._section("Pipeline de indexação")
        self._write(self._status_panel(
            "EXECUTANDO", "pipeline", event.pipeline_name, "Execução iniciada",
            {"run_id": event.run_id, "ambiente": event.environment, "steps": self._steps_total, "ETA": self._eta_flow()},
        ))

    def _on_step_started(self, event: PipelineEvent) -> None:
        index = int(event.step_index or (self._steps_done + 1))
        name = self._step_name(event)
        self._write(self._status_panel(
            "EXECUTANDO", f"step {index}/{self._steps_total}", name, "Step iniciado",
            {"progresso": f"{self._steps_done}/{self._steps_total}", "ETA do fluxo": self._eta_flow(), **self._compact_fields(event.metadata)},
        ))

    def _on_user_log(self, event: PipelineEvent) -> None:
        fields: dict[str, Any] = {}
        if event.metrics:
            fields["métricas"] = self._inline_mapping(event.metrics, 10)
        if event.params:
            fields["parâmetros"] = self._inline_mapping(event.params, 6)
        if event.metadata:
            fields["metadados"] = self._inline_mapping(event.metadata, 6)
        if event.artifacts:
            fields["artefatos"] = ", ".join(event.artifacts.keys())
        self._write(self._status_panel(self._status_from_level(event.level), "detalhe", event.step_name or event.pipeline_name, event.text or "Evento da execução", fields))

    def _on_progress(self, event: PipelineEvent) -> None:
        if not self.progress:
            return
        m = event.metadata
        eta = self._duration(m.get("eta_seconds")) if m.get("eta_seconds") is not None else "calculando"
        elapsed = self._duration(m.get("elapsed_seconds"))
        rate = m.get("rate_per_second", 0)
        description = m.get("description", event.text or "Progresso")
        current = m.get("current", 0)
        total = m.get("total", 0)
        unit = m.get("unit", "itens")
        percent = float(m.get("percent", 0.0))
        self._write(
            f"  {event.step_name or 'step'}  {description}  {current}/{total} {unit}  "
            f"{percent:.1f}%  taxa {rate} {unit}/s  decorrido {elapsed}  ETA {eta}"
        )

    def _on_model_registered(self, event: PipelineEvent) -> None:
        fields = {**event.params, **event.metadata}
        self._write(self._status_panel("INFO", "modelo", str(event.params.get("name", event.text or "modelo")), "Modelo registrado na execução", fields))

    def _on_trace_started(self, event: PipelineEvent) -> None:
        self._write(f"  trace iniciado  {event.text or ''}  span {event.span_id or '-'}  ETA calculando")

    def _on_trace_completed(self, event: PipelineEvent) -> None:
        self._write(f"  trace concluído  {event.text or ''}  duração {self._duration(event.duration_seconds)}  ETA {self._eta_flow()}")

    def _on_trace_failed(self, event: PipelineEvent) -> None:
        self._write(f"  trace falhou  {event.text or ''}  duração {self._duration(event.duration_seconds)}  erro {event.error_message or '-'}")

    def _on_step_completed(self, event: PipelineEvent) -> None:
        duration = float(event.duration_seconds or 0.0)
        self._steps_done += 1
        self._elapsed_steps += duration
        index = int(event.step_index or self._steps_done)
        name = self._step_name(event)
        self._step_rows.append((index, name, "OK", duration))
        fields: dict[str, Any] = {
            "duração": self._duration(duration),
            "progresso": f"{self._steps_done}/{self._steps_total}",
            "ETA do fluxo": self._eta_flow(),
        }
        if event.metrics and self.show_metrics:
            fields["métricas"] = self._inline_mapping(event.metrics, 12)
        if event.artifacts:
            fields["artefatos"] = ", ".join(event.artifacts.keys())
        self._write(self._status_panel("OK", f"step {index}/{self._steps_total}", name, event.text or "Step concluído", fields))

    def _on_step_failed(self, event: PipelineEvent) -> None:
        duration = float(event.duration_seconds or 0.0)
        index = int(event.step_index or (self._steps_done + 1))
        name = self._step_name(event)
        self._step_rows.append((index, name, "FALHOU", duration))
        self._write(self._status_panel(
            "FALHOU", f"step {index}/{self._steps_total}", name, "A execução foi interrompida neste step",
            {"duração": self._duration(duration), "erro": event.error_message or event.error_type or "erro não informado", "ETA": "indisponível"},
        ))

    def _on_pipeline_completed(self, event: PipelineEvent) -> None:
        self._section("Resumo da indexação")
        self._write(self._steps_table())
        self._write(self._status_panel(
            "OK", "pipeline", event.pipeline_name, "Indexação concluída com sucesso",
            {"duração total": self._duration(event.duration_seconds), "steps concluídos": f"{self._steps_done}/{self._steps_total}", "ETA": "0.0s"},
        ))
        self._report_hint()

    def _on_pipeline_failed(self, event: PipelineEvent) -> None:
        self._section("Resumo da indexação")
        self._write(self._steps_table())
        self._write(self._status_panel(
            "FALHOU", "pipeline", event.pipeline_name, "Indexação encerrada com falha",
            {"duração total": self._duration(event.duration_seconds), "erro": event.error_message or event.error_type or "erro não informado", "ETA": "indisponível"},
        ))
        self._report_hint()

    def _on_preflight_failed(self, event: PipelineEvent) -> None:
        self._write(self._status_panel("FALHOU", "validação", "pipeline", "Nenhum step foi executado", {"erro": event.error_message or "erro não informado", "ETA": "indisponível"}))
        self._report_hint()

    def _steps_table(self) -> Any:
        if Table is None:
            return "\n".join(f"{i} {name} {status} {duration:.3f}s" for i, name, status, duration in self._step_rows)
        table = Table(box=box.ROUNDED, expand=True, show_lines=False)
        table.add_column("Step", justify="right", width=6)
        table.add_column("Etapa", style="bold")
        table.add_column("Estado", justify="center", width=12)
        table.add_column("Duração", justify="right", width=12)
        for index, name, status, duration in self._step_rows:
            style = "green" if status == "OK" else "red"
            table.add_row(str(index), name, f"[{style}]{status}[/{style}]", f"{duration:.3f}s")
        return table

    def _configuration_table(self, metadata: dict[str, Any]) -> Any:
        rows = [
            ("Configuração", metadata.get("config_file", "-")),
            ("Run ID", metadata.get("run_id", "-")),
            ("Projeto", metadata.get("project", "-")),
            ("Ambiente", metadata.get("environment", "-")),
            ("Relatórios", metadata.get("report_dir", "-")),
            ("MLflow", f"{metadata.get('mlflow', '-')}  {metadata.get('mlflow_tracking_uri', '-')}"),
            ("Graylog", f"{metadata.get('graylog', '-')}  {metadata.get('graylog_host', '-')}"),
        ]
        if Table is None:
            return "\n".join(f"{k}  {v}" for k, v in rows)
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column("Configuração", style="bold cyan", width=20)
        table.add_column("Valor")
        for key, value in rows:
            table.add_row(str(key), self._text(value, 130))
        return table

    def _status_panel(self, status: str, category: str, name: str, message: str, fields: dict[str, Any]) -> Any:
        lines = [message]
        for key, value in fields.items():
            if value not in (None, "", {}, []):
                lines.append(f"{key}  {self._text(value, 160)}")
        style = "green" if status in {"OK", "SUCCESS"} else "red" if status in {"FAILED", "FALHOU"} else "cyan"
        title = f"{category}  {name}  {status}"
        if Panel is None:
            return title + "\n" + "\n".join(lines)
        return Panel("\n".join(lines), title=title, border_style=style, expand=True)

    def _section(self, title: str) -> None:
        self._write(f"\n[bold cyan]{title}[/bold cyan]" if self._console else f"\n{title}")

    def _title(self, title: str) -> None:
        if Panel is not None and self._console is not None:
            self._console.print(Panel(f"[bold]{title}[/bold]", border_style="cyan", expand=True))
        else:
            self._write(title)

    def _write(self, value: Any) -> None:
        if value in (None, ""):
            return
        if self._console is not None:
            self._console.print(value)
        else:
            print(value)

    def _step_name(self, event: PipelineEvent) -> str:
        return str(event.step_name or f"step_{event.step_index or '?'}")

    def _status_from_level(self, level: str) -> str:
        value = str(level or "INFO").upper()
        return "FALHOU" if value in {"ERROR", "CRITICAL"} else value

    def _compact_fields(self, mapping: dict[str, Any], limit: int = 8) -> dict[str, Any]:
        return {k: v for k, v in list(mapping.items())[:limit] if v not in (None, "", {}, [])}

    def _inline_mapping(self, mapping: dict[str, Any], limit: int = 8) -> str:
        items = list(mapping.items())
        text = "; ".join(f"{k}={self._text(v, 80)}" for k, v in items[:limit])
        if len(items) > limit:
            text += f"; mais {len(items) - limit}"
        return text or "-"

    def _text(self, value: Any, limit: int = 140) -> str:
        text = str(value)
        return text if len(text) <= limit else text[: limit - 3] + "..."

    def _duration(self, value: Any) -> str:
        if value is None or value == "":
            return "-"
        try:
            return f"{float(value):.3f}s"
        except Exception:
            return str(value)

    def _report_hint(self) -> None:
        if self.report_dir:
            self._write(f"Relatório da execução  {self.report_dir}")

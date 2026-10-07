"""Relatório detalhado por steps no terminal."""

import io

from rich.console import Console

from websensors_flow.events import PipelineEvent
from websensors_flow.observers.console import ConsoleObserver


def event(kind, *, step=None, index=None, seconds=None, **kwargs):
    return PipelineEvent(
        event_type=kind,
        pipeline_name="websensors-flow-rag",
        run_id="teste-001",
        environment="local",
        step_name=step,
        step_index=index,
        duration_seconds=seconds,
        **kwargs,
    )


def test_console_shows_steps_progress_eta_and_summary():
    output = io.StringIO()
    observer = ConsoleObserver(report_dir="./outputs/reports")
    observer._console = Console(file=output, force_terminal=False, width=125)
    observer.on_event(event("pipeline_started", metadata={"steps_total": 2}))
    observer.on_event(event("step_started", step="resolver_fonte", index=1))
    observer.on_event(event("step_completed", step="resolver_fonte", index=1, seconds=2.0, text="Fonte localizada", metrics={"source_bytes": 2048}))
    observer.on_event(event("step_started", step="gerar_embeddings", index=2))
    observer.on_event(event("progress", step="gerar_embeddings", index=2, metadata={
        "description": "Gerando embeddings", "current": 3, "total": 6, "unit": "lotes",
        "percent": 50.0, "elapsed_seconds": 2.0, "rate_per_second": 1.5, "eta_seconds": 2.0,
    }))
    observer.on_event(event("step_completed", step="gerar_embeddings", index=2, seconds=4.0))
    observer.on_event(event("pipeline_completed", seconds=6.0))
    text = output.getvalue()
    assert "step 1/2" in text
    assert "step 2/2" in text
    assert "ETA" in text
    assert "Gerando embeddings" in text
    assert "3/6 lotes" in text
    assert "Resumo da indexação" in text
    assert "Fonte localizada" in text
    assert "0.0s" in text


def test_console_shows_failed_step():
    output = io.StringIO()
    observer = ConsoleObserver()
    observer._console = Console(file=output, force_terminal=False, width=115)
    observer.on_event(event("pipeline_started", metadata={"steps_total": 1}))
    observer.on_event(event("step_failed", step="converter_docling", index=1, seconds=1.2, error_message="Falha na conversão"))
    observer.on_event(event("pipeline_failed", seconds=1.2, error_message="Falha na conversão"))
    text = output.getvalue()
    assert "converter_docling" in text
    assert "FALHOU" in text
    assert "Falha na conversão" in text

"""Saída visual do preflight e encerramento limpo da API."""

import io
import sys
from pathlib import Path

import pytest
from rich.console import Console

from websensors_flow_rag.cli import main_api, main_health
from websensors_flow_rag.config import load_rag_settings
from websensors_flow_rag.healthchecks import CheckResult, HealthReport
from websensors_flow_rag.startup_report import render_health_report, run_health_preflight

SETTINGS = Path(__file__).parents[1] / "config" / "rag.yaml"


def unhealthy_report() -> HealthReport:
    return HealthReport(
        checks=[
            CheckResult("elasticsearch", False, "RuntimeError Estado do cluster red", 4.1, 3),
            CheckResult("minio", False, "S3Error InvalidAccessKeyId", 0.1, 1),
            CheckResult("docling", True, "health=ok ready=ok", 0.12, 1),
            CheckResult("embeddings", True, "modelo=texto dimensoes=1024 inferencia=ok", 0.9, 1),
            CheckResult("mlflow", True, "desativado", 0, enabled=False),
            CheckResult("graylog", True, "desativado", 0, enabled=False),
        ],
        duration_seconds=5.8,
    )


def test_report_lists_failures_and_specific_actions():
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=False, width=125)
    render_health_report(unhealthy_report(), load_rag_settings(SETTINGS), console=console)
    output = buffer.getvalue()
    assert "INICIALIZAÇÃO INTERROMPIDA" in output
    assert "Disponíveis 2/4" in output
    assert "/_cat/shards" in output
    assert "services.minio.access_key" in output
    assert "Traceback" not in output


def test_preflight_renders_single_report():
    events = []
    class FakeChecker:
        def __init__(self, settings): pass
        def check_all(self, *, strict, probe_mlflow_write, on_progress):
            events.append((strict, probe_mlflow_write))
            on_progress("started", "elasticsearch", 0, 4, 1)
            on_progress("finished", "elasticsearch", 1, 4, 1)
            return unhealthy_report()
    buffer = io.StringIO(); console = Console(file=buffer, force_terminal=False, width=115)
    report = run_health_preflight(load_rag_settings(SETTINGS), console=console, checker_factory=FakeChecker)
    assert report.ok is False
    assert events == [(False, True)]
    assert buffer.getvalue().count("INICIALIZAÇÃO INTERROMPIDA") == 1


def test_api_unhealthy_exits_before_uvicorn_without_traceback(monkeypatch, capsys):
    called = []
    monkeypatch.setattr(sys, "argv", ["websensors-flow-rag-api", "--config", str(SETTINGS)])
    monkeypatch.setattr("websensors_flow_rag.cli.run_health_preflight", lambda settings: unhealthy_report())
    monkeypatch.setattr("websensors_flow_rag.cli._prepare_elasticsearch", lambda settings: called.append("indices"))
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: called.append("uvicorn"))
    with pytest.raises(SystemExit) as exc: main_api()
    assert exc.value.code == 1
    assert called == []
    assert "Traceback" not in capsys.readouterr().err


def test_healthy_api_starts_uvicorn_without_rechecking(monkeypatch):
    called = []
    monkeypatch.setattr(sys, "argv", ["websensors-flow-rag-api", "--config", str(SETTINGS)])
    monkeypatch.setattr("websensors_flow_rag.cli.run_health_preflight", lambda settings: HealthReport([], 0.2))
    monkeypatch.setattr("websensors_flow_rag.cli._prepare_elasticsearch", lambda settings: called.append("indices"))
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: called.append("uvicorn"))
    main_api()
    assert called == ["indices", "uvicorn"]


def test_health_cli_returns_code_1_without_traceback(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["websensors-flow-rag-health", "--config", str(SETTINGS)])
    monkeypatch.setattr("websensors_flow_rag.cli.run_health_preflight", lambda settings: unhealthy_report())
    with pytest.raises(SystemExit) as exc: main_health()
    assert exc.value.code == 1
    assert "Traceback" not in capsys.readouterr().err


def test_permanent_minio_error_is_not_retried(monkeypatch):
    from websensors_flow_rag.healthchecks import HealthChecker
    settings = load_rag_settings(SETTINGS); settings.startup.retries = 3; settings.startup.retry_interval_seconds = 0
    checker = HealthChecker(settings)
    monkeypatch.setattr(checker, "_elasticsearch", lambda: "ok")
    monkeypatch.setattr(checker, "_docling", lambda: "ok")
    monkeypatch.setattr(checker, "_embeddings", lambda: "ok")
    attempts = []
    def bad_minio():
        attempts.append(1); raise RuntimeError("InvalidAccessKeyId")
    monkeypatch.setattr(checker, "_minio", bad_minio)
    report = checker.check_all(strict=False)
    assert not report.ok
    assert len(attempts) == 1

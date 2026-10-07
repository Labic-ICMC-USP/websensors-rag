"""Validação das verificações que antecedem a criação de índices."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from websensors_flow_rag.api import create_rag_app
from websensors_flow_rag.config import load_rag_settings
from websensors_flow_rag.healthchecks import HealthChecker, StartupHealthError

SETTINGS = Path(__file__).parents[1] / "config" / "rag.yaml"


def mock_dependencies(monkeypatch):
    for name in ("_elasticsearch", "_minio", "_docling", "_embeddings"):
        monkeypatch.setattr(HealthChecker, name, lambda self: "ok")


def test_startup_checks_every_mandatory_service_before_indices(monkeypatch, caplog):
    settings = load_rag_settings(SETTINGS)
    settings.startup.retries = 0
    mock_dependencies(monkeypatch)
    events = []
    original = HealthChecker.check_all

    def checker(self, *, strict=True, **kwargs):
        assert strict
        events.append("saude")
        return original(self, strict=strict, **kwargs)

    monkeypatch.setattr(HealthChecker, "check_all", checker)
    monkeypatch.setattr("websensors_flow_rag.api.ElasticsearchClient.ensure_indices", lambda self: events.append("indices"))

    with caplog.at_level("INFO"):
        with TestClient(create_rag_app(settings)) as client:
            assert client.get("/rag").status_code == 200
    assert events == ["saude", "indices"]
    assert "ETA" in caplog.text
    assert "Serviço docling OK" in caplog.text


def test_unhealthy_service_interrupts_startup_and_reports_all(monkeypatch):
    settings = load_rag_settings(SETTINGS)
    settings.startup.retries = 0
    mock_dependencies(monkeypatch)
    monkeypatch.setattr(HealthChecker, "_docling", lambda self: (_ for _ in ()).throw(RuntimeError("readiness HTTP 503")))
    report = HealthChecker(settings).check_all(strict=False)
    assert not report.ok
    assert next(c for c in report.checks if c.name == "docling").detail.endswith("HTTP 503")
    assert any(c.name == "embeddings" and c.ok for c in report.checks)
    with pytest.raises(StartupHealthError, match="docling"):
        HealthChecker(settings).check_all(strict=True)


def test_disabled_mlflow_is_not_counted_as_healthy_service(monkeypatch):
    settings = load_rag_settings(SETTINGS)
    settings.startup.retries = 0
    mock_dependencies(monkeypatch)
    report = HealthChecker(settings).check_all(strict=True)
    mlflow = next(c for c in report.checks if c.name == "mlflow")
    assert not mlflow.enabled
    assert mlflow.as_dict()["status"] == "desativado"


def test_mlflow_check_uses_write_probe_only_during_startup(monkeypatch):
    settings = load_rag_settings(SETTINGS)
    settings.startup.retries = 0
    settings.observability.mlflow.enabled = True
    settings.startup.check_mlflow_write = True
    mock_dependencies(monkeypatch)
    writes = []
    monkeypatch.setattr(HealthChecker, "_mlflow", lambda self, write_probe=False: writes.append(write_probe) or "ok")
    HealthChecker(settings).check_all(strict=True)
    HealthChecker(settings).check_all(strict=False)
    assert writes == [True, False]


def test_health_returns_503_when_dependency_fails(monkeypatch):
    settings = load_rag_settings(SETTINGS)
    settings.startup.enabled = False
    settings.startup.retries = 0
    mock_dependencies(monkeypatch)
    monkeypatch.setattr(HealthChecker, "_docling", lambda self: (_ for _ in ()).throw(RuntimeError("503")))
    monkeypatch.setattr("websensors_flow_rag.api.ElasticsearchClient.ensure_indices", lambda self: None)
    with TestClient(create_rag_app(settings)) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["dependencies"]["docling"] == "indisponivel"
    assert response.json()["dependencies"]["mlflow"] == "desativado"

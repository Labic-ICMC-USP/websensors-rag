"""Diagnóstico das dependências antes de aceitar requisições."""

from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import httpx

from websensors_flow.events import PipelineEvent
from websensors_flow.observers.mlflow import MLflowObserver
from websensors_flow_rag.clients.docling_client import DoclingClient
from websensors_flow_rag.clients.elasticsearch_client import ElasticsearchClient
from websensors_flow_rag.clients.minio_client import MinIOClient
from websensors_flow_rag.clients.model_client import EmbeddingClient
from websensors_flow_rag.config import RAGSettings

logger = logging.getLogger("websensors_flow_rag.startup")


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    duration_seconds: float
    attempts: int = 1
    enabled: bool = True

    def as_dict(self) -> dict:
        return {
            "service": self.name,
            "status": ("ok" if self.ok else "falha") if self.enabled else "desativado",
            "detail": self.detail,
            "duration_seconds": round(self.duration_seconds, 3),
            "attempts": self.attempts,
        }


@dataclass
class HealthReport:
    checks: list[CheckResult]
    duration_seconds: float

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks if c.enabled)


class StartupHealthError(RuntimeError):
    """A aplicação não deve subir quando as dependências obrigatórias falham."""


class HealthChecker:
    def __init__(self, settings: RAGSettings):
        self.settings = settings

    def _elasticsearch(self) -> str:
        client = ElasticsearchClient(
            self.settings.services.elasticsearch, self.settings.services.embeddings.dimensions
        )
        client.client.timeout = httpx.Timeout(self.settings.startup.timeout_seconds)
        try:
            response = client.client.get("/")
            response.raise_for_status()
            payload = response.json()
            if not payload.get("cluster_name"):
                raise RuntimeError("A resposta não contém cluster_name")
            health = client.client.get("/_cluster/health")
            health.raise_for_status()
            info = health.json()
            state = str(info.get("status", "desconhecido"))
            if state not in {"yellow", "green"}:
                raise RuntimeError(f"Estado do cluster {state}. Consulte /_cluster/health")
            return f"cluster={payload['cluster_name']} status={state} nodes={info.get('number_of_nodes', '?')}"
        finally:
            client.close()

    def _minio(self) -> str:
        client = MinIOClient(self.settings.services.minio)
        required = (
            self.settings.services.minio.bronze_bucket,
            self.settings.services.minio.silver_bucket,
        )
        missing = [bucket for bucket in required if not client.client.bucket_exists(bucket)]
        if missing:
            raise RuntimeError(f"Buckets ausentes {', '.join(missing)}")
        return f"buckets={', '.join(required)}"

    def _docling(self) -> str:
        client = DoclingClient(self.settings.services.docling)
        client.client.timeout = httpx.Timeout(self.settings.startup.timeout_seconds)
        try:
            health = client.client.get(f"{client.base_url}/health")
            health.raise_for_status()
            ready = client.client.get(f"{client.base_url}/ready")
            ready.raise_for_status()
            return "health=ok ready=ok"
        finally:
            client.close()

    def _embeddings(self) -> str:
        client = EmbeddingClient(self.settings.services.embeddings)
        client.client.timeout = httpx.Timeout(self.settings.startup.timeout_seconds)
        try:
            endpoint = self.settings.services.embeddings.endpoint.rstrip("/")
            response = client.client.get(f"{endpoint}/models")
            response.raise_for_status()
            payload = response.json()
            model = self.settings.services.embeddings.model
            entries = payload.get("data", []) if isinstance(payload, dict) else []
            if isinstance(entries, list) and entries:
                identifiers = {m.get("id") for m in entries if isinstance(m, dict)}
                if model not in identifiers:
                    raise RuntimeError(f"Modelo '{model}' não consta em /models")
            if self.settings.startup.validate_embedding_vector:
                vector = client.embed(["Teste de disponibilidade de embeddings"])[0]
                return f"modelo={model} dimensoes={len(vector)} inferencia=ok"
            return f"modelo={model} catalogo=ok"
        finally:
            client.close()

    def _mlflow(self, write_probe: bool = False) -> str:
        config = self.settings.to_flow_settings()
        obs = MLflowObserver(config.observability.mlflow, settings=config)
        obs.validate_ready()
        if write_probe:
            obs.preflight_probe(
                PipelineEvent(
                    event_type="preflight_probe",
                    pipeline_name=self.settings.project.name,
                    run_id=f"startup-{int(time.time())}",
                    environment=self.settings.environment.name,
                    timestamp=datetime.now(timezone.utc),
                    metadata={"steps_total": len(config.steps)},
                )
            )
        return f"tracking_uri={config.observability.mlflow.tracking_uri} leitura=ok" + (
            " escrita=ok" if write_probe else ""
        )

    def _graylog(self) -> str:
        cfg = self.settings.observability.graylog
        with socket.create_connection(
            (cfg.host, cfg.port), timeout=self.settings.startup.timeout_seconds
        ):
            pass
        return f"conexao_tcp=ok host={cfg.host} port={cfg.port}"

    def check_all(
        self,
        *,
        strict: bool = True,
        probe_mlflow_write: bool | None = None,
        on_progress: Callable[[str, str, int, int, int], None] | None = None,
    ) -> HealthReport:
        start = time.monotonic()
        checks: list[CheckResult] = []
        definitions: list[tuple[str, bool, Callable[[], str]]] = [
            ("elasticsearch", True, self._elasticsearch),
            ("minio", True, self._minio),
            ("docling", True, self._docling),
            ("embeddings", True, self._embeddings),
            ("mlflow", self.settings.observability.mlflow.enabled, lambda: self._mlflow((strict if probe_mlflow_write is None else probe_mlflow_write) and self.settings.startup.check_mlflow_write)),
            ("graylog", self.settings.observability.graylog.enabled, self._graylog),
        ]
        enabled_total = sum(enabled for _, enabled, _ in definitions)
        logger.info("Verificação de dependências iniciada. Serviços ativos %d. ETA calculando", enabled_total)
        elapsed_success: list[float] = []
        completed = 0
        for name, enabled, callback in definitions:
            if not enabled:
                checks.append(CheckResult(name, True, "Serviço desativado no YAML", 0, enabled=False))
                logger.info("Serviço %s desativado no YAML", name)
                continue
            if on_progress is not None:
                on_progress("started", name, completed, enabled_total, 1)
            logger.info("Verificando %s. Progresso %d/%d. ETA %s", name, completed, enabled_total,
                        f"{sum(elapsed_success)/len(elapsed_success)*(enabled_total-completed):.1f}s" if elapsed_success else "calculando")
            service_started = time.monotonic()
            detail = ""
            ok = False
            attempts = 0
            for attempt in range(self.settings.startup.retries + 1):
                attempts = attempt + 1
                try:
                    detail = callback()
                    ok = True
                    break
                except Exception as exc:
                    detail = f"{type(exc).__name__} {str(exc)[:300]}"
                    non_retryable = (
                        (name == "minio" and any(tag in detail.lower() for tag in (
                            "invalidaccesskeyid", "signaturedoesnotmatch", "accessdenied", "nosuchbucket"
                        )))
                        or (isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {401, 403})
                    )
                    if non_retryable:
                        logger.warning("Falha permanente em %s. Não serão realizadas novas tentativas. %s", name, detail)
                        break
                    if attempt < self.settings.startup.retries:
                        if on_progress is not None:
                            on_progress("retry", name, completed, enabled_total, attempts + 1)
                        logger.warning("Falha em %s. Tentativa %d/%d. %s. Nova tentativa em %.1fs", name,
                                       attempts, self.settings.startup.retries + 1, detail,
                                       self.settings.startup.retry_interval_seconds)
                        time.sleep(self.settings.startup.retry_interval_seconds)
            elapsed = time.monotonic() - service_started
            checks.append(CheckResult(name, ok, detail, elapsed, attempts))
            completed += 1
            if on_progress is not None:
                on_progress("finished", name, completed, enabled_total, attempts)
            if ok:
                elapsed_success.append(elapsed)
            remaining = enabled_total - completed
            eta = sum(elapsed_success) / len(elapsed_success) * remaining if elapsed_success else None
            message = (f"Serviço {name} {'OK' if ok else 'FALHOU'}. {detail}. "
                       f"Duração {elapsed:.2f}s. Progresso {completed}/{enabled_total}. "
                       f"ETA {f'{eta:.1f}s' if eta is not None else 'indisponível'}")
            if ok:
                logger.info(message)
            else:
                logger.error(message)
        report = HealthReport(checks, time.monotonic() - start)
        logger.info("Verificação concluída. Disponíveis %d/%d. Duração %.2fs ETA 0s",
                    sum(c.ok for c in checks if c.enabled), enabled_total, report.duration_seconds)
        if strict and not report.ok:
            failures = "; ".join(f"{c.name} {c.detail}" for c in checks if c.enabled and not c.ok)
            raise StartupHealthError(f"Inicialização interrompida por dependências indisponíveis. {failures}")
        return report

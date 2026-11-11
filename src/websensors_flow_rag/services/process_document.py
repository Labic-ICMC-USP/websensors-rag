from __future__ import annotations

import hashlib
import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from minio.error import S3Error

from websensors_flow.config import StepDefinition
from websensors_flow.api import JobStatusObserver, JobStore
from websensors_flow.runner import run_configured_flow
from websensors_flow_rag.clients.minio_client import MinIOClient
from websensors_flow_rag.config import RAGSettings
from websensors_flow_rag.models import DoclingArtifacts, IndexDocumentRequest
from websensors_flow_rag.utils import detect_mime_type, docling_options_hash, sha256_bytes, stable_document_id


logger = logging.getLogger("websensors_flow_rag.processing")


class ProcessDocumentService:
    """Upload Bronze e execução do mesmo Flow para API, CLI e adaptadores."""

    def __init__(self, settings: RAGSettings):
        self.settings = settings
        self.store = JobStore(event_history_limit=settings.api.event_history_limit)
        self.executor = ThreadPoolExecutor(max_workers=settings.api.indexing_workers, thread_name_prefix="websensors-rag")
        self._locks = [Lock() for _ in range(256)]
        self._conversion_lock = Lock()

    def close(self, *, wait: bool = True) -> None:
        self.executor.shutdown(wait=wait, cancel_futures=False)

    def prepare_upload(
        self, *, filename: str, content: bytes, project: str,
        metadata: dict[str, Any] | None = None, document_id: str | None = None,
        document_type: str | None = None, artifacts: DoclingArtifacts | None = None,
        force: bool = False, require_cached_artifacts: bool = False,
    ) -> IndexDocumentRequest:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", project):
            raise ValueError("Projeto deve usar letras minúsculas, números, hífen ou sublinhado (1–64 caracteres).")
        filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
        if not filename or filename in {".", ".."} or len(filename) > 255 or any(ord(c) < 32 for c in filename):
            raise ValueError("Nome de arquivo inválido.")
        if not content:
            raise ValueError("Arquivo vazio.")
        if len(content) > self.settings.api.max_upload_bytes:
            raise ValueError("Arquivo excede o limite de upload configurado.")
        if document_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", document_id):
            raise ValueError("Identificador de documento inválido.")
        if document_type is not None and not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", document_type):
            raise ValueError("Tipo documental inválido.")
        digest = sha256_bytes(content)
        if artifacts is not None:
            if artifacts.source_sha256 != digest or artifacts.options_sha256 != docling_options_hash(self.settings):
                raise ValueError("Artefatos Docling não correspondem ao original ou às opções configuradas.")
        # Identidade estável no projeto, com fonte imutável por hash.
        identity = document_id or filename
        normalized_id = hashlib.sha256(f"{project}:{identity}".encode()).hexdigest()[:32]
        key = f"projetos/{project}/documentos/{normalized_id}/{digest}/{filename}"
        values = dict(metadata or {})
        values["project"] = project
        if document_type is not None:
            values["declared_document_type"] = document_type
        request = IndexDocumentRequest(
            key=key, document_id=normalized_id, metadata=values, force=force,
            project=project, document_type=document_type, docling_artifacts=artifacts,
        )
        # Não criar execução ou chamar o Flow antes de concluir o upload.
        client = MinIOClient(self.settings.services.minio)
        client.put_bytes(self.settings.services.minio.bronze_bucket, key, content, detect_mime_type(filename))
        if request.docling_artifacts is None:
            request.docling_artifacts = self._cached_artifacts(client, request.document_id, digest)
        if require_cached_artifacts and request.docling_artifacts is None:
            raise ArtifactsUnavailable("Artefatos Docling indisponíveis. Use o extrator externo RAG no upload ou forneça Markdown e JSON estruturais com proveniência.")
        return request

    def _cache_key(self, document_id: str, digest: str) -> str:
        prefix = self.settings.services.minio.silver_prefix.strip("/")
        return f"{prefix}/{document_id}/conversions/{digest}/{docling_options_hash(self.settings)}/artifacts.json"

    def _cached_artifacts(self, client, document_id: str, digest: str) -> DoclingArtifacts | None:
        try:
            data = client.get_bytes(self.settings.services.minio.silver_bucket, self._cache_key(document_id, digest))
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                return None
            raise
        artifacts = DoclingArtifacts.model_validate_json(data)
        if artifacts.source_sha256 != digest or artifacts.options_sha256 != docling_options_hash(self.settings):
            raise ValueError("Cache Docling incompatível com fonte ou opções.")
        return artifacts

    def convert_for_openwebui(self, *, filename: str, content: bytes, project: str) -> dict[str, Any]:
        # Serializa apenas as conversões desta instância, sem alterar o Docling compartilhado.
        with self._conversion_lock:
            request = self.prepare_upload(filename=filename, content=content, project=project)
            settings = self.settings.to_flow_settings()
            settings.steps = [
                StepDefinition(name="resolver_fonte", class_path="websensors_flow_rag.indexing.steps.ResolveSourceStep"),
                StepDefinition(name="identificar_artefatos", class_path="websensors_flow_rag.indexing.steps.PrepareConversionRevisionStep"),
                StepDefinition(name="converter_docling", class_path="websensors_flow_rag.indexing.steps.ConvertDoclingStep"),
                StepDefinition(name="armazenar_silver", class_path="websensors_flow_rag.indexing.steps.StoreSilverStep"),
            ]
            result = run_configured_flow(settings, input=request, run_id=uuid.uuid4().hex)
            if result.report.status != "success":
                raise RuntimeError("Conversão Docling falhou; consulte o relatório da execução.")
            work = result.output
            artifacts = DoclingArtifacts(
                source_sha256=work.source_sha256, options_sha256=docling_options_hash(self.settings),
                markdown=work.markdown, structural_json=work.docling_json,
            )
            client = MinIOClient(self.settings.services.minio)
            client.put_text(
                self.settings.services.minio.silver_bucket,
                self._cache_key(work.document_id, work.source_sha256),
                artifacts.model_dump_json(), "application/json; charset=utf-8",
            )
            return {"page_content": work.markdown, "metadata": {
                "source": work.filename, "source_sha256": work.source_sha256,
                "rag_document_id": work.document_id, "rag_project": project,
                "docling_options_sha256": artifacts.options_sha256,
            }}

    def run(self, request: IndexDocumentRequest, *, run_id: str | None = None, observers=None):
        bucket = request.bucket or self.settings.services.minio.bronze_bucket
        document_id = request.document_id or stable_document_id(bucket, request.key)
        lock_id = int(hashlib.sha256(document_id.encode()).hexdigest()[:8], 16) % len(self._locks)
        with self._locks[lock_id]:
            result = run_configured_flow(
                self.settings.to_flow_settings(), input=request, run_id=run_id,
                extra_observers=observers,
            )
        if request.project and result.report.status == "success" and isinstance(result.output, dict):
            result.output.setdefault("project", request.project)
            result.output.setdefault("filename", request.key.rsplit("/", 1)[-1])
            result.output.setdefault("classification", None)
            result.output.setdefault("extraction", None)
            if self.settings.extraction.enabled:
                result.output.setdefault("warnings", list((result.output.get("extraction") or {}).get("warnings", [])))
            else:
                result.output.setdefault("warnings", ["Extração semântica desabilitada nesta configuração."] if self.settings.classification.enabled else ["Classificação e extração semântica desabilitadas nesta configuração."])
        return result

    def process_file(self, **kwargs):
        request = self.prepare_upload(**kwargs)
        return self.run(request, run_id=uuid.uuid4().hex)

    def submit(self, request: IndexDocumentRequest) -> str:
        token = uuid.uuid4().hex
        self.store.create(
            token, payload=request.model_dump(mode="json", exclude={"docling_artifacts"}),
            steps_total=len(self.settings.to_flow_settings().steps),
        )
        try:
            self.executor.submit(self._execute_job, token, request)
        except Exception:
            self.store.update(token, status="failed", failure={"error_type": "SubmissionError", "error_message": "Não foi possível iniciar o processamento."})
            raise
        return token

    def _execute_job(self, token: str, request: IndexDocumentRequest) -> None:
        self.store.update(token, status="running", started_at=datetime.now(timezone.utc).isoformat())
        try:
            result = self.run(request, run_id=token, observers=[JobStatusObserver(self.store, token)])
            update = {"status": result.report.status, "report": result.report.model_dump(mode="json"), "finished_at": datetime.now(timezone.utc).isoformat()}
            if result.failure is not None:
                update["failure"] = result.failure.model_dump(mode="json")
            if result.report.status == "success" and isinstance(result.output, dict):
                update["output"] = result.output
            self.store.update(token, **update)
        except Exception as exc:
            logger.error("Falha inesperada no processamento %s: %s", token, type(exc).__name__)
            self.store.update(token, status="failed", finished_at=datetime.now(timezone.utc).isoformat(), failure={"error_type": type(exc).__name__, "error_message": "Falha no processamento. Consulte os logs da execução."})


class ArtifactsUnavailable(ValueError):
    """Impedir reconversão silenciosa de anexos já convertidos pela interface."""

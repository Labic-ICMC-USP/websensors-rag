from __future__ import annotations

import hashlib
import logging
from time import perf_counter
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from threading import Lock
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from websensors_flow.api import JobStatusObserver, JobStore
from websensors_flow.runner import run_configured_flow
from websensors_flow_rag.clients.docling_client import DoclingClient
from websensors_flow_rag.clients.elasticsearch_client import ElasticsearchClient
from websensors_flow_rag.clients.minio_client import MinIOClient
from websensors_flow_rag.clients.model_client import EmbeddingClient
from websensors_flow_rag.healthchecks import HealthChecker, StartupHealthError
from websensors_flow_rag.config import RAGSettings
from websensors_flow_rag.models import (
    HealthResponse,
    IndexDocumentRequest,
    IndexStartResponse,
    RunStatusResponse,
    SearchRequest,
    SearchResponse,
    ServiceDescriptor,
)
from websensors_flow_rag.telemetry import record_search
from websensors_flow_rag.search.service import SearchService
from websensors_flow_rag.utils import public_service_metadata, stable_document_id

logger = logging.getLogger("websensors_flow_rag")


def _status_message(job: dict[str, Any]) -> str:
    status_value = job["status"]
    if status_value == "queued":
        return "Indexação aguardando execução."
    if status_value == "running":
        current = job.get("pipeline", {}).get("current_step")
        return f"Indexação em execução na etapa {current}." if current else "Indexação em execução."
    if status_value == "success":
        return "Indexação concluída com sucesso."
    return "Indexação encerrada com falha."


def _project_status(job: dict[str, Any]) -> dict[str, Any]:
    failure = job.get("failure")
    error = None
    if failure:
        error = {
            "error_type": failure.get("error_type"),
            "error_message": failure.get("error_message"),
            "step_name": failure.get("step_name"),
            "suggestion": failure.get("suggestion") or "Consulte os logs e o relatório da execução.",
        }
    progress = dict(job.get("pipeline") or {})
    if job.get("progress"):
        progress["loop"] = dict(job["progress"])
    return {
        "token": job["token"],
        "status": job["status"],
        "terminal": job["status"] in {"success", "failed"},
        "message": _status_message(job),
        "created_at": job["created_at"],
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "updated_at": job["updated_at"],
        "progress": progress,
        "trace_id": job.get("trace_id"),
        "models": job.get("models") or [],
        "result": job.get("output") if job["status"] == "success" else None,
        "error": error if job["status"] == "failed" else None,
    }


def create_rag_app(settings: RAGSettings, *, startup_prepared: bool = False) -> FastAPI:
    store = JobStore(event_history_limit=settings.api.event_history_limit)
    executor = ThreadPoolExecutor(max_workers=settings.api.indexing_workers, thread_name_prefix="websensors-rag")
    document_locks = [Lock() for _ in range(256)]
    flow_settings = settings.to_flow_settings()
    steps_total = len(flow_settings.steps)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            if not startup_prepared and settings.startup.enabled:
                HealthChecker(settings).check_all(strict=True)
            if not startup_prepared:
                logger.info("Preparando índices e aliases no Elasticsearch. ETA calculando")
                started = perf_counter()
                es = ElasticsearchClient(settings.services.elasticsearch, settings.services.embeddings.dimensions)
                try:
                    es.ensure_indices()
                finally:
                    es.close()
                logger.info("Índices e aliases validados em %.2fs. ETA 0s", perf_counter() - started)
            logger.info("API disponível. Rotas /docs, /openapi.json e /health")
            yield
        finally:
            executor.shutdown(wait=False, cancel_futures=False)

    app = FastAPI(
        title=settings.api.title,
        description=settings.api.description,
        version=settings.project.version,
        lifespan=lifespan,
        openapi_tags=[
            {"name": "servico", "description": "Descrição e saúde do serviço."},
            {"name": "indexacao", "description": "Indexação e atualização de documentos."},
            {"name": "busca", "description": "Recuperação lexical e semântica no Elasticsearch com busca híbrida por fusão RRF na aplicação."},
            {"name": "documentos", "description": "Consulta dos documentos indexados."},
        ],
    )

    if settings.api.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.api.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.state.job_store = store
    app.state.executor = executor
    app.state.rag_settings = settings

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        if not settings.api.auth.enabled:
            return
        expected = f"Bearer {settings.api.auth.token}"
        if authorization != expected:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de acesso inválido.")

    def execute_indexing(token: str, request: IndexDocumentRequest) -> None:
        bucket = request.bucket or settings.services.minio.bronze_bucket
        document_id = request.document_id or stable_document_id(bucket, request.key)
        lock_index = int(hashlib.sha256(document_id.encode("utf-8")).hexdigest()[:8], 16) % len(document_locks)
        with document_locks[lock_index]:
            logger.info("Indexação iniciada. Token %s Documento %s Objeto %s/%s ETA calculando", token, document_id, bucket, request.key)
            started = perf_counter()
            store.update(token, status="running", started_at=datetime.now(timezone.utc).isoformat())
            observer = JobStatusObserver(store, token)
            try:
                result = run_configured_flow(
                    flow_settings,
                    input=request,
                    run_id=token,
                    extra_observers=[observer],
                )
                update: dict[str, Any] = {
                    "status": result.report.status,
                    "report": result.report.model_dump(mode="json"),
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                }
                if result.failure is not None:
                    update["failure"] = result.failure.model_dump(mode="json")
                if result.report.status == "success" and isinstance(result.output, dict):
                    update["output"] = result.output
                store.update(token, **update)
                logger.info("Indexação finalizada. Token %s Estado %s Duração %.2fs ETA 0s", token, result.report.status, perf_counter() - started)
            except Exception as exc:
                logger.error("Erro na indexação. Token %s Documento %s Tipo %s Motivo %s Duração %.2fs", token, document_id, type(exc).__name__, str(exc), perf_counter() - started)
                store.update(
                    token,
                    status="failed",
                    finished_at=datetime.now(timezone.utc).isoformat(),
                    failure={
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "suggestion": "Consulte os logs e o relatório da execução.",
                    },
                )

    @app.get(
        "/rag",
        tags=["servico"],
        operation_id="descrever_servico_rag",
        response_model=ServiceDescriptor,
        summary="Descrever o serviço RAG",
    )
    def describe(_: None = Depends(require_auth)) -> dict[str, Any]:
        return {
            "name": settings.project.name,
            "description": settings.project.description,
            "environment": settings.environment.name,
            "operations": {
                "indexacao": "indexar_documento",
                "status_indexacao": "consultar_indexacao",
                "bm25": "buscar_bm25",
                "semantica": "buscar_semantica",
                "hibrida": "buscar_hibrida",
            },
            "indexing": {
                "docling_centralizado": True,
                "saida": ["markdown", "json"],
                "chunking": settings.indexing.chunking.model_dump(mode="json"),
            },
            "search": {
                "default_top_k": settings.search.default_top_k,
                "services": public_service_metadata(settings),
            },
        }

    @app.get(
        "/health",
        tags=["servico"],
        operation_id="verificar_saude",
        response_model=HealthResponse,
        summary="Verificar saúde do serviço",
        include_in_schema=True,
    )
    def health(_: None = Depends(require_auth)) -> dict[str, Any]:
        report = HealthChecker(settings).check_all(strict=False)
        payload = {
            "status": "ok" if report.ok else "degraded",
            "service": settings.project.name,
            "dependencies": {check.name: ("desativado" if not check.enabled else ("ok" if check.ok else "indisponivel")) for check in report.checks},
            "details": [check.as_dict() for check in report.checks],
            "openapi": "/openapi.json",
        }
        return payload if report.ok else JSONResponse(status_code=503, content=payload)

    @app.post(
        "/documents/index",
        tags=["indexacao"],
        operation_id="indexar_documento",
        response_model=IndexStartResponse,
        status_code=202,
        summary="Indexar ou atualizar um documento",
        description="Inicia a indexação assíncrona de um objeto existente no MinIO.",
    )
    def index_document(request: IndexDocumentRequest, _: None = Depends(require_auth)) -> dict[str, Any]:
        bucket = request.bucket or settings.services.minio.bronze_bucket
        document_id = request.document_id or stable_document_id(bucket, request.key)
        token = uuid.uuid4().hex
        store.create(token, payload=request.model_dump(mode="json"), steps_total=steps_total)
        executor.submit(execute_indexing, token, request)
        return {
            "token": token,
            "status": "queued",
            "terminal": False,
            "document_id": document_id,
            "message": "Documento aceito para indexação.",
            "status_url": f"/indexing/{token}",
        }

    @app.get(
        "/indexing/{token}",
        tags=["indexacao"],
        operation_id="consultar_indexacao",
        response_model=RunStatusResponse,
        summary="Consultar uma indexação",
    )
    def get_indexing(token: str, _: None = Depends(require_auth)) -> dict[str, Any]:
        job = store.get(token)
        if job is None:
            raise HTTPException(status_code=404, detail="Token de indexação não encontrado.")
        return _project_status(job)

    def perform_search(mode: str, request: SearchRequest) -> SearchResponse:
        service = SearchService(settings)
        started = perf_counter()
        logger.info("Busca iniciada. Modo %s Top K %s Filtros %s ETA indisponível para consulta pontual", mode, request.top_k or settings.search.default_top_k, len(request.filters))
        try:
            if mode == "bm25":
                response = service.bm25(request)
            elif mode == "semantic":
                response = service.semantic(request)
            elif mode == "hybrid":
                response = service.hybrid(request)
            else:
                raise ValueError(f"Modo de busca não suportado: {mode}")
            elapsed = perf_counter() - started
            logger.info("Busca concluída. Modo %s Resultados %s Duração %.3fs", mode, response.count, elapsed)
            record_search(settings, mode, response.count, elapsed)
            return response
        except ValueError as exc:
            logger.warning("Busca inválida. Modo %s Detalhes %s", mode, exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            logger.error("Dependência da busca retornou erro HTTP. Modo %s Código %s", mode, exc.response.status_code)
            detail = exc.response.text[:2000] if exc.response is not None else str(exc)
            raise HTTPException(status_code=502, detail=f"Falha em dependência de busca: {detail}") from exc
        except httpx.RequestError as exc:
            logger.error("Conexão indisponível durante a busca. Modo %s Erro %s", mode, exc)
            raise HTTPException(status_code=502, detail=f"Falha de conexão com dependência de busca: {exc}") from exc
        except Exception as exc:
            logger.error("Erro inesperado na busca. Modo %s Tipo %s Motivo %s", mode, type(exc).__name__, str(exc))
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post(
        "/search/bm25",
        tags=["busca"],
        operation_id="buscar_bm25",
        response_model=SearchResponse,
        summary="Executar busca BM25",
    )
    def search_bm25(request: SearchRequest, _: None = Depends(require_auth)) -> SearchResponse:
        return perform_search("bm25", request)

    @app.post(
        "/search/semantic",
        tags=["busca"],
        operation_id="buscar_semantica",
        response_model=SearchResponse,
        summary="Executar busca semântica",
    )
    def search_semantic(request: SearchRequest, _: None = Depends(require_auth)) -> SearchResponse:
        return perform_search("semantic", request)

    @app.post(
        "/search/hybrid",
        tags=["busca"],
        operation_id="buscar_hibrida",
        response_model=SearchResponse,
        summary="Executar busca híbrida",
    )
    def search_hybrid(request: SearchRequest, _: None = Depends(require_auth)) -> SearchResponse:
        return perform_search("hybrid", request)


    @app.get(
        "/documents",
        tags=["documentos"],
        operation_id="listar_documentos",
        summary="Listar documentos indexados",
    )
    def list_documents(limit: int = Query(default=50, ge=1, le=200), _: None = Depends(require_auth)) -> dict[str, Any]:
        es = ElasticsearchClient(settings.services.elasticsearch, settings.services.embeddings.dimensions)
        try:
            documents = es.list_documents(limit)
        finally:
            es.close()
        return {"count": len(documents), "documents": documents}

    @app.get(
        "/documents/{document_id}",
        tags=["documentos"],
        operation_id="obter_documento",
        summary="Obter documento indexado",
    )
    def get_document(document_id: str, _: None = Depends(require_auth)) -> dict[str, Any]:
        es = ElasticsearchClient(settings.services.elasticsearch, settings.services.embeddings.dimensions)
        try:
            document = es.get_document(document_id)
        finally:
            es.close()
        if document is None:
            raise HTTPException(status_code=404, detail="Documento não encontrado.")
        return document

    return app

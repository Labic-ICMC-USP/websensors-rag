from __future__ import annotations

import argparse
import json
import logging
import sys
from time import perf_counter

from websensors_flow.runner import run_configured_flow
from websensors_flow_rag.api import create_rag_app
from websensors_flow_rag.clients.elasticsearch_client import ElasticsearchClient
from websensors_flow_rag.config import RAGSettings, load_rag_settings
from websensors_flow_rag.models import IndexDocumentRequest
from websensors_flow_rag.startup_report import render_startup_error, run_health_preflight

logger = logging.getLogger("websensors_flow_rag.cli")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        force=True,
    )
    # Os eventos de alto nível são registrados pelo RAG. As requisições
    # individuais do cliente HTTP só são necessárias no modo de depuração.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _load_settings(path: str) -> RAGSettings:
    try:
        return load_rag_settings(path)
    except Exception as exc:
        render_startup_error(f"Não foi possível ler a configuração {path}\n{type(exc).__name__}  {exc}", stage="YAML global")
        raise SystemExit(2) from None


def _require_health(settings: RAGSettings) -> None:
    try:
        report = run_health_preflight(settings)
    except Exception as exc:
        render_startup_error(f"Falha inesperada no diagnóstico\n{type(exc).__name__}  {exc}")
        raise SystemExit(2) from None
    if not report.ok:
        raise SystemExit(1)


def _prepare_elasticsearch(settings: RAGSettings) -> None:
    logger.info("Preparação dos índices Elasticsearch iniciada. ETA calculando")
    started = perf_counter()
    client = None
    try:
        client = ElasticsearchClient(settings.services.elasticsearch, settings.services.embeddings.dimensions)
        client.ensure_indices()
    except Exception as exc:
        render_startup_error(
            f"O Elasticsearch não concluiu a preparação dos índices ou aliases.\n"
            f"{type(exc).__name__}  {exc}\n"
            "Verifique /_cluster/health, /_cat/shards e /_cluster/pending_tasks.",
            stage="Preparação dos índices",
        )
        raise SystemExit(1) from None
    finally:
        if client is not None:
            client.close()
    logger.info("Índices e aliases validados. Duração %.2fs. ETA 0s", perf_counter() - started)


def main_api() -> None:
    parser = argparse.ArgumentParser(description="Servidor WebSensors Flow RAG")
    parser.add_argument("--config", required=True, help="Caminho do YAML global")
    args = parser.parse_args()
    configure_logging()
    settings = _load_settings(args.config)
    if settings.startup.enabled:
        _require_health(settings)
    _prepare_elasticsearch(settings)

    import uvicorn

    # O diagnóstico e a criação dos índices já foram concluídos antes
    # da inicialização do ASGI. Isso evita verificações duplicadas e
    # traceback de dependências indisponíveis no servidor HTTP.
    try:
        uvicorn.run(
            create_rag_app(settings, startup_prepared=True),
            host=settings.api.host,
            port=settings.api.port,
            workers=1,
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        render_startup_error(f"Não foi possível iniciar o servidor HTTP.\n{type(exc).__name__}  {exc}")
        raise SystemExit(1) from None


def main_index() -> None:
    parser = argparse.ArgumentParser(description="Indexação direta com WebSensors Flow RAG")
    parser.add_argument("--config", required=True, help="Caminho do YAML global")
    parser.add_argument("--key", required=True, help="Chave do objeto no MinIO")
    parser.add_argument("--bucket", default=None, help="Bucket de origem")
    parser.add_argument("--document-id", default=None, help="Identificador do documento")
    parser.add_argument("--metadata", default=None, help="Metadados em JSON")
    parser.add_argument("--force", action="store_true", help="Força nova indexação")
    args = parser.parse_args()

    configure_logging()
    settings = _load_settings(args.config)
    if settings.startup.enabled:
        _require_health(settings)
    _prepare_elasticsearch(settings)

    request_data = {
        "bucket": args.bucket,
        "key": args.key,
        "document_id": args.document_id,
        "force": args.force,
    }
    if args.metadata is not None:
        try:
            request_data["metadata"] = json.loads(args.metadata)
        except ValueError as exc:
            render_startup_error(f"Metadados JSON inválidos.\n{exc}", stage="Indexação")
            raise SystemExit(2) from None
    request = IndexDocumentRequest.model_validate(request_data)
    result = run_configured_flow(settings.to_flow_settings(), input=request)
    if result.report.status == "success":
        print(json.dumps(result.output, ensure_ascii=False, indent=2))
        return
    if result.failure is not None:
        print(json.dumps(result.failure.model_dump(mode="json"), ensure_ascii=False, indent=2))
    raise SystemExit(1)


def main_health() -> None:
    parser = argparse.ArgumentParser(description="Diagnóstico dos serviços do WebSensors Flow RAG")
    parser.add_argument("--config", required=True, help="Caminho do YAML global")
    args = parser.parse_args()
    configure_logging()
    _require_health(_load_settings(args.config))

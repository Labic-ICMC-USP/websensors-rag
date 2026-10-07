"""Testes de tempo limite e diagnóstico operacional."""

from pathlib import Path

import httpx

from websensors_flow_rag.clients.docling_client import DoclingClient
from websensors_flow_rag.clients.elasticsearch_client import ElasticsearchClient
from websensors_flow_rag.config import load_rag_settings

SETTINGS = Path(__file__).parents[1] / "config" / "rag.yaml"


def test_elasticsearch_creation_uses_dedicated_timeout():
    settings = load_rag_settings(SETTINGS)
    es = ElasticsearchClient(settings.services.elasticsearch, settings.services.embeddings.dimensions)
    calls = []

    def respond(request):
        calls.append(request)
        if request.method == "HEAD":
            return httpx.Response(404)
        return httpx.Response(200, json={"acknowledged": True, "shards_acknowledged": True})

    es.client.close()
    es.client = httpx.Client(base_url=settings.services.elasticsearch.endpoint, transport=httpx.MockTransport(respond))
    try:
        es._ensure_index("teste_rag", es._documents_definition())
    finally:
        es.close()
    assert len(calls) == 2
    assert calls[-1].method == "PUT"
    assert calls[-1].extensions["timeout"]["read"] == 180.0
    assert calls[-1].url.params["master_timeout"] == "170s"


def test_docling_emits_progress_without_inventing_eta():
    settings = load_rag_settings(SETTINGS)
    settings.services.docling.poll_interval_seconds = 0.001
    checks = []
    seen_status = []

    def respond(request):
        if request.method == "POST":
            return httpx.Response(200, json={"task_id": "abc"})
        if "/status/poll/" in request.url.path:
            checks.append(1)
            return httpx.Response(200, json={"task_status": "completed" if len(checks) > 1 else "running"})
        if "/result/" in request.url.path:
            return httpx.Response(200, json={"document": {"md_content": "# Documento", "json_content": {"pages": []}}})
        return httpx.Response(404)

    docling = DoclingClient(settings.services.docling)
    docling.client.close()
    docling.client = httpx.Client(transport=httpx.MockTransport(respond))
    try:
        result = docling.convert("teste.pdf", b"data", "application/pdf", seen_status.append)
    finally:
        docling.close()
    assert result["markdown"] == "# Documento"
    assert len(seen_status) == 2
    assert all(entry["eta_seconds"] is None for entry in seen_status)

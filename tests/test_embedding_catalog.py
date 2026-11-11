from pathlib import Path

import httpx

from websensors_flow_rag.clients.model_client import EmbeddingClient
from websensors_flow_rag.config import load_rag_settings
from websensors_flow_rag.healthchecks import HealthChecker


CONFIG = Path(__file__).parents[1] / "config" / "rag.yaml"


def test_embedding_client_uses_configured_catalog():
    settings = load_rag_settings(CONFIG).services.embeddings.model_copy(
        update={"endpoint": "https://example.test/api/v1", "models_path": "/embeddings/models"}
    )
    paths = []

    def respond(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"data": [{"id": settings.model}]})

    client = EmbeddingClient(settings)
    client.client.close()
    client.client = httpx.Client(transport=httpx.MockTransport(respond))
    try:
        assert client.ping()
        assert paths == ["/api/v1/embeddings/models"]
    finally:
        client.close()


def test_healthcheck_uses_embedding_catalog_and_checks_inference(monkeypatch):
    settings = load_rag_settings(CONFIG)
    settings.services.embeddings.endpoint = "https://example.test/api/v1"
    settings.services.embeddings.models_path = "/embeddings/models"
    settings.services.embeddings.model = "baai/bge-m3"
    paths = []

    def respond(request):
        paths.append(request.url.path)
        if request.method == "GET":
            assert request.url.path == "/api/v1/embeddings/models"
            return httpx.Response(200, json={"data": [{"id": "baai/bge-m3"}]})
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * 1024}]})

    client = EmbeddingClient(settings.services.embeddings)
    client.client.close()
    client.client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr("websensors_flow_rag.healthchecks.EmbeddingClient", lambda _: client)
    detail = HealthChecker(settings)._embeddings()
    assert "inferencia=ok" in detail
    assert paths == ["/api/v1/embeddings/models", "/api/v1/embeddings"]

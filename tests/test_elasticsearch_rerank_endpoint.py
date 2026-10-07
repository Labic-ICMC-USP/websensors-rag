from pathlib import Path

from websensors_flow_rag.clients.elasticsearch_client import ElasticsearchClient
from websensors_flow_rag.config import load_rag_settings


CONFIG = Path(__file__).parents[1] / "config" / "rag.yaml"


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(str(self.status_code))

    def json(self):
        return self._payload


class FakeHttpClient:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def get(self, path):
        return FakeResponse(self.status_code, self.payload)

    def close(self):
        pass


def _client(payload):
    settings = load_rag_settings(CONFIG)
    client = ElasticsearchClient(settings.services.elasticsearch, settings.services.embeddings.dimensions)
    client.client.close()
    client.client = FakeHttpClient(payload)
    return client


def test_accepts_only_elasticsearch_inference_service():
    client = _client(
        {
            "endpoints": [
                {
                    "inference_id": "websensors-rag-rerank",
                    "task_type": "rerank",
                    "service": "elasticsearch",
                    "service_settings": {"model_id": "modelo-local"},
                }
            ]
        }
    )
    assert client.inference_endpoint_available("websensors-rag-rerank") is True
    endpoint = client.require_elasticsearch_rerank_endpoint("websensors-rag-rerank")
    assert endpoint["service"] == "elasticsearch"


def test_rejects_external_inference_service():
    client = _client(
        {
            "endpoints": [
                {
                    "inference_id": "websensors-rag-rerank",
                    "task_type": "rerank",
                    "service": "cohere",
                    "service_settings": {},
                }
            ]
        }
    )
    assert client.inference_endpoint_available("websensors-rag-rerank") is False
    try:
        client.require_elasticsearch_rerank_endpoint("websensors-rag-rerank")
    except RuntimeError as exc:
        assert "service='cohere'" in str(exc)
    else:
        raise AssertionError("Endpoint externo deveria ser rejeitado")

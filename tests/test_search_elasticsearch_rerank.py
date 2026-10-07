from pathlib import Path

from websensors_flow_rag.config import load_rag_settings
from websensors_flow_rag.models import SearchRequest
from websensors_flow_rag.search.service import SearchService


CONFIG = Path(__file__).parents[1] / "config" / "rag.yaml"


class FakeElasticsearchClient:
    last_body = None

    def __init__(self, *args, **kwargs):
        pass

    def close(self):
        pass

    def search(self, body):
        FakeElasticsearchClient.last_body = body
        return {
            "took": 7,
            "hits": {
                "hits": [
                    {
                        "_id": "chunk-1",
                        "_score": 0.91,
                        "_source": {
                            "document_id": "doc-1",
                            "chunk_id": "chunk-1",
                            "revision_id": "rev-1",
                            "content": "conteudo relevante",
                            "active": True,
                        },
                    }
                ]
            },
        }


def test_config_has_only_elasticsearch_reranker():
    settings = load_rag_settings(CONFIG)
    assert not hasattr(settings.services, "reranker")
    assert settings.search.reranker.inference_id == "websensors-rag-rerank"
    assert settings.search.reranker.field == "content"


def test_hybrid_uses_elasticsearch_rrf(monkeypatch):
    settings = load_rag_settings(CONFIG)
    service = SearchService(settings)
    monkeypatch.setattr(service, "_embed_query", lambda _: [0.0] * settings.services.embeddings.dimensions)
    monkeypatch.setattr("websensors_flow_rag.search.service.ElasticsearchClient", FakeElasticsearchClient)

    response, _ = service.hybrid(SearchRequest(query="consulta", top_k=5, debug=True))

    body = FakeElasticsearchClient.last_body
    assert "rrf" in body["retriever"]
    assert len(body["retriever"]["rrf"]["retrievers"]) == 2
    assert response.debug["engine"] == "elasticsearch"


def test_hybrid_rerank_uses_text_similarity_reranker(monkeypatch):
    settings = load_rag_settings(CONFIG)
    service = SearchService(settings)
    monkeypatch.setattr(service, "_embed_query", lambda _: [0.0] * settings.services.embeddings.dimensions)
    monkeypatch.setattr("websensors_flow_rag.search.service.ElasticsearchClient", FakeElasticsearchClient)

    response = service.hybrid_rerank(SearchRequest(query="consulta", top_k=5, debug=True))

    body = FakeElasticsearchClient.last_body
    reranker = body["retriever"]["text_similarity_reranker"]
    assert reranker["inference_id"] == "websensors-rag-rerank"
    assert reranker["field"] == "content"
    assert "rrf" in reranker["retriever"]
    assert response.results[0].reranker_score == 0.91
    assert response.debug["reranker"] == "text_similarity_reranker"

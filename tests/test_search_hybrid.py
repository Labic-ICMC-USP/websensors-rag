from pathlib import Path

from websensors_flow_rag.config import load_rag_settings
from websensors_flow_rag.models import SearchRequest
from websensors_flow_rag.search.service import SearchService

CONFIG = Path(__file__).parents[1] / "config" / "rag.yaml"


class FakeElasticsearchClient:
    bodies = []

    def __init__(self, *args, **kwargs):
        pass

    def close(self):
        pass

    def search(self, body):
        type(self).bodies.append(body)
        if "query" in body:
            return {
                "took": 4,
                "hits": {
                    "hits": [
                        {"_id": "a", "_score": 8.0, "_source": {"document_id": "d1", "chunk_id": "a", "revision_id": "r1", "content": "A"}},
                        {"_id": "b", "_score": 7.0, "_source": {"document_id": "d2", "chunk_id": "b", "revision_id": "r1", "content": "B"}},
                    ]
                },
            }
        return {
            "took": 6,
            "hits": {
                "hits": [
                    {"_id": "b", "_score": 0.95, "_source": {"document_id": "d2", "chunk_id": "b", "revision_id": "r1", "content": "B"}},
                    {"_id": "c", "_score": 0.90, "_source": {"document_id": "d3", "chunk_id": "c", "revision_id": "r1", "content": "C"}},
                ]
            },
        }


def test_search_configuration_has_three_modes():
    settings = load_rag_settings(CONFIG)
    assert not hasattr(settings.search, "reranker")
    assert settings.search.hybrid.rank_window_size >= settings.search.default_top_k


def test_hybrid_executes_bm25_and_knn_then_fuses_in_application(monkeypatch):
    settings = load_rag_settings(CONFIG)
    service = SearchService(settings)
    monkeypatch.setattr(service, "_embed_query", lambda _: [0.0] * settings.services.embeddings.dimensions)
    FakeElasticsearchClient.bodies = []
    monkeypatch.setattr("websensors_flow_rag.search.service.ElasticsearchClient", FakeElasticsearchClient)

    response = service.hybrid(SearchRequest(query="consulta", top_k=5, debug=True))

    assert len(FakeElasticsearchClient.bodies) == 2
    assert "query" in FakeElasticsearchClient.bodies[0]
    assert "knn" in FakeElasticsearchClient.bodies[1]
    assert "retriever" not in FakeElasticsearchClient.bodies[0]
    assert "retriever" not in FakeElasticsearchClient.bodies[1]
    assert response.mode == "hybrid"
    assert response.debug["retrieval"] == "rrf"
    assert response.debug["fusion"] == "application"
    assert response.debug["components"] == ["bm25", "knn"]
    assert response.results[0].chunk_id == "b"


def test_rrf_rewards_documents_present_in_both_rankings():
    settings = load_rag_settings(CONFIG)
    service = SearchService(settings)
    lexical = [
        {"_id": "a", "_score": 10.0, "_source": {"chunk_id": "a"}},
        {"_id": "b", "_score": 9.0, "_source": {"chunk_id": "b"}},
    ]
    semantic = [
        {"_id": "b", "_score": 0.9, "_source": {"chunk_id": "b"}},
        {"_id": "c", "_score": 0.8, "_source": {"chunk_id": "c"}},
    ]

    fused = service._rrf_fuse(lexical, semantic)

    assert fused[0]["_id"] == "b"
    assert fused[0]["_score"] > fused[1]["_score"]

from pathlib import Path

import pytest

from websensors_flow_rag.clients.elasticsearch_client import ElasticsearchClient
from websensors_flow_rag.config import ChunkingSettings, load_rag_settings
from websensors_flow_rag.indexing.chunking import structural_chunks
from websensors_flow_rag.models import SearchRequest
from websensors_flow_rag.search.service import SearchService


CONFIG = Path(__file__).parents[1] / "config" / "rag.yaml"


class SimpleResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class SimpleHttpClient:
    def __init__(self, response):
        self.response = response

    def get(self, path):
        return self.response

    def close(self):
        pass


def test_elasticsearch_ping_rejects_unauthorized():
    settings = load_rag_settings(CONFIG)
    client = ElasticsearchClient(settings.services.elasticsearch, settings.services.embeddings.dimensions)
    client.client.close()
    client.client = SimpleHttpClient(SimpleResponse(status_code=401))
    assert client.ping() is False



def test_chunking_never_exceeds_max_tokens_and_preserves_heading_boundary():
    markdown = "# Documento\n\n## A\n\n" + ("alpha " * 420) + "\n\n## B\n\n" + ("beta " * 420)
    settings = ChunkingSettings(target_tokens=120, max_tokens=160, overlap_tokens=30, min_chunk_tokens=10)
    _, chunks = structural_chunks(markdown, settings)
    assert chunks
    assert all(chunk["estimated_tokens"] <= 160 for chunk in chunks)
    assert all(chunk["heading_path"] in [["Documento", "A"], ["Documento", "B"]] for chunk in chunks)
    assert all(chunk["heading_text"] in {"Documento > A", "Documento > B"} for chunk in chunks)


def test_top_k_above_configured_limit_is_rejected():
    settings = load_rag_settings(CONFIG)
    service = SearchService(settings)
    with pytest.raises(ValueError, match="max_top_k"):
        service._top_k(SearchRequest(query="teste", top_k=settings.search.max_top_k + 1))


def test_empty_filter_list_generates_match_none():
    settings = load_rag_settings(CONFIG)
    service = SearchService(settings)
    filters = service._filters(SearchRequest(query="teste", filters={"empresa": []}))
    assert {"match_none": {}} in filters


def test_hybrid_knn_num_candidates_is_never_smaller_than_k():
    settings = load_rag_settings(CONFIG)
    changed = settings.model_copy(deep=True)
    changed.search.semantic.candidates = 300
    changed.search.semantic.num_candidates = 100
    service = SearchService(changed)
    body = service._semantic_body(SearchRequest(query="teste"), [0.0], 50)
    knn = body["knn"]
    assert knn["num_candidates"] >= knn["k"]



def test_rag_config_has_no_direct_vlm_service():
    settings = load_rag_settings(CONFIG)
    assert not hasattr(settings.services, "vlm")
    assert settings.services.docling.options["picture_description_preset"] == "labic_vision"


def test_pipeline_hash_ignores_release_version_but_tracks_processing_version():
    from websensors_flow_rag.utils import pipeline_hash

    settings = load_rag_settings(CONFIG)
    release_changed = settings.model_copy(deep=True)
    release_changed.project.version = "99.0.0"
    assert pipeline_hash(release_changed) == pipeline_hash(settings)

    processing_changed = settings.model_copy(deep=True)
    processing_changed.indexing.processing_version = "2"
    assert pipeline_hash(processing_changed) != pipeline_hash(settings)


def test_search_query_rejects_only_whitespace():
    with pytest.raises(Exception):
        SearchRequest(query="   ")


def test_search_filters_reject_nested_objects():
    with pytest.raises(Exception):
        SearchRequest(query="teste", filters={"empresa": {"nome": "ROMI"}})


def test_known_structural_filters_do_not_fall_back_to_metadata():
    settings = load_rag_settings(CONFIG)
    service = SearchService(settings)
    assert service._filter_field("type") == "type"
    assert service._filter_field("heading_path") == "heading_path"
    assert service._filter_field("page_start") == "page_start"
    assert service._filter_field("page_end") == "page_end"

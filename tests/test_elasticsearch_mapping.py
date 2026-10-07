from pathlib import Path

from websensors_flow_rag.clients.elasticsearch_client import ElasticsearchClient
from websensors_flow_rag.config import load_rag_settings


CONFIG = Path(__file__).parents[1] / "config" / "rag.yaml"


def test_chunk_mapping_uses_configured_dimensions():
    settings = load_rag_settings(CONFIG)
    client = ElasticsearchClient(settings.services.elasticsearch, 1024)
    try:
        mapping = client._chunks_definition()
        embedding = mapping["mappings"]["properties"]["embedding"]
        assert embedding["dims"] == 1024
        assert embedding["similarity"] == "cosine"
        assert mapping["mappings"]["properties"]["metadata"]["type"] == "flattened"
    finally:
        client.close()

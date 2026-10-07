from pathlib import Path

from websensors_flow_rag.api import create_rag_app
from websensors_flow_rag.config import load_rag_settings


CONFIG = Path(__file__).parents[1] / "config" / "rag.yaml"


def test_openapi_exposes_search_and_index_operations():
    settings = load_rag_settings(CONFIG)
    app = create_rag_app(settings)
    schema = app.openapi()
    operation_ids = {
        operation["operationId"]
        for path in schema["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict) and "operationId" in operation
    }
    assert "indexar_documento" in operation_ids
    assert "consultar_indexacao" in operation_ids
    assert "buscar_bm25" in operation_ids
    assert "buscar_semantica" in operation_ids
    assert "buscar_hibrida" in operation_ids
    assert "buscar_hibrida_com_rerank" not in operation_ids

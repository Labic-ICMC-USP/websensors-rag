from pathlib import Path

from websensors_flow_rag.config import load_rag_settings
from websensors_flow_rag.utils import pipeline_hash


CONFIG = Path(__file__).parents[1] / "config" / "rag.yaml"


def test_load_global_yaml():
    settings = load_rag_settings(CONFIG)
    assert settings.project.name == "websensors-flow-rag"
    assert settings.services.docling.options["do_picture_description"] is True
    assert settings.services.elasticsearch.aliases.chunks == "websensors-rag-chunks"


def test_pipeline_hash_changes_with_chunking():
    settings = load_rag_settings(CONFIG)
    original = pipeline_hash(settings)
    changed = settings.model_copy(deep=True)
    changed.indexing.chunking.target_tokens += 1
    assert pipeline_hash(changed) != original


def test_flow_has_expected_steps():
    settings = load_rag_settings(CONFIG)
    flow = settings.to_flow_settings()
    assert [step.name for step in flow.steps] == [
        "resolver_fonte",
        "detectar_alteracoes",
        "converter_docling",
        "armazenar_silver",
        "segmentar_documento",
        "gerar_embeddings",
        "preparar_revisao_elasticsearch",
        "validar_revisao",
        "publicar_revisao",
    ]
    assert flow.pipeline.params == {"servico": "rag"}

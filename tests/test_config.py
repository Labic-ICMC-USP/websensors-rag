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


def _environment_config(tmp_path):
    import yaml
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    raw = yaml.safe_load(CONFIG.read_text())
    raw["services"]["embeddings"]["api_key"] = "${RAG_TEST_API_KEY}"
    path = config_dir / "rag.yaml"
    path.write_text(yaml.safe_dump(raw))
    return path


def test_api_key_from_project_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("RAG_TEST_API_KEY", raising=False)
    path = _environment_config(tmp_path)
    (tmp_path / ".env").write_text("RAG_TEST_API_KEY=test-file-secret\n")
    settings = load_rag_settings(path)
    assert settings.services.embeddings.api_key == "test-file-secret"
    assert "RAG_TEST_API_KEY" not in __import__("os").environ


def test_process_environment_overrides_dotenv(tmp_path, monkeypatch):
    path = _environment_config(tmp_path)
    (tmp_path / ".env").write_text("RAG_TEST_API_KEY=test-file-secret\n")
    monkeypatch.setenv("RAG_TEST_API_KEY", "test-process-secret")
    assert load_rag_settings(path).services.embeddings.api_key == "test-process-secret"


def test_missing_environment_key_fails_before_client_creation(tmp_path, monkeypatch):
    import pytest
    from websensors_flow.exceptions import ConfigurationError
    monkeypatch.delenv("RAG_TEST_API_KEY", raising=False)
    path = _environment_config(tmp_path)
    with pytest.raises(ConfigurationError, match="RAG_TEST_API_KEY"):
        load_rag_settings(path)

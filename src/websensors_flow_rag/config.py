from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from websensors_flow.config import (
    ApiConfig,
    AuthConfig,
    ConsoleConfig,
    EnvironmentConfig,
    FlowSettings,
    GraylogConfig,
    MLflowConfig,
    ObservabilityConfig,
    PipelineConfig,
    ProjectConfig,
    RuntimeConfig,
    StepDefinition,
)
from websensors_flow.exceptions import ConfigurationError


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectSettings(StrictModel):
    name: str = "websensors-flow-rag"
    version: str = "0.4.1"
    description: str = "Indexação e recuperação de documentos para RAG."


class EnvironmentSettings(StrictModel):
    name: str = "local"
    deployment_id: str | None = None
    owner: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class ConsoleSettings(StrictModel):
    enabled: bool = True
    progress: bool = True
    show_metrics: bool = True


class RuntimeSettings(StrictModel):
    report_dir: str = "./outputs/reports"
    include_traceback: bool = True
    raise_on_failure: bool = False
    console: ConsoleSettings = Field(default_factory=ConsoleSettings)


class AuthSettings(StrictModel):
    enabled: bool = False
    username: str | None = None
    password: str | None = None
    token: str | None = None

    @model_validator(mode="after")
    def validate_credentials(self) -> "AuthSettings":
        if self.enabled and not self.token and not (self.username and self.password):
            raise ValueError("Autenticação habilitada sem credenciais no YAML.")
        return self


class MLflowSettings(StrictModel):
    enabled: bool = False
    tracking_uri: str | None = None
    experiment_name: str | None = None
    run_name: str | None = None
    artifact_location: str | None = None
    http_request_timeout: int = 5
    connect_timeout_seconds: float = 3.0
    track_searches: bool = True
    auth: AuthSettings = Field(default_factory=AuthSettings)

    @model_validator(mode="after")
    def validate_enabled(self) -> "MLflowSettings":
        if self.enabled and (not self.tracking_uri or not self.experiment_name):
            raise ValueError("MLflow habilitado exige tracking_uri e experiment_name no YAML.")
        return self


class GraylogSettings(StrictModel):
    enabled: bool = False
    host: str | None = None
    port: int | None = None
    protocol: Literal["tcp"] = "tcp"
    facility: str = "websensors-flow-rag"
    level: str = "INFO"
    localname: str | None = None
    connect_timeout_seconds: float = 3.0
    auth: AuthSettings = Field(default_factory=AuthSettings)

    @model_validator(mode="after")
    def validate_enabled(self) -> "GraylogSettings":
        if self.enabled and (not self.host or not self.port):
            raise ValueError("Graylog habilitado exige host e port no YAML.")
        return self


class ObservabilitySettings(StrictModel):
    mlflow: MLflowSettings = Field(default_factory=MLflowSettings)
    graylog: GraylogSettings = Field(default_factory=GraylogSettings)


class MinIOSettings(StrictModel):
    endpoint: str
    access_key: str
    secret_key: str
    secure: bool = False
    region: str | None = None
    bronze_bucket: str = "rag-bronze"
    silver_bucket: str = "rag-silver"
    silver_prefix: str = "documentos"
    timeout_seconds: float = Field(default=10.0, gt=0)


class ElasticsearchIndexSettings(StrictModel):
    documents: str = "websensors-rag-documents-v1"
    chunks: str = "websensors-rag-chunks-v1"


class ElasticsearchAliasSettings(StrictModel):
    documents: str = "websensors-rag-documents"
    chunks: str = "websensors-rag-chunks"


class ElasticsearchSettings(StrictModel):
    endpoint: str
    username: str | None = None
    password: str | None = None
    api_key: str | None = None
    verify_certs: bool = True
    ca_cert: str | None = None
    timeout_seconds: float = 30.0
    index_creation_timeout_seconds: float = Field(default=180.0, ge=10.0)
    indices: ElasticsearchIndexSettings = Field(default_factory=ElasticsearchIndexSettings)
    aliases: ElasticsearchAliasSettings = Field(default_factory=ElasticsearchAliasSettings)
    shards: int = 1
    replicas: int = 0


class DoclingSettings(StrictModel):
    endpoint: str
    api_key: str | None = None
    timeout_seconds: float = 600.0
    poll_interval_seconds: float = 1.0
    options: dict[str, Any] = Field(default_factory=dict)


class EmbeddingSettings(StrictModel):
    endpoint: str
    path: str = "/embeddings"
    models_path: str = "/models"
    api_key: str | None = None
    model: str
    dimensions: int = Field(gt=0)
    batch_size: int = Field(default=32, ge=1, le=512)
    timeout_seconds: float = 120.0
    truncate_prompt_tokens: int | None = Field(default=None, ge=1)


class LLMSettings(StrictModel):
    endpoint: str = "https://openrouter.ai/api/v1"
    model: str = Field(min_length=1)
    api_key: str = Field(min_length=1, repr=False)
    timeout_seconds: float = Field(default=120, gt=0)
    temperature: float = Field(default=0, ge=0, le=2)
    max_tokens: int = Field(default=2048, ge=128)
    retries: int = Field(default=2, ge=0, le=5)
    structured_output: bool = True


class ClassificationSettings(StrictModel):
    enabled: bool = False
    projects_dir: str = "projects"
    max_input_chars: int = Field(default=100000, ge=1)


class ExtractionSettings(StrictModel):
    enabled: bool = False
    structured_output: bool | None = None
    max_input_chars: int = Field(default=100000, ge=1)
    max_output_tokens: int = Field(default=4096, ge=128)
    # Inclui cabeçalhos/rodapés do JSON Docling, omitidos pelo Markdown exportado.
    include_page_furniture: bool = False


class StructuredIndexSettings(StrictModel):
    """Publicação da extração em índices Elasticsearch por projeto/tipo documental."""
    enabled: bool = False
    index_prefix: str = Field(default="rag-estruturado", pattern=r"^[a-z0-9][a-z0-9_-]{0,40}$")


class ServicesSettings(StrictModel):
    llm: LLMSettings | None = None
    minio: MinIOSettings
    elasticsearch: ElasticsearchSettings
    docling: DoclingSettings
    embeddings: EmbeddingSettings


class ChunkingSettings(StrictModel):
    strategy: Literal["structural"] = "structural"
    target_tokens: int = Field(default=600, ge=64)
    max_tokens: int = Field(default=900, ge=128)
    overlap_tokens: int = Field(default=80, ge=0)
    min_chunk_tokens: int = Field(default=40, ge=1)

    @model_validator(mode="after")
    def validate_limits(self) -> "ChunkingSettings":
        if self.target_tokens > self.max_tokens:
            raise ValueError("target_tokens deve ser menor ou igual a max_tokens.")
        if self.overlap_tokens >= self.target_tokens:
            raise ValueError("overlap_tokens deve ser menor que target_tokens.")
        if self.min_chunk_tokens > self.max_tokens:
            raise ValueError("min_chunk_tokens deve ser menor ou igual a max_tokens.")
        return self


class UpdateSettings(StrictModel):
    compare_source_hash: bool = True
    compare_pipeline_hash: bool = True


class IndexingSettings(StrictModel):
    processing_version: str = "1"
    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)
    update: UpdateSettings = Field(default_factory=UpdateSettings)


class LexicalSearchSettings(StrictModel):
    fields: list[str] = Field(default_factory=lambda: ["title^3", "heading_text^2.5", "section^2", "content"])


class SemanticSearchSettings(StrictModel):
    candidates: int = Field(default=50, ge=1)
    num_candidates: int = Field(default=200, ge=1)


class HybridSearchSettings(StrictModel):
    rank_window_size: int = Field(default=50, ge=1)
    rank_constant: int = Field(default=60, ge=1)



class SearchSettings(StrictModel):
    default_top_k: int = Field(default=10, ge=1, le=100)
    max_top_k: int = Field(default=50, ge=1, le=500)
    lexical: LexicalSearchSettings = Field(default_factory=LexicalSearchSettings)
    semantic: SemanticSearchSettings = Field(default_factory=SemanticSearchSettings)
    hybrid: HybridSearchSettings = Field(default_factory=HybridSearchSettings)

    @model_validator(mode="after")
    def validate_top_k(self) -> "SearchSettings":
        if self.default_top_k > self.max_top_k:
            raise ValueError("default_top_k deve ser menor ou igual a max_top_k.")
        return self


class APIAuthSettings(StrictModel):
    enabled: bool = False
    token: str | None = None

    @model_validator(mode="after")
    def validate_token(self) -> "APIAuthSettings":
        if self.enabled and not self.token:
            raise ValueError("Autenticação da API habilitada sem token no YAML.")
        return self


class APISettings(StrictModel):
    title: str = "WebSensors Flow RAG API"
    description: str = "Serviço de indexação e busca para RAG."
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    indexing_workers: int = Field(default=4, ge=1, le=64)
    max_upload_bytes: int = Field(default=50 * 1024 * 1024, ge=1)
    event_history_limit: int = Field(default=1000, ge=10)
    cors_origins: list[str] = Field(default_factory=list)
    auth: APIAuthSettings = Field(default_factory=APIAuthSettings)


class StartupSettings(StrictModel):
    enabled: bool = True
    retries: int = Field(default=2, ge=0, le=20)
    retry_interval_seconds: float = Field(default=2.0, ge=0, le=60)
    timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    validate_embedding_vector: bool = True
    check_mlflow_write: bool = True


class RAGSettings(StrictModel):
    source_path: str | None = None
    project: ProjectSettings = Field(default_factory=ProjectSettings)
    environment: EnvironmentSettings = Field(default_factory=EnvironmentSettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    services: ServicesSettings
    classification: ClassificationSettings = Field(default_factory=ClassificationSettings)
    extraction: ExtractionSettings = Field(default_factory=ExtractionSettings)
    structured_index: StructuredIndexSettings = Field(default_factory=StructuredIndexSettings)
    indexing: IndexingSettings = Field(default_factory=IndexingSettings)
    startup: StartupSettings = Field(default_factory=StartupSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    api: APISettings = Field(default_factory=APISettings)

    @field_validator("project")
    @classmethod
    def validate_project_name(cls, value: ProjectSettings) -> ProjectSettings:
        if value.name != "websensors-flow-rag":
            raise ValueError("project.name deve ser websensors-flow-rag.")
        return value

    def to_flow_settings(self) -> FlowSettings:
        steps = [
            StepDefinition(name="resolver_fonte", class_path="websensors_flow_rag.indexing.steps.ResolveSourceStep"),
            StepDefinition(name="detectar_alteracoes", class_path="websensors_flow_rag.indexing.steps.DetectChangesStep"),
            StepDefinition(name="converter_docling", class_path="websensors_flow_rag.indexing.steps.ConvertDoclingStep"),
            StepDefinition(name="armazenar_silver", class_path="websensors_flow_rag.indexing.steps.StoreSilverStep"),
            StepDefinition(name="segmentar_documento", class_path="websensors_flow_rag.indexing.steps.ChunkDocumentStep"),
            StepDefinition(name="gerar_embeddings", class_path="websensors_flow_rag.indexing.steps.GenerateEmbeddingsStep"),
            StepDefinition(name="preparar_revisao_elasticsearch", class_path="websensors_flow_rag.indexing.steps.StageElasticsearchStep"),
            StepDefinition(name="validar_revisao", class_path="websensors_flow_rag.indexing.steps.ValidateRevisionStep"),
            StepDefinition(name="publicar_revisao", class_path="websensors_flow_rag.indexing.steps.PublishRevisionStep"),
        ]

        if self.classification.enabled:
            if self.services.llm is None:
                raise ConfigurationError("Classificação habilitada exige services.llm.")
            steps.insert(3, StepDefinition(name="classificar_documento", class_path="websensors_flow_rag.classification.steps.ClassifyDocumentTypeStep"))

        if self.extraction.enabled:
            if not self.classification.enabled or self.services.llm is None:
                raise ConfigurationError("Extração exige classificação habilitada e services.llm.")
            steps.insert(4, StepDefinition(name="extrair_dados_estruturados", class_path="websensors_flow_rag.extraction.steps.ExtractStructuredDataStep"))

        if self.structured_index.enabled:
            if not self.extraction.enabled:
                raise ConfigurationError("Índices estruturados exigem extração habilitada.")
            position = next(i for i, step in enumerate(steps) if step.name == "preparar_revisao_elasticsearch") + 1
            steps.insert(position, StepDefinition(name="preparar_registro_estruturado", class_path="websensors_flow_rag.structured.steps.StageStructuredRecordStep"))

        mlflow = self.observability.mlflow
        graylog = self.observability.graylog

        observability = ObservabilityConfig(
            mlflow=MLflowConfig(
                enabled=mlflow.enabled,
                tracking_uri=mlflow.tracking_uri,
                experiment_name=mlflow.experiment_name,
                run_name=mlflow.run_name,
                artifact_location=mlflow.artifact_location,
                http_request_timeout=mlflow.http_request_timeout,
                connect_timeout_seconds=mlflow.connect_timeout_seconds,
                auth=AuthConfig(
                    enabled=mlflow.auth.enabled,
                    username=mlflow.auth.username,
                    password=mlflow.auth.password,
                    token=mlflow.auth.token,
                ),
            ),
            graylog=GraylogConfig(
                enabled=graylog.enabled,
                host=graylog.host,
                port=graylog.port,
                protocol=graylog.protocol,
                facility=graylog.facility,
                level=graylog.level,
                localname=graylog.localname,
                connect_timeout_seconds=graylog.connect_timeout_seconds,
                auth=AuthConfig(
                    enabled=graylog.auth.enabled,
                    username=graylog.auth.username,
                    password=graylog.auth.password,
                    token=graylog.auth.token,
                ),
            ),
        )

        return FlowSettings(
            source_path=self.source_path,
            project=ProjectConfig(
                name=self.project.name,
                version=self.project.version,
                description=self.project.description,
            ),
            environment=EnvironmentConfig(
                name=self.environment.name,
                deployment_id=self.environment.deployment_id,
                owner=self.environment.owner,
                tags=self.environment.tags,
            ),
            runtime=RuntimeConfig(
                report_dir=self.runtime.report_dir,
                fail_fast=True,
                include_traceback=self.runtime.include_traceback,
                raise_on_failure=self.runtime.raise_on_failure,
                console=ConsoleConfig(**self.runtime.console.model_dump()),
            ),
            observability=observability,
            pipeline=PipelineConfig(params={"servico": "rag"}),
            steps=steps,
            api=ApiConfig(enabled=False),
        )


def _resolve_environment_values(value: Any, variables: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: _resolve_environment_values(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_environment_values(item, variables) for item in value]
    match = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", value) if isinstance(value, str) else None
    if match:
        name = match.group(1)
        resolved = variables.get(name)
        if not resolved:
            raise ConfigurationError(f"Variável de ambiente obrigatória ausente: {name}")
        return resolved
    return value


def load_rag_settings(path: str | Path, *, env_file: str | Path | None = None) -> RAGSettings:
    path = Path(path).resolve()
    if not path.exists():
        raise ConfigurationError(f"Arquivo de configuração não encontrado: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        # YAMLs em config/ usam o .env da raiz; outros usam o .env adjacente.
        default_env = (path.parent.parent if path.parent.name == "config" else path.parent) / ".env"
        selected_env = Path(env_file).resolve() if env_file is not None else default_env
        file_values = dotenv_values(selected_env, interpolate=False) if selected_env.is_file() else {}
        variables = {**file_values, **os.environ}
        raw = _resolve_environment_values(raw, variables)
        raw["source_path"] = str(path)
        return RAGSettings.model_validate(raw)
    except (yaml.YAMLError, ValidationError) as exc:
        raise ConfigurationError(str(exc)) from exc

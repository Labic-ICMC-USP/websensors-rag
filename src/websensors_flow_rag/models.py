from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IndexDocumentRequest(APIModel):
    bucket: str | None = Field(default=None, description="Bucket de origem. Quando omitido, usa o bucket bronze configurado.")
    key: str = Field(min_length=1, description="Chave do objeto no MinIO.")
    document_id: str | None = Field(default=None, description="Identificador estável do documento. Quando omitido, é derivado do bucket e da chave.")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Metadados pesquisáveis associados ao documento.")
    force: bool = Field(default=False, description="Força uma nova indexação mesmo quando os hashes não mudaram.")


class IndexStartResponse(APIModel):
    token: str
    status: Literal["queued", "running", "success", "failed"]
    terminal: bool
    document_id: str | None = None
    message: str
    status_url: str


class RunStatusResponse(APIModel):
    token: str
    status: Literal["queued", "running", "success", "failed"]
    terminal: bool
    message: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    updated_at: str
    progress: dict[str, Any]
    trace_id: str | None = None
    models: list[dict[str, Any]] = Field(default_factory=list)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class SearchRequest(APIModel):
    query: str = Field(min_length=1, description="Consulta textual.")
    top_k: int | None = Field(default=None, ge=1, le=500, description="Quantidade de resultados finais.")
    filters: dict[str, str | int | float | bool | list[str | int | float | bool]] = Field(
        default_factory=dict,
        description="Filtros exatos. Chaves desconhecidas são tratadas como metadados do documento.",
    )
    debug: bool = Field(default=False, description="Inclui informações adicionais de recuperação na resposta.")

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query não pode conter somente espaços.")
        return value


class SearchHit(APIModel):
    rank: int
    document_id: str
    chunk_id: str
    revision_id: str
    filename: str | None = None
    title: str | None = None
    section: str | None = None
    heading_path: list[str] = Field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    content: str
    score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(APIModel):
    query: str
    mode: Literal["bm25", "semantic", "hybrid"]
    took_ms: float
    count: int
    results: list[SearchHit]
    debug: dict[str, Any] | None = None


class ServiceDescriptor(APIModel):
    name: str
    description: str
    environment: str
    operations: dict[str, str]
    indexing: dict[str, Any]
    search: dict[str, Any]


class HealthResponse(APIModel):
    status: Literal["ok", "degraded"]
    service: str
    dependencies: dict[str, str]
    details: list[dict[str, Any]] = Field(default_factory=list)
    openapi: str = "/openapi.json"


@dataclass
class WorkItem:
    request: IndexDocumentRequest
    bucket: str = ""
    key: str = ""
    document_id: str = ""
    filename: str = ""
    mime_type: str = "application/octet-stream"
    source_bytes: bytes | None = None
    source_sha256: str = ""
    pipeline_hash: str = ""
    revision_id: str = ""
    existing_document: dict[str, Any] | None = None
    noop: bool = False
    metadata_only: bool = False
    markdown: str = ""
    docling_json: dict[str, Any] = field(default_factory=dict)
    docling_metadata: dict[str, Any] = field(default_factory=dict)
    silver: dict[str, str] = field(default_factory=dict)
    chunks: list[dict[str, Any]] = field(default_factory=list)
    final_result: dict[str, Any] = field(default_factory=dict)

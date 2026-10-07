from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from pathlib import PurePosixPath
from typing import Any

from websensors_flow_rag.config import RAGSettings, load_rag_settings


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_document_id(bucket: str, key: str) -> str:
    raw = f"{bucket}:{key}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def pipeline_hash(settings: RAGSettings) -> str:
    payload = {
        "processing_version": settings.indexing.processing_version,
        "docling_options": settings.services.docling.options,
        "chunking": settings.indexing.chunking.model_dump(mode="json"),
        "embedding": {
            "endpoint_path": settings.services.embeddings.path,
            "model": settings.services.embeddings.model,
            "dimensions": settings.services.embeddings.dimensions,
        },
    }
    if settings.services.embeddings.truncate_prompt_tokens is not None:
        payload["embedding"]["truncate_prompt_tokens"] = settings.services.embeddings.truncate_prompt_tokens
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def revision_id(source_sha256: str, processing_hash: str) -> str:
    return hashlib.sha256(f"{source_sha256}:{processing_hash}".encode("utf-8")).hexdigest()[:24]


def detect_filename(key: str) -> str:
    return PurePosixPath(key).name or "documento"


def detect_mime_type(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def normalize_text(value: str) -> str:
    value = re.sub(r"[`*_>#|]", " ", value)
    value = re.sub(r"\s+", " ", value).strip().lower()
    return value


def public_service_metadata(settings: RAGSettings) -> dict[str, Any]:
    return {
        "docling": {
            "picture_description_preset": settings.services.docling.options.get("picture_description_preset"),
        },
        "embeddings": {
            "model": settings.services.embeddings.model,
            "dimensions": settings.services.embeddings.dimensions,
        },
        "elasticsearch": {
            "documents_alias": settings.services.elasticsearch.aliases.documents,
            "chunks_alias": settings.services.elasticsearch.aliases.chunks,
        },
    }


def load_context_settings(context: Any) -> RAGSettings:
    source_path = context.settings.source_path
    if not source_path:
        raise RuntimeError("O caminho do YAML global não está disponível no contexto do flow.")
    return load_rag_settings(source_path)

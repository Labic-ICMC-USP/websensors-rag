"""Nomes, definição e validação dos registros estruturados por tipo documental.

Cada tipo de um projeto tem um alias de leitura (``<prefixo>-<projeto>-<tipo>``) e
índices físicos versionados pelo hash do ``mapping.json``. Assim, uma mudança de
mapping cria outro índice físico em vez de exigir alteração incompatível.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from websensors_flow_rag.config import RAGSettings
from websensors_flow_rag.utils import classification_projects_dir

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _resource_dir(settings: RAGSettings, project: str, document_type: str) -> Path:
    if not _NAME.fullmatch(project) or not _NAME.fullmatch(document_type):
        raise ValueError("Projeto ou tipo documental inválido para índice estruturado.")
    root = classification_projects_dir(settings).resolve()
    directory = (root / project / "document_types" / document_type).resolve()
    if not directory.is_relative_to(root):
        raise ValueError("Recursos fora do diretório de projetos.")
    return directory


def structured_index_pattern(settings: RAGSettings, project: str) -> str:
    if not _NAME.fullmatch(project):
        raise ValueError("Projeto inválido para índice estruturado.")
    return f"{settings.structured_index.index_prefix}-{project}-*"


def structured_target(settings: RAGSettings, project: str, document_type: str) -> dict[str, Any]:
    """Resolve alias, índice físico, mapping e schema de ``data`` para um tipo."""
    directory = _resource_dir(settings, project, document_type)
    mapping_text = (directory / "mapping.json").read_text(encoding="utf-8")
    schema_text = (directory / "schema.json").read_text(encoding="utf-8")
    mapping = json.loads(mapping_text)
    if mapping.get("mappings", {}).get("dynamic") != "strict":
        raise ValueError("Mapping estruturado deve ser explícito (dynamic: strict).")
    schema = json.loads(schema_text)
    data_schema = schema["properties"]["data"]
    mapping_version = hashlib.sha256(mapping_text.encode("utf-8")).hexdigest()
    alias = f"{settings.structured_index.index_prefix}-{project}-{document_type}"
    return {
        "alias": alias,
        "index": f"{alias}-{mapping_version[:12]}",
        "mapping_version": mapping_version,
        "schema_version": hashlib.sha256(schema_text.encode("utf-8")).hexdigest(),
        "definition": {
            "settings": {
                "number_of_shards": settings.services.elasticsearch.shards,
                "number_of_replicas": settings.services.elasticsearch.replicas,
            },
            **mapping,
        },
        "data_schema": data_schema,
    }


def has_structured_data(extraction: dict[str, Any] | None) -> bool:
    return bool(extraction) and extraction.get("status") in {"success", "needs_review"} and isinstance(extraction.get("data"), dict)


def build_record(work: Any, target: dict[str, Any], now: str) -> dict[str, Any]:
    extraction = work.extraction
    metadata = work.extraction_metadata or {}
    return {
        "document_id": work.document_id,
        "revision_id": work.revision_id,
        "document_type": extraction["document_type"],
        "project": work.request.project,
        "filename": work.filename,
        "extraction_version": metadata.get("prompt_version"),
        "schema_version": target["schema_version"],
        "status": extraction["status"],
        "needs_review": extraction["status"] != "success",
        "warnings": list(extraction.get("warnings") or []),
        "data": extraction["data"],
        "sources": list(extraction.get("sources") or []),
        "active": False,
        "source": {"bucket": work.bucket, "key": work.key},
        "created_at": now,
        "updated_at": now,
    }


def validate_record(record: dict[str, Any] | None, pointer: dict[str, Any], data_schema: dict[str, Any]) -> None:
    """Confere o registro preparado antes da publicação, sem copiar valores nas mensagens."""
    if record is None:
        raise RuntimeError("Registro estruturado preparado não encontrado no Elasticsearch.")
    if record.get("active") is not False:
        raise RuntimeError("Registro estruturado preparado já está ativo; publicação interrompida.")
    for key in ("document_id", "revision_id", "document_type"):
        if record.get(key) != pointer.get(key):
            raise RuntimeError(f"Registro estruturado divergente da revisão em '{key}'.")
    error = next(Draft202012Validator(data_schema).iter_errors(record.get("data")), None)
    if error is not None:
        raise RuntimeError(f"Registro estruturado incompatível com o schema; regra: {error.validator}.")

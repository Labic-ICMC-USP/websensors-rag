from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from websensors_flow import PipelineStep, StepResult
from websensors_flow_rag.clients.elasticsearch_client import ElasticsearchClient
from websensors_flow_rag.structured.index import build_record, has_structured_data, structured_target
from websensors_flow_rag.utils import load_context_settings


class StageStructuredRecordStep(PipelineStep):
    """Prepara o registro da extração, inativo, no índice do tipo documental.

    A ativação ocorre somente em ``PublishRevisionStep``, junto da revisão textual.
    """

    def execute(self, input: Any, context: Any) -> StepResult:
        work = input
        if work.noop or work.metadata_only:
            work.structured = (work.existing_document or {}).get("structured")
            return StepResult(output=work, has_output=True, text="Registro estruturado persistido reutilizado.", metrics={"structured_reused": 1})
        if not work.request.project or not has_structured_data(work.extraction):
            work.structured = None
            return StepResult(
                output=work, has_output=True,
                text="Sem dados estruturados para indexar (legado, tipo outro ou extração sem dados).",
                metrics={"structured_staged": 0, "structured_skipped": 1},
            )

        settings = load_context_settings(context)
        document_type = work.extraction["document_type"]
        target = structured_target(settings, work.request.project, document_type)
        record_id = f"{work.document_id}:{work.revision_id}"
        now = datetime.now(timezone.utc).isoformat()
        record = build_record(work, target, now)
        previous = (work.existing_document or {}).get("structured")
        restored = 0

        es = ElasticsearchClient(settings.services.elasticsearch, settings.services.embeddings.dimensions)
        try:
            es.ensure_structured_index(target["index"], target["alias"], target["definition"])
            leftover = es.get_structured_record(target["index"], record_id)
            if leftover and leftover.get("active"):
                # Publicação anterior interrompida: devolver o estado ativo à
                # revisão publicada antes de preparar novamente esta revisão.
                if previous and previous.get("record_id") != record_id:
                    if not es.set_structured_active(previous["index"], previous["record_id"], True, now):
                        raise RuntimeError("Registro estruturado ativo anterior não encontrado para restauração.")
                    restored = 1
            es.put_structured_record(target["index"], record_id, record)
        finally:
            es.close()

        work.structured = {
            "index": target["index"],
            "alias": target["alias"],
            "record_id": record_id,
            "document_id": work.document_id,
            "revision_id": work.revision_id,
            "document_type": document_type,
            "mapping_version": target["mapping_version"],
            "schema_version": target["schema_version"],
        }
        populated = sum(value not in (None, "", [], {}) for value in record["data"].values())
        return StepResult(
            output=work, has_output=True,
            text="Registro estruturado preparado sem publicação.",
            metrics={
                "structured_staged": 1,
                "structured_fields_count": populated,
                "structured_record_bytes": len(json.dumps(record, ensure_ascii=False).encode("utf-8")),
                "structured_previous_restored": restored,
            },
            params={"structured_document_type": document_type, "structured_mapping_version": target["mapping_version"][:12]},
        )

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any

from websensors_flow import PipelineStep, StepResult
from websensors_flow_rag.clients.docling_client import DoclingClient
from websensors_flow_rag.clients.elasticsearch_client import ElasticsearchClient
from websensors_flow_rag.clients.minio_client import MinIOClient
from websensors_flow_rag.clients.model_client import EmbeddingClient
from websensors_flow_rag.indexing.chunking import attach_pages, structural_chunks
from websensors_flow_rag.models import IndexDocumentRequest, WorkItem
from websensors_flow_rag.utils import (
    detect_filename,
    detect_mime_type,
    load_context_settings,
    pipeline_hash,
    revision_id,
    sha256_bytes,
    stable_document_id,
)


def _skip(work: WorkItem, text: str) -> StepResult:
    return StepResult(output=work, has_output=True, text=text, metrics={"noop": 1})


class ResolveSourceStep(PipelineStep):
    def execute(self, input: Any, context: Any) -> StepResult:
        settings = load_context_settings(context)
        request = input if isinstance(input, IndexDocumentRequest) else IndexDocumentRequest.model_validate(input)
        bucket = request.bucket or settings.services.minio.bronze_bucket
        key = request.key
        document_id = request.document_id or stable_document_id(bucket, key)
        filename = detect_filename(key)
        mime_type = detect_mime_type(filename)

        client = MinIOClient(settings.services.minio)
        context.logger.info("Obtendo arquivo do MinIO Bronze.", metadata={"bucket": bucket, "key": key})
        content = client.get_bytes(bucket, key)
        work = WorkItem(
            request=request,
            bucket=bucket,
            key=key,
            document_id=document_id,
            filename=filename,
            mime_type=mime_type,
            source_bytes=content,
            source_sha256=sha256_bytes(content),
        )
        return StepResult(
            output=work,
            has_output=True,
            text="Fonte carregada do MinIO.",
            metrics={"source_bytes": len(content)},
            metadata={"document_id": document_id, "bucket": bucket, "key": key, "mime_type": mime_type},
        )


class DetectChangesStep(PipelineStep):
    def execute(self, input: WorkItem, context: Any) -> StepResult:
        settings = load_context_settings(context)
        work = input
        work.pipeline_hash = pipeline_hash(settings)

        es = ElasticsearchClient(settings.services.elasticsearch, settings.services.embeddings.dimensions)
        try:
            es.ensure_indices()
            existing = es.get_document(work.document_id)
        finally:
            es.close()
        work.existing_document = existing

        metadata_was_sent = "metadata" in work.request.model_fields_set
        if existing and not metadata_was_sent:
            work.request.metadata = dict(existing.get("metadata") or {})

        unchanged = False
        metadata_only = False
        if existing and not work.request.force:
            same_source = existing.get("source", {}).get("sha256") == work.source_sha256
            same_pipeline = existing.get("pipeline_hash") == work.pipeline_hash
            source_ok = same_source or not settings.indexing.update.compare_source_hash
            pipeline_ok = same_pipeline or not settings.indexing.update.compare_pipeline_hash
            processing_unchanged = source_ok and pipeline_ok and existing.get("status") == "ready"
            same_metadata = (existing.get("metadata") or {}) == work.request.metadata
            unchanged = processing_unchanged and same_metadata
            metadata_only = processing_unchanged and not same_metadata and metadata_was_sent

        if unchanged:
            work.noop = True
            work.revision_id = str(existing.get("active_revision") or "")
            work.final_result = {
                "action": "noop",
                "document_id": work.document_id,
                "revision_id": work.revision_id,
                "message": "O documento e a configuração de processamento não mudaram.",
            }
            return StepResult(
                output=work,
                has_output=True,
                text="Nenhuma atualização necessária.",
                metrics={"changed": 0, "noop": 1},
                metadata={"document_id": work.document_id, "revision_id": work.revision_id},
            )


        if metadata_only:
            work.metadata_only = True
            work.revision_id = str(existing.get("active_revision") or "")
            return StepResult(
                output=work,
                has_output=True,
                text="Somente os metadados serão atualizados.",
                metrics={"changed": 1, "metadata_only": 1},
                metadata={"document_id": work.document_id, "revision_id": work.revision_id},
            )

        base_revision = revision_id(work.source_sha256, work.pipeline_hash)
        if work.request.force and existing and existing.get("active_revision") == base_revision:
            work.revision_id = hashlib.sha256(
                f"{work.source_sha256}:{work.pipeline_hash}:{context.run_id}".encode("utf-8")
            ).hexdigest()[:24]
        else:
            work.revision_id = base_revision

        return StepResult(
            output=work,
            has_output=True,
            text="Alteração detectada e nova revisão preparada.",
            metrics={"changed": 1, "noop": 0},
            metadata={"document_id": work.document_id, "revision_id": work.revision_id},
        )


class ConvertDoclingStep(PipelineStep):
    def execute(self, input: WorkItem, context: Any) -> StepResult:
        work = input
        if work.noop:
            return _skip(work, "Conversão dispensada porque não houve alteração.")
        if work.metadata_only:
            return _skip(work, "Conversão dispensada porque somente os metadados serão atualizados.")
        if work.source_bytes is None:
            raise RuntimeError("Conteúdo de origem ausente antes da conversão.")

        settings = load_context_settings(context)
        preset = settings.services.docling.options.get("picture_description_preset")
        context.register_model(
            str(preset or "docling"),
            provider="docling",
            role="processamento_documental",
            endpoint=settings.services.docling.endpoint,
            metadata={
                "descricao_de_imagens": bool(settings.services.docling.options.get("do_picture_description")),
                "preset_descricao": preset,
            },
        )
        client = DoclingClient(settings.services.docling)
        last_logged = [0.0]
        def report_docling(progress: dict[str, Any]) -> None:
            now = time.monotonic()
            if now - last_logged[0] < 5.0 and progress.get("status") not in {"success", "completed", "done", "failure", "failed", "error"}:
                return
            last_logged[0] = now
            eta = progress.get("eta_seconds")
            context.logger.info(
                "Docling em processamento. "
                f"Status {progress['status']}. "
                f"Tempo decorrido {progress['elapsed_seconds']:.1f}s. "
                f"ETA {f'{eta:.1f}s' if eta is not None else 'indisponível' }.",
                metrics={"docling_elapsed_seconds": progress["elapsed_seconds"]},
                metadata={"task_id": progress["task_id"], "eta_seconds": eta, "percent": progress.get("percent")},
            )
        try:
            converted = client.convert(work.filename, work.source_bytes, work.mime_type, progress_callback=report_docling)
        finally:
            client.close()

        markdown = converted.get("markdown", "").strip()
        if not markdown:
            raise RuntimeError("O Docling não retornou conteúdo Markdown.")
        work.markdown = markdown
        work.docling_json = converted.get("json") or {}
        work.docling_metadata = {
            "status": converted.get("status"),
            "processing_time": converted.get("processing_time"),
            "timings": converted.get("timings") or {},
            "errors": converted.get("errors") or [],
        }
        return StepResult(
            output=work,
            has_output=True,
            text="Documento convertido pelo Docling para Markdown e JSON.",
            metrics={
                "markdown_chars": len(work.markdown),
                "docling_errors": len(work.docling_metadata["errors"]),
            },
            metadata={"docling_status": str(work.docling_metadata.get("status") or "")},
        )


class StoreSilverStep(PipelineStep):
    def execute(self, input: WorkItem, context: Any) -> StepResult:
        work = input
        if work.noop:
            return _skip(work, "Persistência Silver dispensada porque não houve alteração.")
        if work.metadata_only:
            return _skip(work, "Persistência Silver dispensada porque somente os metadados serão atualizados.")
        settings = load_context_settings(context)
        client = MinIOClient(settings.services.minio)
        prefix = settings.services.minio.silver_prefix.strip("/")
        base = f"{prefix}/{work.document_id}/{work.revision_id}"
        markdown_key = f"{base}/document.md"
        json_key = f"{base}/document.json"
        manifest_key = f"{base}/manifest.json"

        manifest = {
            "document_id": work.document_id,
            "revision_id": work.revision_id,
            "source": {
                "bucket": work.bucket,
                "key": work.key,
                "sha256": work.source_sha256,
                "filename": work.filename,
                "mime_type": work.mime_type,
            },
            "pipeline_hash": work.pipeline_hash,
            "docling": work.docling_metadata,
        }

        bucket = settings.services.minio.silver_bucket
        with context.progress(total=3, description="Armazenando artefatos no MinIO Silver", unit="objetos") as progress:
            client.put_text(bucket, markdown_key, work.markdown, "text/markdown; charset=utf-8")
            progress.update()
            client.put_text(
                bucket,
                json_key,
                json.dumps(work.docling_json, ensure_ascii=False, indent=2),
                "application/json; charset=utf-8",
            )
            progress.update()
            client.put_text(
                bucket,
                manifest_key,
                json.dumps(manifest, ensure_ascii=False, indent=2),
                "application/json; charset=utf-8",
            )
            progress.update()

        work.silver = {
            "markdown": f"s3://{bucket}/{markdown_key}",
            "json": f"s3://{bucket}/{json_key}",
            "manifest": f"s3://{bucket}/{manifest_key}",
        }
        work.source_bytes = None
        return StepResult(
            output=work,
            has_output=True,
            text="Representações Markdown e JSON armazenadas no MinIO Silver.",
            metrics={"silver_objects": 3},
            metadata=work.silver,
        )


class ChunkDocumentStep(PipelineStep):
    def execute(self, input: WorkItem, context: Any) -> StepResult:
        work = input
        if work.noop:
            return _skip(work, "Segmentação dispensada porque não houve alteração.")
        if work.metadata_only:
            return _skip(work, "Segmentação dispensada porque somente os metadados serão atualizados.")
        settings = load_context_settings(context)
        title, chunks = structural_chunks(work.markdown, settings.indexing.chunking)
        attach_pages(chunks, work.docling_json)
        if not chunks:
            raise RuntimeError("A segmentação não produziu chunks.")
        for chunk in chunks:
            chunk["title"] = chunk.get("title") or title or work.filename
        work.chunks = chunks
        return StepResult(
            output=work,
            has_output=True,
            text="Documento segmentado com base na estrutura do Markdown.",
            metrics={
                "chunks": len(chunks),
                "tokens_estimados": sum(int(item.get("estimated_tokens") or 0) for item in chunks),
            },
        )


class GenerateEmbeddingsStep(PipelineStep):
    def execute(self, input: WorkItem, context: Any) -> StepResult:
        work = input
        if work.noop:
            return _skip(work, "Geração de embeddings dispensada porque não houve alteração.")
        if work.metadata_only:
            return _skip(work, "Geração de embeddings dispensada porque somente os metadados serão atualizados.")
        settings = load_context_settings(context)
        embedding_settings = settings.services.embeddings
        context.register_model(
            embedding_settings.model,
            provider="openai_compatible",
            role="embedding",
            endpoint=embedding_settings.endpoint,
            metadata={"dimensions": embedding_settings.dimensions},
        )
        client = EmbeddingClient(embedding_settings)
        batch_size = embedding_settings.batch_size
        batches = [work.chunks[i : i + batch_size] for i in range(0, len(work.chunks), batch_size)]
        try:
            with context.progress(total=len(batches), description="Gerando embeddings", unit="lotes") as progress:
                for batch in batches:
                    vectors = client.embed([item["embedding_text"] for item in batch])
                    for item, vector in zip(batch, vectors):
                        item["embedding"] = vector
                    progress.update()
        finally:
            client.close()
        return StepResult(
            output=work,
            has_output=True,
            text="Embeddings gerados para todos os chunks.",
            metrics={"chunks_embedded": len(work.chunks), "embedding_dimensions": embedding_settings.dimensions},
            params={"embedding_model": embedding_settings.model},
        )


class StageElasticsearchStep(PipelineStep):
    def execute(self, input: WorkItem, context: Any) -> StepResult:
        work = input
        if work.noop:
            return _skip(work, "Preparação no Elasticsearch dispensada porque não houve alteração.")
        if work.metadata_only:
            return _skip(work, "Preparação de revisão dispensada porque somente os metadados serão atualizados.")
        settings = load_context_settings(context)
        now = datetime.now(timezone.utc).isoformat()
        indexed: list[dict[str, Any]] = []
        for chunk in work.chunks:
            sequence = int(chunk["sequence"])
            indexed.append(
                {
                    "chunk_id": f"{work.document_id}:{work.revision_id}:{sequence:06d}",
                    "document_id": work.document_id,
                    "revision_id": work.revision_id,
                    "active": False,
                    "sequence": sequence,
                    "type": chunk.get("type", "text"),
                    "filename": work.filename,
                    "mime_type": work.mime_type,
                    "title": chunk.get("title"),
                    "section": chunk.get("section"),
                    "heading_path": chunk.get("heading_path") or [],
                    "heading_text": chunk.get("heading_text") or "",
                    "page_start": chunk.get("page_start"),
                    "page_end": chunk.get("page_end"),
                    "content": chunk["content"],
                    "embedding_text": chunk["embedding_text"],
                    "embedding": chunk["embedding"],
                    "metadata": work.request.metadata,
                    "source": {"bucket": work.bucket, "key": work.key},
                    "created_at": now,
                }
            )
        es = ElasticsearchClient(settings.services.elasticsearch, settings.services.embeddings.dimensions)
        try:
            active_target = es.count_revision(work.document_id, work.revision_id, active=True)
            if active_target:
                previous_revision = (work.existing_document or {}).get("active_revision")
                if previous_revision and previous_revision != work.revision_id and es.count_revision(work.document_id, previous_revision) > 0:
                    es.switch_active_revision(work.document_id, previous_revision)
                    if es.count_revision(work.document_id, work.revision_id, active=True) > 0:
                        raise RuntimeError("Não foi possível restaurar a revisão ativa anterior antes da nova tentativa.")
                else:
                    raise RuntimeError(
                        "A revisão que seria preparada já possui chunks ativos e não foi possível restaurar a revisão anterior."
                    )
            es.delete_staged_revision(work.document_id, work.revision_id)
            batch_size = 128
            batches = [indexed[i:i+batch_size] for i in range(0, len(indexed), batch_size)]
            with context.progress(total=len(batches), description="Indexando chunks no Elasticsearch", unit="lotes") as progress:
                for batch in batches:
                    es.bulk_index_chunks(batch)
                    progress.update(metadata={"chunks_do_lote": len(batch)})
        finally:
            es.close()
        work.chunks = indexed
        return StepResult(
            output=work,
            has_output=True,
            text="Nova revisão preparada no Elasticsearch sem publicação para busca.",
            metrics={"chunks_staged": len(indexed)},
            metadata={"revision_id": work.revision_id},
        )


class ValidateRevisionStep(PipelineStep):
    def execute(self, input: WorkItem, context: Any) -> StepResult:
        work = input
        if work.noop:
            return _skip(work, "Validação dispensada porque não houve alteração.")
        if work.metadata_only:
            return _skip(work, "Validação de revisão dispensada porque somente os metadados serão atualizados.")
        settings = load_context_settings(context)
        es = ElasticsearchClient(settings.services.elasticsearch, settings.services.embeddings.dimensions)
        try:
            count = es.count_revision(work.document_id, work.revision_id, active=False)
        finally:
            es.close()
        expected = len(work.chunks)
        if count != expected:
            raise RuntimeError(f"Revisão incompleta no Elasticsearch. Esperado {expected}, encontrado {count}.")
        return StepResult(
            output=work,
            has_output=True,
            text="Revisão validada no Elasticsearch.",
            metrics={"chunks_validated": count},
        )


class PublishRevisionStep(PipelineStep):
    def execute(self, input: WorkItem, context: Any) -> StepResult:
        work = input
        if work.noop:
            return StepResult(
                output=work.final_result,
                has_output=True,
                text="Indexação concluída sem alterações.",
                metrics={"published": 0, "noop": 1},
                metadata={"document_id": work.document_id, "revision_id": work.revision_id},
            )

        settings = load_context_settings(context)

        if work.metadata_only:
            es = ElasticsearchClient(settings.services.elasticsearch, settings.services.embeddings.dimensions)
            now = datetime.now(timezone.utc).isoformat()
            try:
                active_count = es.count_revision(work.document_id, work.revision_id, active=True)
                if active_count <= 0:
                    raise RuntimeError("Documento sem chunks ativos para atualização de metadados.")
                updated_chunks = es.update_active_chunks_metadata(work.document_id, work.request.metadata)
                if updated_chunks != active_count:
                    raise RuntimeError(
                        f"Atualização de metadados incompleta. Esperado {active_count}, atualizado {updated_chunks}."
                    )
                document = dict(work.existing_document or {})
                document["metadata"] = work.request.metadata
                document["updated_at"] = now
                es.put_document(work.document_id, document)
            finally:
                es.close()
            work.source_bytes = None
            work.final_result = {
                "action": "metadata_updated",
                "document_id": work.document_id,
                "revision_id": work.revision_id,
                "chunks": active_count,
            }
            return StepResult(
                output=work.final_result,
                has_output=True,
                text="Metadados atualizados sem reprocessamento do documento.",
                metrics={"metadata_updated": 1, "chunks_updated": updated_chunks},
                metadata={"document_id": work.document_id, "revision_id": work.revision_id},
            )

        es = ElasticsearchClient(settings.services.elasticsearch, settings.services.embeddings.dimensions)
        now = datetime.now(timezone.utc).isoformat()
        previous_created_at = (work.existing_document or {}).get("created_at") or now
        try:
            es.switch_active_revision(work.document_id, work.revision_id)
            active_target = es.count_revision(work.document_id, work.revision_id, active=True)
            active_others = es.count_active_other_revisions(work.document_id, work.revision_id)
            if active_target != len(work.chunks) or active_others != 0:
                raise RuntimeError(
                    "Publicação inconsistente no Elasticsearch. "
                    f"Revisão alvo ativa: {active_target}/{len(work.chunks)}. "
                    f"Chunks ativos de outras revisões: {active_others}."
                )
            title = work.chunks[0].get("title") if work.chunks else work.filename
            document = {
                "document_id": work.document_id,
                "filename": work.filename,
                "title": title,
                "mime_type": work.mime_type,
                "source": {"bucket": work.bucket, "key": work.key, "sha256": work.source_sha256},
                "active_revision": work.revision_id,
                "pipeline_hash": work.pipeline_hash,
                "status": "ready",
                "metadata": work.request.metadata,
                "silver": work.silver,
                "created_at": previous_created_at,
                "updated_at": now,
            }
            es.put_document(work.document_id, document)
        finally:
            es.close()

        work.final_result = {
            "action": "indexed" if work.existing_document is None else "updated",
            "document_id": work.document_id,
            "revision_id": work.revision_id,
            "chunks": len(work.chunks),
            "silver": work.silver,
        }
        return StepResult(
            output=work.final_result,
            has_output=True,
            text="Nova revisão publicada para busca.",
            metrics={"published": 1, "chunks_active": len(work.chunks), "other_active_chunks": 0},
            metadata={"document_id": work.document_id, "revision_id": work.revision_id},
        )

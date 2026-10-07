from __future__ import annotations

import json
import logging
import threading
from contextlib import contextmanager
from time import monotonic
from typing import Any
from urllib.parse import quote

import httpx

from websensors_flow_rag.config import ElasticsearchSettings


logger = logging.getLogger(__name__)


@contextmanager
def _creation_heartbeat(index: str, timeout_seconds: float):
    """Publica batimentos enquanto o Elasticsearch prepara um índice."""
    stop = threading.Event()
    started = monotonic()

    def publish() -> None:
        while not stop.wait(10):
            elapsed = monotonic() - started
            logger.info(
                "Aguardando criação do índice %s. Decorrido %.1fs. Prazo de resposta %.0fs. ETA indisponível",
                index, elapsed, timeout_seconds,
            )

    thread = threading.Thread(target=publish, name="rag-es-index-heartbeat", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1)


class ElasticsearchClient:
    def __init__(self, settings: ElasticsearchSettings, embedding_dimensions: int):
        self.settings = settings
        self.embedding_dimensions = embedding_dimensions
        headers = {"accept": "application/json", "Content-Type": "application/json"}
        auth = None
        if settings.api_key:
            headers["Authorization"] = f"ApiKey {settings.api_key}"
        elif settings.username:
            auth = httpx.BasicAuth(settings.username, settings.password or "")
        verify: bool | str = settings.verify_certs
        if settings.ca_cert:
            verify = settings.ca_cert
        self.client = httpx.Client(
            base_url=settings.endpoint.rstrip("/"),
            timeout=settings.timeout_seconds,
            headers=headers,
            auth=auth,
            verify=verify,
        )

    def close(self) -> None:
        self.client.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        content: str | bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        response = self.client.request(method, path, json=json_body, content=content, headers=headers)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()

    def ping(self) -> bool:
        try:
            response = self.client.get("/")
            return 200 <= response.status_code < 300
        except httpx.HTTPError:
            return False

    def ensure_indices(self) -> None:
        self._ensure_index(self.settings.indices.documents, self._documents_definition())
        self._ensure_index(self.settings.indices.chunks, self._chunks_definition())
        self._ensure_chunk_mapping()
        self._ensure_alias(self.settings.indices.documents, self.settings.aliases.documents)
        self._ensure_alias(self.settings.indices.chunks, self.settings.aliases.chunks)

    def _ensure_index(self, index: str, definition: dict[str, Any]) -> None:
        path = f"/{quote(index, safe='')}"
        response = self.client.head(path)
        if response.status_code == 200:
            return
        if response.status_code != 404:
            response.raise_for_status()

        # A criação de índices pode esperar pela eleição do nó coordenador e
        # pela ativação do shard primário. Seu prazo não deve ser o mesmo
        # utilizado pelas consultas comuns ao Elasticsearch.
        creation_timeout = self.settings.index_creation_timeout_seconds
        server_timeout = max(1, int(creation_timeout - 10))
        request_timeout = httpx.Timeout(
            connect=min(10.0, self.settings.timeout_seconds),
            read=creation_timeout,
            write=self.settings.timeout_seconds,
            pool=self.settings.timeout_seconds,
        )
        logger.info("Criando índice Elasticsearch %s com prazo de %.0f segundos", index, creation_timeout)
        try:
            with _creation_heartbeat(index, creation_timeout):
                created = self.client.put(
                    path,
                    json=definition,
                    params={"timeout": f"{server_timeout}s", "master_timeout": f"{server_timeout}s"},
                    timeout=request_timeout,
                )
        except httpx.TimeoutException as exc:
            # Um timeout de leitura não garante que a criação falhou.
            # Reconsultar o índice evita repetir a operação sobre um índice
            # que foi criado pelo cluster enquanto o cliente aguardava.
            try:
                check = self.client.head(path, timeout=10)
            except httpx.HTTPError:
                check = None
            if check is not None and check.status_code == 200:
                logger.warning("O Elasticsearch não respondeu à criação de %s no prazo, mas o índice existe", index)
                return
            raise RuntimeError(
                f"Tempo esgotado criando índice '{index}' no Elasticsearch. "
                "Verifique /_cluster/health, /_cluster/pending_tasks e os logs do nó. "
                "Aumente services.elasticsearch.index_creation_timeout_seconds no YAML se necessário."
            ) from exc

        if created.status_code == 400:
            # Uma segunda instância da API pode criar o índice entre o HEAD
            # e o PUT. Não aceitar qualquer erro 400, apenas índice existente.
            try:
                error = created.json().get("error", {})
                error_type = error.get("type") if isinstance(error, dict) else None
            except ValueError:
                error_type = None
            if error_type == "resource_already_exists_exception":
                return
        created.raise_for_status()
        details = created.json()
        if not details.get("acknowledged", False):
            check = self.client.head(path, timeout=10)
            if check.status_code != 200:
                raise RuntimeError(
                    f"Elasticsearch não confirmou a criação do índice '{index}'. "
                    "Inspecione /_cluster/health e /_cluster/pending_tasks."
                )
        if not details.get("shards_acknowledged", True):
            logger.warning(
                "Índice %s foi registrado, mas os shards não ficaram prontos dentro do prazo. "
                "Consulte /_cat/shards/%s?v.", index, index
            )

    def _ensure_alias(self, index: str, alias: str) -> None:
        response = self.client.get(f"/_alias/{quote(alias, safe='')}")
        if response.status_code == 200:
            data = response.json()
            targets = set(data) if isinstance(data, dict) else set()
            if targets != {index}:
                raise RuntimeError(
                    f"Alias '{alias}' aponta para {sorted(targets)} e a configuração espera somente '{index}'."
                )
            return
        if response.status_code != 404:
            response.raise_for_status()
        payload = {
            "actions": [
                {
                    "add": {
                        "index": index,
                        "alias": alias,
                        "is_write_index": True,
                    }
                }
            ]
        }
        created = self.client.post("/_aliases", json=payload)
        created.raise_for_status()

    def _ensure_chunk_mapping(self) -> None:
        index = self.settings.indices.chunks
        response = self.client.get(f"/{quote(index, safe='')}/_mapping")
        response.raise_for_status()
        payload = response.json()
        index_mapping = payload.get(index, {}).get("mappings", {}) if isinstance(payload, dict) else {}
        properties = index_mapping.get("properties", {}) if isinstance(index_mapping, dict) else {}
        embedding = properties.get("embedding", {}) if isinstance(properties, dict) else {}
        configured_dims = embedding.get("dims") if isinstance(embedding, dict) else None
        if configured_dims is not None and int(configured_dims) != self.embedding_dimensions:
            raise RuntimeError(
                f"O índice '{index}' usa embedding.dims={configured_dims}, mas o YAML configura "
                f"{self.embedding_dimensions}. Crie um novo índice físico e atualize o alias."
            )
        if "heading_text" not in properties:
            mapping = {
                "properties": {
                    "heading_text": {
                        "type": "text",
                        "fields": {"keyword": {"type": "keyword"}},
                    }
                }
            }
            updated = self.client.put(f"/{quote(index, safe='')}/_mapping", json=mapping)
            updated.raise_for_status()

    def _documents_definition(self) -> dict[str, Any]:
        return {
            "settings": {
                "number_of_shards": self.settings.shards,
                "number_of_replicas": self.settings.replicas,
            },
            "mappings": {
                "dynamic": False,
                "properties": {
                    "document_id": {"type": "keyword"},
                    "filename": {"type": "keyword"},
                    "mime_type": {"type": "keyword"},
                    "title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                    "source": {
                        "properties": {
                            "bucket": {"type": "keyword"},
                            "key": {"type": "keyword"},
                            "sha256": {"type": "keyword"},
                        }
                    },
                    "active_revision": {"type": "keyword"},
                    "pipeline_hash": {"type": "keyword"},
                    "status": {"type": "keyword"},
                    "metadata": {"type": "flattened"},
                    "silver": {"type": "object", "enabled": False},
                    "created_at": {"type": "date"},
                    "updated_at": {"type": "date"},
                },
            },
        }

    def _chunks_definition(self) -> dict[str, Any]:
        return {
            "settings": {
                "number_of_shards": self.settings.shards,
                "number_of_replicas": self.settings.replicas,
            },
            "mappings": {
                "dynamic": False,
                "properties": {
                    "chunk_id": {"type": "keyword"},
                    "document_id": {"type": "keyword"},
                    "revision_id": {"type": "keyword"},
                    "active": {"type": "boolean"},
                    "sequence": {"type": "integer"},
                    "type": {"type": "keyword"},
                    "filename": {"type": "keyword"},
                    "mime_type": {"type": "keyword"},
                    "title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                    "section": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                    "heading_path": {"type": "keyword"},
                    "heading_text": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                    "page_start": {"type": "integer"},
                    "page_end": {"type": "integer"},
                    "content": {"type": "text"},
                    "embedding_text": {"type": "text", "index": False},
                    "embedding": {
                        "type": "dense_vector",
                        "dims": self.embedding_dimensions,
                        "index": True,
                        "similarity": "cosine",
                    },
                    "metadata": {"type": "flattened"},
                    "source": {
                        "properties": {
                            "bucket": {"type": "keyword"},
                            "key": {"type": "keyword"},
                        }
                    },
                    "created_at": {"type": "date"},
                },
            },
        }

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        response = self._request(
            "GET",
            f"/{quote(self.settings.aliases.documents, safe='')}/_doc/{quote(document_id, safe='')}",
        )
        if response is None or not response.get("found", True):
            return None
        return response.get("_source") or {}

    def put_document(self, document_id: str, document: dict[str, Any]) -> None:
        response = self.client.put(
            f"/{quote(self.settings.indices.documents, safe='')}/_doc/{quote(document_id, safe='')}?refresh=wait_for",
            json=document,
        )
        response.raise_for_status()

    def list_documents(self, size: int = 50) -> list[dict[str, Any]]:
        payload = {
            "size": min(max(size, 1), 200),
            "sort": [{"updated_at": {"order": "desc", "unmapped_type": "date"}}],
            "query": {"match_all": {}},
        }
        data = self._request(
            "POST",
            f"/{quote(self.settings.aliases.documents, safe='')}/_search",
            json_body=payload,
        ) or {}
        return [hit.get("_source") or {} for hit in data.get("hits", {}).get("hits", [])]

    def bulk_index_chunks(self, chunks: list[dict[str, Any]]) -> dict[str, Any]:
        if not chunks:
            return {"errors": False, "items": []}
        lines: list[str] = []
        for chunk in chunks:
            lines.append(
                json.dumps(
                    {"index": {"_index": self.settings.indices.chunks, "_id": chunk["chunk_id"]}},
                    ensure_ascii=False,
                )
            )
            lines.append(json.dumps(chunk, ensure_ascii=False, separators=(",", ":")))
        body = "\n".join(lines) + "\n"
        response = self.client.post(
            "/_bulk?refresh=wait_for",
            content=body.encode("utf-8"),
            headers={"Content-Type": "application/x-ndjson", "accept": "application/json"},
        )
        response.raise_for_status()
        data = response.json()
        if data.get("errors"):
            failures = []
            for item in data.get("items", []):
                action = item.get("index") or {}
                if action.get("error"):
                    failures.append(action.get("error"))
            raise RuntimeError(f"Falha no bulk do Elasticsearch: {failures[:3]}")
        return data

    def count_revision(self, document_id: str, revision_id: str, *, active: bool | None = None) -> int:
        filters: list[dict[str, Any]] = [
            {"term": {"document_id": document_id}},
            {"term": {"revision_id": revision_id}},
        ]
        if active is not None:
            filters.append({"term": {"active": active}})
        payload = {"query": {"bool": {"filter": filters}}}
        data = self._request(
            "POST",
            f"/{quote(self.settings.aliases.chunks, safe='')}/_count",
            json_body=payload,
        ) or {}
        return int(data.get("count", 0))

    def count_active_other_revisions(self, document_id: str, revision_id: str) -> int:
        payload = {
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"document_id": document_id}},
                        {"term": {"active": True}},
                    ],
                    "must_not": [{"term": {"revision_id": revision_id}}],
                }
            }
        }
        data = self._request(
            "POST",
            f"/{quote(self.settings.aliases.chunks, safe='')}/_count",
            json_body=payload,
        ) or {}
        return int(data.get("count", 0))

    def delete_staged_revision(self, document_id: str, revision_id: str) -> int:
        payload = {
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"document_id": document_id}},
                        {"term": {"revision_id": revision_id}},
                        {"term": {"active": False}},
                    ]
                }
            }
        }
        data = self._request(
            "POST",
            f"/{quote(self.settings.indices.chunks, safe='')}/_delete_by_query?refresh=true&conflicts=proceed",
            json_body=payload,
        ) or {}
        return int(data.get("deleted", 0))

    def switch_active_revision(self, document_id: str, revision_id: str) -> int:
        payload = {
            "script": {
                "source": "ctx._source.active = (ctx._source.revision_id == params.revision_id)",
                "lang": "painless",
                "params": {"revision_id": revision_id},
            },
            "query": {"term": {"document_id": document_id}},
        }
        data = self._request(
            "POST",
            f"/{quote(self.settings.indices.chunks, safe='')}/_update_by_query?refresh=true&conflicts=proceed",
            json_body=payload,
        ) or {}
        return int(data.get("updated", 0))


    def update_active_chunks_metadata(self, document_id: str, metadata: dict[str, Any]) -> int:
        payload = {
            "script": {
                "source": "ctx._source.metadata = params.metadata",
                "lang": "painless",
                "params": {"metadata": metadata},
            },
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"document_id": document_id}},
                        {"term": {"active": True}},
                    ]
                }
            },
        }
        data = self._request(
            "POST",
            f"/{quote(self.settings.indices.chunks, safe='')}/_update_by_query?refresh=true&conflicts=proceed",
            json_body=payload,
        ) or {}
        return int(data.get("updated", 0))

    def search(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/{quote(self.settings.aliases.chunks, safe='')}/_search",
            json_body=body,
        ) or {}

from __future__ import annotations

from time import perf_counter
from typing import Any

from websensors_flow_rag.clients.elasticsearch_client import ElasticsearchClient
from websensors_flow_rag.clients.model_client import EmbeddingClient
from websensors_flow_rag.config import RAGSettings
from websensors_flow_rag.models import SearchRequest, SearchResponse


class SearchService:
    def __init__(self, settings: RAGSettings):
        self.settings = settings

    def _top_k(self, request: SearchRequest) -> int:
        value = request.top_k or self.settings.search.default_top_k
        if value > self.settings.search.max_top_k:
            raise ValueError(f"top_k={value} excede search.max_top_k={self.settings.search.max_top_k}.")
        return value

    @staticmethod
    def _filter_field(key: str) -> str:
        known = {
            "document_id": "document_id", "revision_id": "revision_id",
            "filename": "filename", "mime_type": "mime_type",
            "title": "title.keyword", "section": "section.keyword",
            "type": "type", "heading_path": "heading_path",
            "page_start": "page_start", "page_end": "page_end",
            "source.bucket": "source.bucket", "source.key": "source.key",
        }
        if key in known:
            return known[key]
        if key.startswith("metadata."):
            return key
        return f"metadata.{key}"

    def _filters(self, request: SearchRequest) -> list[dict[str, Any]]:
        filters: list[dict[str, Any]] = [{"term": {"active": True}}]
        for key, value in request.filters.items():
            field = self._filter_field(key)
            if isinstance(value, list):
                if not value:
                    filters.append({"match_none": {}})
                else:
                    filters.append({"terms": {field: value}})
            else:
                filters.append({"term": {field: value}})
        return filters

    def _lexical_query(self, request: SearchRequest) -> dict[str, Any]:
        return {
            "bool": {
                "must": [{"multi_match": {
                    "query": request.query,
                    "fields": self.settings.search.lexical.fields,
                    "type": "best_fields",
                }}],
                "filter": self._filters(request),
            }
        }

    def _embed_query(self, query: str) -> list[float]:
        client = EmbeddingClient(self.settings.services.embeddings)
        try:
            return client.embed([query])[0]
        finally:
            client.close()

    def _bm25_body(self, request: SearchRequest, size: int) -> dict[str, Any]:
        return {
            "size": size,
            "query": self._lexical_query(request),
            "_source": {"excludes": ["embedding", "embedding_text"]},
        }

    def _semantic_body(self, request: SearchRequest, vector: list[float], size: int) -> dict[str, Any]:
        return {
            "size": size,
            "knn": {
                "field": "embedding",
                "query_vector": vector,
                "k": size,
                "num_candidates": max(
                    size,
                    self.settings.search.semantic.candidates,
                    self.settings.search.semantic.num_candidates,
                ),
                "filter": {"bool": {"filter": self._filters(request)}},
            },
            "_source": {"excludes": ["embedding", "embedding_text"]},
        }

    @staticmethod
    def _hit_key(hit: dict[str, Any]) -> str:
        source = hit.get("_source") or {}
        return str(hit.get("_id") or source.get("chunk_id") or "")

    def _rrf_fuse(
        self,
        lexical_hits: list[dict[str, Any]],
        semantic_hits: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rank_constant = self.settings.search.hybrid.rank_constant
        merged: dict[str, dict[str, Any]] = {}

        def add_hits(hits: list[dict[str, Any]], component: str) -> None:
            for rank, hit in enumerate(hits, start=1):
                key = self._hit_key(hit)
                if not key:
                    continue
                entry = merged.setdefault(
                    key,
                    {
                        "hit": hit,
                        "rrf_score": 0.0,
                        "bm25_rank": None,
                        "semantic_rank": None,
                        "bm25_score": None,
                        "semantic_score": None,
                    },
                )
                entry["rrf_score"] += 1.0 / (rank_constant + rank)
                entry[f"{component}_rank"] = rank
                entry[f"{component}_score"] = hit.get("_score")

        add_hits(lexical_hits, "bm25")
        add_hits(semantic_hits, "semantic")

        ordered = sorted(
            merged.values(),
            key=lambda item: (
                -item["rrf_score"],
                item["bm25_rank"] if item["bm25_rank"] is not None else 10**9,
                item["semantic_rank"] if item["semantic_rank"] is not None else 10**9,
                self._hit_key(item["hit"]),
            ),
        )

        fused: list[dict[str, Any]] = []
        for item in ordered:
            hit = dict(item["hit"])
            hit["_score"] = item["rrf_score"]
            hit["_rrf"] = {
                "bm25_rank": item["bm25_rank"],
                "semantic_rank": item["semantic_rank"],
                "bm25_score": item["bm25_score"],
                "semantic_score": item["semantic_score"],
            }
            fused.append(hit)
        return fused

    @staticmethod
    def _source_to_hit(hit: dict[str, Any], rank: int) -> dict[str, Any]:
        source = hit.get("_source") or {}
        return {
            "rank": rank,
            "document_id": source.get("document_id", ""),
            "chunk_id": source.get("chunk_id", hit.get("_id", "")),
            "revision_id": source.get("revision_id", ""),
            "filename": source.get("filename"),
            "title": source.get("title"),
            "section": source.get("section"),
            "heading_path": source.get("heading_path") or [],
            "page_start": source.get("page_start"),
            "page_end": source.get("page_end"),
            "content": source.get("content", ""),
            "score": hit.get("_score"),
            "metadata": source.get("metadata") or {},
            "source": source.get("source") or {},
        }

    @staticmethod
    def _deduplicate(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[tuple[str, str]] = set()
        output: list[dict[str, Any]] = []
        for hit in hits:
            source = hit.get("_source") or {}
            key = (source.get("document_id", ""), source.get("content", ""))
            if key in seen:
                continue
            seen.add(key)
            output.append(hit)
        return output

    def _response(self, request: SearchRequest, mode: str, started: float, hits: list[dict[str, Any]], debug: dict[str, Any] | None = None) -> SearchResponse:
        top_k = self._top_k(request)
        hits = self._deduplicate(hits)[:top_k]
        return SearchResponse(
            query=request.query, mode=mode,
            took_ms=round((perf_counter() - started) * 1000, 3),
            count=len(hits),
            results=[self._source_to_hit(hit, rank=i) for i, hit in enumerate(hits, start=1)],
            debug=debug if request.debug else None,
        )

    def bm25(self, request: SearchRequest) -> SearchResponse:
        started = perf_counter(); top_k = self._top_k(request)
        body = self._bm25_body(request, top_k)
        es = ElasticsearchClient(self.settings.services.elasticsearch, self.settings.services.embeddings.dimensions)
        try: data = es.search(body)
        finally: es.close()
        return self._response(request, "bm25", started, data.get("hits", {}).get("hits", []), {"engine": "elasticsearch", "retrieval": "bm25", "elasticsearch_took_ms": data.get("took")})

    def semantic(self, request: SearchRequest) -> SearchResponse:
        started = perf_counter(); top_k = self._top_k(request); vector = self._embed_query(request.query)
        body = self._semantic_body(request, vector, top_k)
        es = ElasticsearchClient(self.settings.services.elasticsearch, self.settings.services.embeddings.dimensions)
        try: data = es.search(body)
        finally: es.close()
        return self._response(request, "semantic", started, data.get("hits", {}).get("hits", []), {"engine": "elasticsearch", "retrieval": "knn", "elasticsearch_took_ms": data.get("took")})

    def hybrid(self, request: SearchRequest) -> SearchResponse:
        started = perf_counter()
        top_k = self._top_k(request)
        window = max(top_k, self.settings.search.hybrid.rank_window_size)
        vector = self._embed_query(request.query)

        lexical_body = self._bm25_body(request, window)
        semantic_body = self._semantic_body(request, vector, window)

        es = ElasticsearchClient(self.settings.services.elasticsearch, self.settings.services.embeddings.dimensions)
        try:
            lexical_data = es.search(lexical_body)
            semantic_data = es.search(semantic_body)
        finally:
            es.close()

        lexical_hits = lexical_data.get("hits", {}).get("hits", [])
        semantic_hits = semantic_data.get("hits", {}).get("hits", [])
        fusion_started = perf_counter()
        fused_hits = self._rrf_fuse(lexical_hits, semantic_hits)
        fusion_ms = round((perf_counter() - fusion_started) * 1000, 3)

        debug = {
            "engine": "elasticsearch+application",
            "retrieval": "rrf",
            "fusion": "application",
            "components": ["bm25", "knn"],
            "rank_window_size": window,
            "rank_constant": self.settings.search.hybrid.rank_constant,
            "bm25_candidates": len(lexical_hits),
            "semantic_candidates": len(semantic_hits),
            "bm25_elasticsearch_took_ms": lexical_data.get("took"),
            "semantic_elasticsearch_took_ms": semantic_data.get("took"),
            "fusion_took_ms": fusion_ms,
        }
        return self._response(request, "hybrid", started, fused_hits, debug)

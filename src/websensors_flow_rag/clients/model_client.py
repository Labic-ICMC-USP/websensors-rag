from __future__ import annotations

import httpx

from websensors_flow_rag.config import EmbeddingSettings


def _headers(api_key: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


class EmbeddingClient:
    def __init__(self, settings: EmbeddingSettings):
        self.settings = settings
        self.client = httpx.Client(timeout=settings.timeout_seconds, headers=_headers(settings.api_key))

    def close(self) -> None:
        self.client.close()


    def ping(self) -> bool:
        try:
            endpoint = self.settings.endpoint.rstrip("/")
            response = self.client.get(f"{endpoint}/models")
            return 200 <= response.status_code < 300
        except httpx.HTTPError:
            return False

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        request_payload = {"model": self.settings.model, "input": texts}
        if self.settings.truncate_prompt_tokens is not None:
            request_payload["truncate_prompt_tokens"] = self.settings.truncate_prompt_tokens
        response = self.client.post(
            f"{self.settings.endpoint.rstrip('/')}/{self.settings.path.lstrip('/')}",
            json=request_payload,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") or []
        ordered = sorted(data, key=lambda item: int(item.get("index", 0)))
        vectors = [item.get("embedding") for item in ordered]
        if len(vectors) != len(texts):
            raise RuntimeError("O serviço de embeddings retornou quantidade inesperada de vetores.")
        for vector in vectors:
            if not isinstance(vector, list) or len(vector) != self.settings.dimensions:
                raise RuntimeError(
                    f"Dimensão de embedding incompatível. Esperado {self.settings.dimensions}."
                )
        return vectors

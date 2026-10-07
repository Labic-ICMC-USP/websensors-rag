from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import httpx

from websensors_flow_rag.config import DoclingSettings


class DoclingClient:
    def __init__(self, settings: DoclingSettings):
        self.settings = settings
        self.base_url = settings.endpoint.rstrip("/")
        headers: dict[str, str] = {"accept": "application/json"}
        if settings.api_key:
            headers["Authorization"] = f"Bearer {settings.api_key}"
            headers["X-Api-Key"] = settings.api_key
        self.client = httpx.Client(timeout=settings.timeout_seconds, headers=headers)

    def close(self) -> None:
        self.client.close()


    def ready(self) -> bool:
        try:
            response = self.client.get(f"{self.base_url}/ready")
            return 200 <= response.status_code < 300
        except httpx.HTTPError:
            return False

    def health(self) -> bool:
        try:
            response = self.client.get(f"{self.base_url}/health")
            return 200 <= response.status_code < 300
        except httpx.HTTPError:
            return False

    def convert(
        self, filename: str, content: bytes, mime_type: str,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        multipart: list[tuple[str, Any]] = [
            ("files", (filename, content, mime_type)),
            ("to_formats", (None, "md")),
            ("to_formats", (None, "json")),
        ]
        for key, value in self.settings.options.items():
            if key == "to_formats" or value is None:
                continue
            values = value if isinstance(value, list) else [value]
            for item in values:
                if isinstance(item, bool):
                    item = "true" if item else "false"
                elif isinstance(item, (dict, list)):
                    item = json.dumps(item, ensure_ascii=False)
                else:
                    item = str(item)
                multipart.append((key, (None, item)))

        response = self.client.post(f"{self.base_url}/v1/convert/file/async", files=multipart)
        response.raise_for_status()
        task = response.json()
        task_id = task.get("task_id")
        if not task_id:
            raise RuntimeError(f"Docling não retornou task_id: {task}")

        started = time.monotonic()
        deadline = started + self.settings.timeout_seconds
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Tempo limite excedido no Docling para a tarefa {task_id}.")
            status_response = self.client.get(f"{self.base_url}/v1/status/poll/{task_id}")
            status_response.raise_for_status()
            status = status_response.json()
            task_status = str(status.get("task_status") or status.get("status") or "").lower()
            if progress_callback is not None:
                elapsed = time.monotonic() - started
                raw_percent = status.get("progress") or status.get("progress_percent")
                try:
                    percent = float(raw_percent) if raw_percent is not None else None
                    if percent is not None and 0 < percent <= 1:
                        percent *= 100
                    if percent is not None and not (0 <= percent <= 100):
                        percent = None
                except (TypeError, ValueError):
                    percent = None
                eta = elapsed * (100 - percent) / percent if percent and percent < 100 else (0.0 if percent == 100 else None)
                progress_callback({
                    "task_id": task_id, "status": task_status,
                    "elapsed_seconds": round(elapsed, 1),
                    "percent": percent, "eta_seconds": round(eta, 1) if eta is not None else None,
                })
            if task_status in {"success", "completed", "done"}:
                break
            if task_status in {"failure", "failed", "error"}:
                raise RuntimeError(f"Falha no Docling: {status}")
            time.sleep(self.settings.poll_interval_seconds)

        result_response = self.client.get(f"{self.base_url}/v1/result/{task_id}")
        result_response.raise_for_status()
        return self.normalize_result(result_response.json())

    @staticmethod
    def normalize_result(payload: dict[str, Any]) -> dict[str, Any]:
        document = payload.get("document")
        if document is None:
            documents = payload.get("documents")
            if isinstance(documents, list) and documents:
                first = documents[0]
                document = first.get("document", first) if isinstance(first, dict) else {}
            else:
                document = payload

        if not isinstance(document, dict):
            raise RuntimeError("Resposta do Docling sem documento estruturado.")

        markdown = document.get("md_content") or document.get("markdown") or ""
        json_content = document.get("json_content") or document.get("json") or {}
        if isinstance(json_content, str):
            try:
                json_content = json.loads(json_content)
            except json.JSONDecodeError:
                json_content = {"raw": json_content}

        if not isinstance(json_content, dict):
            json_content = {"content": json_content}

        return {
            "markdown": str(markdown),
            "json": json_content,
            "status": payload.get("status", "success"),
            "processing_time": payload.get("processing_time"),
            "timings": payload.get("timings") or {},
            "errors": payload.get("errors") or [],
        }

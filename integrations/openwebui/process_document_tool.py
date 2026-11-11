"""
title: Processamento documental WebSensors-RAG
author: WebSensors
version: 0.2.1
requirements: httpx>=0.27,pydantic>=2
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time

import httpx
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        RAG_API_URL: str = Field(default="http://host.docker.internal:8000")
        RAG_API_KEY: str = Field(default="", json_schema_extra={"input": {"type": "password"}})
        PROJECT: str = "fai"
        MAX_FILE_BYTES: int = Field(default=50 * 1024 * 1024, ge=1)
        POLL_INTERVAL_SECONDS: float = Field(default=2, gt=0)
        WAIT_SECONDS: float = Field(default=900, gt=0)

    def __init__(self):
        self.valves = self.Valves()

    async def processar_documento(self, file_id: str = "", __files__: list | None = None, __request__=None, __event_emitter__=None) -> str:
        """Processar novamente um anexo desta conversa no projeto configurado.

        Executa nova classificação, extração e indexação a cada chamada, mantendo
        apenas os artefatos Docling em cache. Se houver vários anexos, informe o ID desejado.
        """
        candidates = {}
        for entry in __files__ or []:
            file = entry.get("file") or entry
            identifier = file.get("id") or entry.get("id")
            if isinstance(identifier, str) and re.fullmatch(r"[0-9a-fA-F-]{36}", identifier):
                candidates[identifier] = file
        if not file_id:
            if len(candidates) != 1:
                return "Selecione um único anexo ou informe o ID de um dos arquivos anexados à conversa."
            file_id = next(iter(candidates))
        if file_id not in candidates:
            return "O arquivo solicitado não está entre os anexos desta conversa."
        if __request__ is None:
            return "A versão/configuração do OpenWebUI não disponibilizou o contexto da requisição."
        if not self.valves.RAG_API_KEY:
            return "Configure RAG_API_KEY nas Valves antes de processar documentos."
        # Reutilizar a identidade da requisição somente dentro do próprio OpenWebUI.
        auth = __request__.headers.get("authorization")
        cookie = __request__.headers.get("cookie")
        headers = {"Authorization": auth} if auth else ({"Cookie": cookie} if cookie else {})
        if not headers:
            return "A autenticação do usuário não está disponível para recuperar o original."

        async def emit(description, done=False):
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": description, "done": done}})

        await emit("Recuperando o arquivo original com a permissão do usuário.")
        try:
            transport = httpx.ASGITransport(app=__request__.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://localhost", headers=headers, timeout=120) as webui:
                metadata_response = await webui.get(f"/api/v1/files/{file_id}")
                metadata_response.raise_for_status()
                metadata = metadata_response.json()
                processing_status = (metadata.get("data") or {}).get("status")
                if processing_status in {"pending", "processing"}:
                    return "O upload ainda está sendo processado. Aguarde sua conclusão e acione a Tool novamente."
                if processing_status == "failed":
                    return "O processamento do anexo no OpenWebUI falhou. Confira o extrator antes de continuar."
                if (metadata.get("meta") or {}).get("size", 0) > self.valves.MAX_FILE_BYTES:
                    return "Arquivo excede o limite de tamanho configurado."
                original = await webui.get(f"/api/v1/files/{file_id}/content")
                original.raise_for_status()
            content = original.content
            if not content or len(content) > self.valves.MAX_FILE_BYTES:
                return "Arquivo vazio ou acima do limite configurado."
            expected = (metadata.get("meta") or {}).get("file_hash")
            if expected and expected != hashlib.sha256(content).hexdigest():
                return "O arquivo recuperado não corresponde ao hash registrado no OpenWebUI."
            filename = metadata.get("filename") or (metadata.get("meta") or {}).get("name") or "documento"
            await emit("Iniciando nova classificação, extração e embeddings; conversão Docling em cache.")
            rag_headers = {"Authorization": f"Bearer {self.valves.RAG_API_KEY}"}
            async with httpx.AsyncClient(base_url=self.valves.RAG_API_URL.rstrip("/"), headers=rag_headers, timeout=120) as rag:
                response = await rag.post(
                    "/api/v1/documents/process",
                    files={"file": (filename, content, (metadata.get("meta") or {}).get("content_type", "application/octet-stream"))},
                    data={"project": self.valves.PROJECT, "metadata": json.dumps({"openwebui_file_id": file_id}), "require_cached_artifacts": "true", "force": "true"},
                )
                if response.status_code == 409:
                    return "O original está disponível, mas falta o JSON estrutural Docling no RAG. Configure o extrator externo WebSensors-RAG antes de anexar o documento; a Tool não fará uma segunda conversão silenciosa."
                response.raise_for_status()
                token = response.json()["token"]
                if not re.fullmatch(r"[0-9a-f]{32}", token):
                    return "O RAG retornou um identificador de execução inválido."
                deadline = time.monotonic() + self.valves.WAIT_SECONDS
                while time.monotonic() < deadline:
                    status_response = await rag.get(f"/api/v1/jobs/{token}")
                    status_response.raise_for_status()
                    job = status_response.json()
                    if job["terminal"]:
                        await emit("Processamento concluído." if job["status"] == "success" else "Processamento encerrado com falha.", True)
                        return json.dumps(job, ensure_ascii=False, indent=2)
                    await asyncio.sleep(self.valves.POLL_INTERVAL_SECONDS)
                await emit("Execução continua no RAG; prazo de espera da Tool encerrado.", True)
                return json.dumps({"token": token, "status": "running", "status_url": f"/api/v1/jobs/{token}"})
        except httpx.HTTPStatusError as exc:
            await emit("Falha de comunicação ou permissão.", True)
            return f"Falha HTTP {exc.response.status_code}. Verifique acesso ao arquivo e configuração da API RAG."
        except httpx.HTTPError:
            await emit("Serviço indisponível.", True)
            return "Falha de conexão ou tempo limite; consulte o processamento no RAG antes de reenviar."


    async def consultar_processamento(self, token: str) -> str:
        """Consultar uma execução já iniciada por esta integração, sem reenviar o anexo."""
        if not re.fullmatch(r"[0-9a-f]{32}", token):
            return "Identificador de execução inválido."
        if not self.valves.RAG_API_KEY:
            return "Configure RAG_API_KEY nas Valves."
        try:
            async with httpx.AsyncClient(base_url=self.valves.RAG_API_URL.rstrip("/"), headers={"Authorization": f"Bearer {self.valves.RAG_API_KEY}"}, timeout=30) as rag:
                response = await rag.get(f"/api/v1/jobs/{token}")
                response.raise_for_status()
                return json.dumps(response.json(), ensure_ascii=False, indent=2)
        except httpx.HTTPStatusError as exc:
            return f"Consulta retornou HTTP {exc.response.status_code}."
        except httpx.HTTPError:
            return "Não foi possível consultar a execução agora. Preserve o identificador e tente novamente."

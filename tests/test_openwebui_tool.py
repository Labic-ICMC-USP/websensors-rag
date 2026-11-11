import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response, JSONResponse


spec = importlib.util.spec_from_file_location('document_tool', Path(__file__).parents[1] / 'integrations/openwebui/process_document_tool.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
FILE_ID = 'bdcaffd8-a121-489f-a3f2-de20aef83f07'


def test_tool_retrieves_original_with_user_permission_and_separates_tokens(monkeypatch):
    webui, rag = FastAPI(), FastAPI()
    content = b'%PDF-original'
    calls = []

    @webui.get('/api/v1/files/{file_id}')
    async def metadata(file_id: str, request: Request):
        assert request.headers['authorization'] == 'Bearer user-token'
        assert file_id == FILE_ID
        return {'filename': 'ficha.pdf', 'meta': {'size': len(content), 'file_hash': hashlib.sha256(content).hexdigest(), 'content_type': 'application/pdf'}}

    @webui.get('/api/v1/files/{file_id}/content')
    async def original(file_id: str, request: Request):
        assert request.headers['authorization'] == 'Bearer user-token'
        return Response(content, media_type='application/pdf')

    @rag.post('/api/v1/documents/process')
    async def process(request: Request):
        assert request.headers['authorization'] == 'Bearer rag-token'
        form = await request.form()
        assert await form['file'].read() == content
        assert form['project'] == 'fai'
        assert form['require_cached_artifacts'] == 'true'
        assert form['force'] == 'true'
        calls.append('submit')
        return {'token': 'a' * 32}

    @rag.get('/api/v1/jobs/{token}')
    async def job(token: str):
        calls.append('poll')
        return {'token': token, 'terminal': True, 'status': 'success', 'result': {'document_id': 'document'}}

    real_client = httpx.AsyncClient
    def client(**kwargs):
        if 'transport' not in kwargs: kwargs['transport'] = httpx.ASGITransport(app=rag)
        return real_client(**kwargs)
    monkeypatch.setattr(module.httpx, 'AsyncClient', client)
    tool = module.Tools(); tool.valves.RAG_API_KEY = 'rag-token'
    result = asyncio.run(tool.processar_documento(__files__=[{'file': {'id': FILE_ID}}], __request__=SimpleNamespace(app=webui, headers={'authorization': 'Bearer user-token'})))
    assert json.loads(result)['status'] == 'success'
    assert calls == ['submit', 'poll']
    assert 'user-token' not in result and 'rag-token' not in result


def test_tool_rejects_file_outside_current_attachments():
    tool = module.Tools()
    result = asyncio.run(tool.processar_documento(file_id=FILE_ID, __files__=[]))
    assert 'não está entre os anexos' in result


def test_tool_preserves_file_access_denial(monkeypatch):
    webui = FastAPI()
    @webui.get('/api/v1/files/{file_id}')
    async def denied(file_id: str): return JSONResponse(status_code=403, content={'detail': 'denied'})
    tool = module.Tools(); tool.valves.RAG_API_KEY = 'rag-token'
    result = asyncio.run(tool.processar_documento(__files__=[{'id': FILE_ID}], __request__=SimpleNamespace(app=webui, headers={'authorization': 'Bearer user-token'})))
    assert 'HTTP 403' in result

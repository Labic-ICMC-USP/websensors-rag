"""Chat OpenAI-compatible com retries limitados e erros sem conteúdo sensível."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

import httpx


class LLMError(RuntimeError):
    pass


class LLMResponseError(LLMError):
    """Resposta recebida, mas sem objeto JSON válido; não inclui seu conteúdo."""


@dataclass(frozen=True)
class ChatResult:
    data: dict
    retry_count: int
    usage: dict


class LLMClient:
    def __init__(self, *, endpoint: str, model: str, api_key: str, timeout_seconds: float = 120,
                 temperature: float = 0, max_tokens: int = 2048, retries: int = 2,
                 transport=None):
        if not model.strip() or not api_key:
            raise ValueError("Modelo e chave de chat são obrigatórios.")
        if not 0 <= retries <= 5:
            raise ValueError("retries deve estar entre 0 e 5.")
        self.model, self.temperature, self.max_tokens, self.retries = model, temperature, max_tokens, retries
        self.client = httpx.Client(base_url=endpoint.rstrip('/')+'/', timeout=timeout_seconds,
                                  headers={'Authorization': f'Bearer {api_key}'}, transport=transport)

    def close(self):
        self.client.close()

    def complete_json(self, *, system: str, user: str, schema: dict | None = None) -> ChatResult:
        payload = {'model': self.model, 'messages': [{'role':'system','content':system}, {'role':'user','content':user}],
                   'temperature':self.temperature, 'max_tokens':self.max_tokens,
                   'response_format': {'type':'json_schema','json_schema':{'name':'document_result','strict':True,'schema':schema}} if schema else {'type':'json_object'}}
        for attempt in range(self.retries + 1):
            try:
                response = self.client.post('chat/completions', json=payload)
            except httpx.TransportError:
                if attempt < self.retries:
                    time.sleep(min(2 ** attempt, 4)); continue
                raise LLMError("Tempo limite ou falha de conexão com o provedor LLM.") from None
            if response.status_code in {408,429,500,502,503,504} and attempt < self.retries:
                time.sleep(min(2 ** attempt, 4)); continue
            if response.is_error:
                raise LLMError(f"Provedor LLM retornou HTTP {response.status_code}.")
            try:
                body = response.json()
                choice = body['choices'][0]
                if choice.get('finish_reason') != 'stop':
                    reason = choice.get('finish_reason')
                    reason = reason if isinstance(reason, str) and reason in {'length','content_filter','tool_calls','function_call','error'} else 'unknown'
                    usage = body.get('usage', {})
                    completion_tokens = usage.get('completion_tokens') if isinstance(usage, dict) else None
                    completion_tokens = completion_tokens if type(completion_tokens) is int else 'unknown'
                    content = choice.get('message', {}).get('content')
                    output_chars = len(content) if isinstance(content, str) else 0
                    raise LLMError(f"Resposta LLM incompleta ou interrompida; finish_reason={reason}; max_tokens={self.max_tokens}; completion_tokens={completion_tokens}; output_chars={output_chars}; revisão necessária.")
                data = json.loads(choice['message']['content'])
                if not isinstance(data, dict): raise ValueError()
                usage = {key:value for key,value in body.get('usage',{}).items() if key in {'prompt_tokens','completion_tokens','total_tokens'} and isinstance(value,int)}
                return ChatResult(data=data, retry_count=attempt, usage=usage)
            except (ValueError,KeyError,IndexError,TypeError):
                raise LLMResponseError("Resposta LLM inválida; esperado objeto JSON completo.") from None
        raise LLMError("Tentativas LLM esgotadas.")

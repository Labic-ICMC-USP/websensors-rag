from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

from jsonschema import Draft202012Validator

from websensors_flow_rag.clients.llm_client import LLMResponseError


class ExtractionValidationError(ValueError):
    """Erro sem cópia do documento ou da resposta inválida."""


def load_extraction_resources(projects_dir: Path, project: str, document_type: str):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', project) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', document_type):
        raise ValueError('Projeto ou tipo documental inválido.')
    root = projects_dir.resolve()
    directory = (root / project / 'document_types' / document_type).resolve()
    if not directory.is_relative_to(root):
        raise ValueError('Recursos fora do diretório de projetos.')
    prompt = (directory / 'prompt.md').read_text(encoding='utf-8')
    schema_text = (directory / 'schema.json').read_text(encoding='utf-8')
    schema = json.loads(schema_text)
    Draft202012Validator.check_schema(schema)
    if not prompt.strip(): raise ValueError('Prompt de extração vazio.')
    return prompt, schema, {'prompt_version':hashlib.sha256(prompt.encode()).hexdigest(), 'schema_version':hashlib.sha256(schema_text.encode()).hexdigest()}


def _normalize(text):
    return ' '.join(unicodedata.normalize('NFC', text).split())


_FORMAT_TOKEN = re.compile(r'^(?:#{1,6}|[-*+•]|\*\*|[a-zA-Z]\)|\(?[ivxIVX]{1,4}\))$')


def _relaxed(text):
    """Remove apenas sintaxe Markdown (tabelas, títulos, marcadores soltos de lista).

    O Docling pode intercalar marcadores como ``b)`` no meio de uma frase ou separar
    células por ``|``; as palavras e sua ordem continuam obrigatórias.
    """
    text = unicodedata.normalize('NFC', text).replace('|', ' ')
    text = re.sub(r'-{3,}', ' ', text).replace('**', ' ')
    return ' '.join(token for token in text.split() if not _FORMAT_TOKEN.fullmatch(token))


def has_value(value):
    if isinstance(value, dict): return any(has_value(v) for v in value.values())
    if isinstance(value, list): return any(has_value(v) for v in value)
    return value is not None and value != ''


def _schema_problem(error) -> str:
    """Descreve o erro com caminho e nomes do schema, sem repetir valores do documento."""
    path = '.'.join(str(part) for part in error.absolute_path) or 'raiz'
    rule = error.validator
    if rule == 'additionalProperties' and isinstance(error.instance, dict):
        extras = sorted(str(key)[:40] for key in set(error.instance) - set(error.schema.get('properties', {})))
        allowed = sorted(error.schema.get('properties', {}))
        return f"{path}: propriedades não permitidas {extras}; use somente {allowed}"
    if rule == 'required' and isinstance(error.instance, dict):
        return f"{path}: faltam as propriedades obrigatórias {[k for k in error.validator_value if k not in error.instance]}"
    if rule in {'type', 'enum', 'minimum', 'minLength'}:
        return f"{path}: valor fora da regra {rule} (esperado {error.validator_value!r})"
    return f"{path}: regra {rule}"


def validate_extraction(data, schema, markdown, valid_pages):
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: [str(p) for p in e.absolute_path])
    if errors:
        details = '; '.join(_schema_problem(error) for error in errors[:5])
        more = f' (+{len(errors) - 5} erro(s))' if len(errors) > 5 else ''
        raise ExtractionValidationError(f'Resposta incompatível com schema: {details}{more}.')
    text = _normalize(markdown)
    relaxed_text = None
    problems = []
    for index, source in enumerate(data['sources']):
        quote = _normalize(source['quote'])
        literal = bool(quote) and quote in text
        if not literal and quote:
            relaxed_text = relaxed_text if relaxed_text is not None else _relaxed(markdown)
            relaxed_quote = _relaxed(source['quote'])
            literal = bool(relaxed_quote) and relaxed_quote in relaxed_text
        if not literal:
            problems.append(f"sources[{index}].quote (campo {source['field']}): evidência não corresponde a trecho literal do documento")
        if source['page'] is not None and source['page'] not in valid_pages:
            problems.append(f'sources[{index}].page: página não disponível no documento')
    if problems:
        raise ExtractionValidationError('; '.join(problems))
    return data


def extract_structured_data(client, *, markdown, document_type, projects_dir, project, valid_pages=(), structured_output=True):
    prompt, schema, metadata = load_extraction_resources(projects_dir,project,document_type)
    payload = {'document_type':document_type,'document_markdown':markdown,'valid_page_numbers':sorted(valid_pages)}
    if not structured_output:
        payload['output_schema'] = schema
    # Metadados de schema não são necessários ao provedor; toda a estrutura é preservada.
    provider_schema = {k:v for k,v in schema.items() if k not in {'$schema','title'}}
    transport_retries = 0
    usage = {}
    for correction in range(2):
        result = None
        try:
            result = client.complete_json(system=prompt,user=json.dumps(payload,ensure_ascii=False),schema=provider_schema if structured_output else None)
            transport_retries += result.retry_count
            for key,value in getattr(result,'usage',{}).items(): usage[key] = usage.get(key,0) + value
            value = validate_extraction(result.data,schema,markdown,set(valid_pages))
            populated = {key for key,item in value['data'].items() if has_value(item)}
            sourced = {source['field'] for source in value['sources']}
            warnings = list(value['warnings'])
            if populated - sourced:
                warnings.append('Campos preenchidos sem evidência explícita: '+', '.join(sorted(populated-sourced)))
            if not populated: warnings.append('Nenhuma informação estruturada identificada; revisão necessária.')
            return {**value,'warnings':warnings}, {**metadata,'retry_count':transport_retries,'correction_count':correction,'usage':usage,'fields_count':len(populated),'needs_review':bool(warnings)}
        except (LLMResponseError,ExtractionValidationError) as exc:
            if correction == 1:
                raise ExtractionValidationError(f'Extração inválida após uma tentativa de correção; revisão necessária. Motivo: {exc}') from None
            payload['correction_instruction'] = str(exc)+' Corrija todos os itens indicados e revise as demais evidências. Cada quote deve ser um trecho curto e contínuo copiado do Markdown, preservando pontuação e marcação; não concatene trechos nem parafraseie. Se não houver evidência literal, remova a fonte e registre aviso. Não invente ou complete dados.'
            if result is not None: payload['previous_response'] = result.data
    raise ExtractionValidationError('Extração não concluída.')

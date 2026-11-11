from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


def load_classification_resources(projects_dir: Path, project: str):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', project):
        raise ValueError('Projeto inválido para classificação.')
    base = projects_dir.resolve()
    directory = (base / project / 'classification').resolve()
    if not directory.is_relative_to(base):
        raise ValueError('Recursos fora do diretório de projetos.')
    categories_text = (directory / 'categories.json').read_text(encoding='utf-8')
    categories = json.loads(categories_text)
    prompt = (directory / 'prompt.md').read_text(encoding='utf-8')
    if not isinstance(categories, dict) or 'outro' not in categories or not all(isinstance(k,str) and isinstance(v,str) and k and v for k,v in categories.items()):
        raise ValueError('Categorias inválidas; é obrigatório definir outro.')
    if not prompt.strip(): raise ValueError('Prompt de classificação vazio.')
    version = hashlib.sha256((categories_text+'\n'+prompt).encode()).hexdigest()
    schema = {'type':'object', 'properties': {
        'document_type': {'type':'string','enum':list(categories)},
        'reason': {'type':'string'}, 'needs_review': {'type':'boolean'}},
        'required':['document_type','reason','needs_review'], 'additionalProperties':False}
    return categories, prompt, schema, version


def validate_classification(data: dict, categories: dict) -> dict:
    if set(data) != {'document_type','reason','needs_review'}:
        raise ValueError('Campos inválidos na resposta de classificação.')
    if not isinstance(data['document_type'], str) or data['document_type'] not in categories:
        raise ValueError('Categoria retornada não pertence ao projeto.')
    if not isinstance(data['reason'], str) or not data['reason'].strip() or len(data['reason']) > 2000:
        raise ValueError('Justificativa de classificação inválida.')
    if type(data['needs_review']) is not bool:
        raise ValueError('needs_review deve ser booleano.')
    return {**data, 'needs_review': data['needs_review'] or data['document_type']=='outro'}


def classify_document(client, *, markdown: str, filename: str, projects_dir: Path, project: str, max_input_chars: int = 100000, structured_output: bool = True):
    categories, prompt, schema, version = load_classification_resources(projects_dir, project)
    if not markdown.strip() or len(markdown) > max_input_chars:
        return {'document_type':'outro','reason':'Conteúdo vazio ou acima do limite configurado; revisão necessária, sem truncamento silencioso.','needs_review':True}, {'prompt_version':version,'retry_count':0,'llm_called':False}
    user = json.dumps({'categories':categories,'filename':filename,'document_markdown':markdown},ensure_ascii=False)
    result = client.complete_json(system=prompt,user=user,schema=schema if structured_output else None)
    classification = validate_classification(result.data,categories)
    return classification, {'prompt_version':version,'retry_count':result.retry_count,'llm_called':True,'usage':getattr(result,'usage',{})}

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from websensors_flow_rag.clients.llm_client import LLMError, LLMResponseError
from websensors_flow_rag.extraction.service import ExtractionValidationError, extract_structured_data, load_extraction_resources

ROOT = Path(__file__).parents[1] / 'projects'


def empty_value(schema):
    if schema.get('type') == 'array': return []
    return None


def answer(kind='ficha_inscricao'):
    _, schema, _ = load_extraction_resources(ROOT, 'fai', kind)
    return {'data': {k: empty_value(v) for k, v in schema['properties']['data']['properties'].items()}, 'sources': [], 'warnings': []}


class Client:
    def __init__(self, results): self.results = iter(results); self.calls = []
    def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        result = next(self.results)
        if isinstance(result, Exception): raise result
        return SimpleNamespace(data=result, retry_count=0, usage={'total_tokens': 5})


def extract(client):
    return extract_structured_data(client, markdown='Nome: Pessoa Sintética\nRA: 00123', document_type='ficha_inscricao', projects_dir=ROOT, project='fai', valid_pages={1})


def test_all_eight_schemas_accept_explicit_missing_values():
    directories = list((ROOT/'fai/document_types').iterdir())
    assert len(directories) == 8
    for directory in directories:
        prompt, schema, versions = load_extraction_resources(ROOT, 'fai', directory.name)
        Draft202012Validator(schema).validate(answer(directory.name))
        assert prompt and versions['schema_version'] and json.loads((directory/'mapping.json').read_text())


def test_grounded_values_preserve_identifiers_and_missing_fields():
    value = answer()
    value['data'].update(candidato='Pessoa Sintética', registro_academico='00123')
    value['sources'] = [{'field':'candidato','quote':'Nome: Pessoa Sintética','page':1}, {'field':'registro_academico','quote':'RA: 00123','page':None}]
    result, metadata = extract(Client([value]))
    assert result['data']['registro_academico'] == '00123'
    assert result['data']['email'] is None
    assert metadata['fields_count'] == 2 and not metadata['needs_review']


@pytest.mark.parametrize('problem', ['schema', 'quote', 'page', 'json'])
def test_one_correction_for_invalid_schema_json_or_evidence(problem):
    bad = answer()
    if problem == 'schema': bad['extra'] = 'not allowed'
    elif problem == 'json': bad = LLMResponseError('JSON inválido.')
    else: bad['sources'] = [{'field':'candidato','quote':'invenção' if problem=='quote' else 'Pessoa Sintética','page':99 if problem=='page' else None}]
    client = Client([bad, answer()])
    _, metadata = extract(client)
    assert len(client.calls) == 2 and metadata['correction_count'] == 1
    assert 'correction_instruction' in json.loads(client.calls[1]['user'])


def test_invalid_second_response_fails_without_echoing_document():
    client = Client([{'private':'SECRET'}, {'private':'SECRET'}])
    with pytest.raises(ExtractionValidationError) as error: extract(client)
    assert 'SECRET' not in str(error.value) and len(client.calls) == 2


def test_transport_error_is_not_schema_correction():
    client = Client([LLMError('Falha de transporte.')])
    with pytest.raises(LLMError): extract(client)
    assert len(client.calls) == 1


def test_unsourced_values_and_empty_result_require_review():
    value = answer(); value['data']['candidato'] = 'Pessoa Sintética'
    result, metadata = extract(Client([value]))
    assert metadata['needs_review'] and 'candidato' in result['warnings'][0]
    _, metadata = extract(Client([answer()]))
    assert metadata['needs_review']


@pytest.mark.parametrize('project,kind', [('../escape','ficha_inscricao'), ('fai','../../escape')])
def test_resource_paths_are_confined(project,kind):
    with pytest.raises(ValueError): load_extraction_resources(ROOT,project,kind)


def test_final_failure_preserves_safe_evidence_location():
    value = answer()
    value['sources'] = [{'field':'candidato','quote':'PRIVATE-UNSUPPORTED-TEXT','page':None}]
    with pytest.raises(ExtractionValidationError) as error:
        extract(Client([value,value]))
    assert 'sources[0].quote' in str(error.value)
    assert 'PRIVATE-UNSUPPORTED-TEXT' not in str(error.value)


def test_correction_receives_all_invalid_evidence_locations():
    value=answer()
    value['sources']=[{'field':'candidato','quote':'PRIVATE-A','page':None}, {'field':'curso','quote':'PRIVATE-B','page':None}]
    client=Client([value,answer()])
    extract(client)
    feedback=json.loads(client.calls[1]['user'])['correction_instruction']
    assert 'sources[0].quote' in feedback and 'sources[1].quote' in feedback
    assert 'PRIVATE-' not in feedback


def test_json_mode_receives_output_schema_and_keeps_local_validation():
    client=Client([answer()])
    extract_structured_data(client,markdown='Nome: Pessoa Sintética',document_type='ficha_inscricao',projects_dir=ROOT,project='fai',structured_output=False)
    assert client.calls[0]['schema'] is None
    payload=json.loads(client.calls[0]['user'])
    assert payload['output_schema']['properties']['data']['required']

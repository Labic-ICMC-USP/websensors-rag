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


def test_page_furniture_is_added_to_extraction_input_and_hash():
    from types import SimpleNamespace as NS
    from websensors_flow_rag.extraction.steps import extraction_input, page_furniture_text
    docling = {'texts': [
        {'label': 'text', 'content_layer': 'body', 'text': 'Corpo'},
        {'label': 'page_footer', 'content_layer': 'furniture', 'text': 'Código de controle: AB12'},
        {'label': 'page_footer', 'content_layer': 'furniture', 'text': 'Código de controle: AB12'},
        {'label': 'page_header', 'content_layer': 'furniture', 'text': 'Universidade'},
        {'label': 'picture', 'content_layer': 'furniture', 'text': 'logo'},
    ]}
    assert page_furniture_text(docling) == 'Código de controle: AB12\nUniversidade'
    work = NS(markdown='# Declaração\n\nCorpo', docling_json=docling)
    off = NS(extraction=NS(include_page_furniture=False))
    on = NS(extraction=NS(include_page_furniture=True))
    assert extraction_input(work, off) == work.markdown
    text = extraction_input(work, on)
    assert text.startswith(work.markdown) and 'Código de controle: AB12' in text and 'logo' not in text


def test_furniture_option_changes_pipeline_hash():
    from websensors_flow_rag.config import load_rag_settings
    from websensors_flow_rag.utils import pipeline_hash
    settings = load_rag_settings(Path(__file__).parents[1] / 'config/rag.yaml')
    settings.classification.enabled = settings.extraction.enabled = True
    from websensors_flow_rag.config import LLMSettings
    settings.services.llm = LLMSettings(model='m', api_key='k')
    before = pipeline_hash(settings)
    settings.extraction.include_page_furniture = True
    assert pipeline_hash(settings) != before


def test_relaxed_evidence_ignores_markdown_formatting_but_not_words():
    from websensors_flow_rag.extraction.service import validate_extraction
    _, schema, _ = load_extraction_resources(ROOT, 'fai', 'edital')
    markdown = ('São requisitos:\n\na)\n\nEstar matriculado em Sistemas de Informação,\n\nb)\n\n'
                'Ciência da Computação.\n\n| Critério | Pontuação |\n|---|---|\n| Formação acadêmica | 1,0 ponto |\n')
    value = answer('edital')
    value['sources'] = [
        {'field': 'requisitos_obrigatorios', 'quote': 'Estar matriculado em Sistemas de Informação, Ciência da Computação.', 'page': None},
        {'field': 'criterios_avaliacao', 'quote': 'Formação acadêmica 1,0 ponto', 'page': None},
    ]
    assert validate_extraction(value, schema, markdown, set()) is value
    value['sources'] = [{'field': 'criterios_avaliacao', 'quote': 'Formação acadêmica 2,0 pontos', 'page': None}]
    with pytest.raises(ExtractionValidationError):
        validate_extraction(value, schema, markdown, set())
    value['sources'] = [{'field': 'requisitos_obrigatorios', 'quote': 'Estar matriculado em Ciência da Computação', 'page': None}]
    with pytest.raises(ExtractionValidationError):
        validate_extraction(value, schema, markdown, set())


def test_schema_error_names_path_and_extra_keys_without_values():
    from websensors_flow_rag.extraction.service import validate_extraction
    schema = load_extraction_resources(ROOT, 'fai', 'curriculo_lattes')[1]
    value = answer('curriculo_lattes')
    value['data']['formacao'] = [{'nivel': 'Graduação', 'instituicao': 'Universidade Sigilosa', 'curso': None, 'inicio': None,
                                  'fim': None, 'situacao': None, 'titulo': None, 'orientador': 'Pessoa Sigilosa'}]
    with pytest.raises(ExtractionValidationError) as caught:
        validate_extraction(value, schema, 'texto', set())
    message = str(caught.value)
    assert "data.formacao.0: propriedades não permitidas ['orientador']" in message
    assert 'Sigilosa' not in message

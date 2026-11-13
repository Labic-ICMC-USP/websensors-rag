import json
from types import SimpleNamespace

import pytest
import yaml

from test_classification_pipeline import enable
from test_extraction import answer
from test_processing import processing  # noqa: F401 - fixture
from websensors_flow.exceptions import ConfigurationError
from websensors_flow_rag.services.process_document import ProcessDocumentService
from websensors_flow_rag.structured.index import structured_target
from websensors_flow_rag.utils import pipeline_hash


@pytest.fixture
def structured(processing, tmp_path, monkeypatch):  # noqa: F811
    settings, objects, calls, path = processing
    directory = enable(settings, path, tmp_path)
    settings.extraction.enabled = True
    settings.structured_index.enabled = True
    path.write_text(yaml.safe_dump(settings.model_dump(mode='json')))

    records, aliases = {}, {}
    from websensors_flow_rag.indexing import steps as indexing_steps
    Base = indexing_steps.ElasticsearchClient
    failures = {'put_document': False}

    class ES(Base):
        def put_document(self, document_id, document):
            if failures['put_document']:
                raise RuntimeError('falha simulada no documento')
            super().put_document(document_id, document)
        def ensure_structured_index(self, index, alias, definition):
            assert definition['mappings']['dynamic'] == 'strict'
            aliases.setdefault(alias, set()).add(index)
        def put_structured_record(self, index, record_id, record):
            records[index, record_id] = json.loads(json.dumps(record))
        def get_structured_record(self, index, record_id):
            return records.get((index, record_id))
        def set_structured_active(self, index, record_id, active, updated_at):
            if (index, record_id) not in records:
                return False
            records[index, record_id]['active'] = active
            return True
        def count_active_structured(self, pattern, document_id, exclude_id=None):
            prefix = pattern.rstrip('*')
            return sum(i.startswith(prefix) and r['document_id'] == document_id and r['active'] and rid != exclude_id
                       for (i, rid), r in records.items())

    monkeypatch.setattr('websensors_flow_rag.indexing.steps.ElasticsearchClient', ES)
    monkeypatch.setattr('websensors_flow_rag.structured.steps.ElasticsearchClient', ES)

    predictions = []

    class Client:
        def __init__(self, **kwargs): pass
        def close(self): pass
        def complete_json(self, **kwargs):
            kind = json.loads(kwargs['user'])['document_type']
            predictions.append(kind)
            value = answer(kind)
            if kind == 'ficha_inscricao':
                value['data']['instituicao'] = 'matrícula acadêmica'
                value['sources'] = [{'field': 'instituicao', 'quote': 'matrícula acadêmica', 'page': None}]
            return SimpleNamespace(data=value, retry_count=0)

    monkeypatch.setattr('websensors_flow_rag.extraction.steps.LLMClient', Client)
    service = ProcessDocumentService(settings)
    service.convert_for_openwebui(filename='doc.pdf', content=b'original', project='fai')
    yield SimpleNamespace(settings=settings, path=path, directory=directory, records=records, aliases=aliases,
                          service=service, predictions=predictions, failures=failures, calls=calls, ES=ES)
    service.close()


def run(ctx, document_type):
    return ctx.service.process_file(filename='doc.pdf', content=b'original', project='fai',
                                    document_type=document_type, require_cached_artifacts=True)


def active(ctx):
    return {rid: r for (_, rid), r in ctx.records.items() if r['active']}


def test_config_requires_extraction_and_places_step_after_textual_staging(structured):
    names = [s.name for s in structured.settings.to_flow_settings().steps]
    assert names.index('preparar_registro_estruturado') == names.index('preparar_revisao_elasticsearch') + 1
    assert len(names) == 12
    structured.settings.extraction.enabled = False
    with pytest.raises(ConfigurationError):
        structured.settings.to_flow_settings()


def test_publication_activates_record_and_noop_reuses_it(structured):
    first = run(structured, 'ficha_inscricao')
    assert first.report.status == 'success', first.failure
    pointer = first.output['structured']
    assert pointer['record_id'] == f"{first.output['document_id']}:{first.output['revision_id']}"
    assert pointer['alias'] == 'rag-estruturado-fai-ficha_inscricao'
    assert pointer['index'].startswith(pointer['alias'] + '-')
    record = structured.records[pointer['index'], pointer['record_id']]
    assert record['active'] and record['data']['instituicao'] == 'matrícula acadêmica'
    assert record['project'] == 'fai' and record['status'] == 'success'
    document = structured.ES(None, None).get_document(first.output['document_id'])
    assert document['structured']['record_id'] == pointer['record_id']

    second = run(structured, 'ficha_inscricao')
    assert second.output['action'] == 'noop' and second.output['structured'] == pointer
    assert structured.predictions == ['ficha_inscricao']
    assert list(active(structured)) == [pointer['record_id']]


def test_type_change_deactivates_previous_category(structured):
    first = run(structured, 'ficha_inscricao')
    changed = run(structured, 'comprovante_matricula')
    assert changed.report.status == 'success', changed.failure
    assert changed.output['structured']['alias'] == 'rag-estruturado-fai-comprovante_matricula'
    assert list(active(structured)) == [changed.output['structured']['record_id']]
    assert not structured.records[first.output['structured']['index'], first.output['structured']['record_id']]['active']

    other = run(structured, 'outro')
    assert other.report.status == 'success' and 'structured' not in other.output
    assert active(structured) == {}
    document = structured.ES(None, None).get_document(other.output['document_id'])
    assert document['structured'] is None


def test_partial_publication_failure_restores_previous_revision(structured):
    first = run(structured, 'ficha_inscricao')
    structured.failures['put_document'] = True
    failed = run(structured, 'comprovante_matricula')
    assert failed.report.status == 'failed'
    assert 'falha simulada' in failed.failure.error_message
    es = structured.ES(None, None)
    document = es.get_document(first.output['document_id'])
    assert document['active_revision'] == first.output['revision_id']
    assert list(active(structured)) == [first.output['structured']['record_id']]
    assert es.count_revision(first.output['document_id'], first.output['revision_id'], active=True) > 0
    assert es.count_active_other_revisions(first.output['document_id'], first.output['revision_id']) == 0


def test_first_publication_failure_leaves_nothing_active(structured):
    structured.failures['put_document'] = True
    failed = run(structured, 'ficha_inscricao')
    assert failed.report.status == 'failed'
    assert active(structured) == {}
    assert structured.ES(None, None).get_document(next(iter(structured.records))[1].split(':')[0]) is None


def test_retry_restores_leftover_active_record_before_staging(structured):
    first = run(structured, 'ficha_inscricao')
    structured.failures['put_document'] = True
    failed = run(structured, 'comprovante_matricula')
    assert failed.report.status == 'failed'
    # Simula interrupção sem compensação: registro novo ficou ativo e o anterior não.
    leftover = next(k for k, r in structured.records.items() if r['document_type'] == 'comprovante_matricula')
    structured.records[leftover]['active'] = True
    structured.records[first.output['structured']['index'], first.output['structured']['record_id']]['active'] = False
    structured.failures['put_document'] = False
    retried = run(structured, 'comprovante_matricula')
    assert retried.report.status == 'success', retried.failure
    assert list(active(structured)) == [retried.output['structured']['record_id']]


def test_invalid_staged_record_blocks_publication(structured, monkeypatch):
    first = run(structured, 'ficha_inscricao')
    original_put = structured.ES.put_structured_record

    def corrupt(self, index, record_id, record):
        record = dict(record, data={**record['data'], 'campo_inexistente': 'x'})
        original_put(self, index, record_id, record)

    monkeypatch.setattr(structured.ES, 'put_structured_record', corrupt)
    failed = run(structured, 'comprovante_matricula')
    assert failed.report.status == 'failed'
    assert 'schema' in failed.failure.error_message
    assert list(active(structured)) == [first.output['structured']['record_id']]


def test_mapping_change_creates_new_physical_index_and_invalidates_hash(structured):
    before = structured_target(structured.settings, 'fai', 'ficha_inscricao')
    original_hash = pipeline_hash(structured.settings)
    mapping = structured.directory / 'fai/document_types/ficha_inscricao/mapping.json'
    raw = json.loads(mapping.read_text())
    raw['mappings']['properties']['data']['properties']['campus'] = {'type': 'keyword'}
    mapping.write_text(json.dumps(raw))
    after = structured_target(structured.settings, 'fai', 'ficha_inscricao')
    assert after['alias'] == before['alias'] and after['index'] != before['index']
    assert pipeline_hash(structured.settings) != original_hash


@pytest.mark.parametrize('project,kind', [('../x', 'ficha_inscricao'), ('fai', '../edital'), ('FAI', 'edital')])
def test_structured_paths_are_confined(structured, project, kind):
    with pytest.raises(ValueError):
        structured_target(structured.settings, project, kind)


def test_cli_conversion_populates_cache_for_next_revision(processing, tmp_path, monkeypatch):  # noqa: F811
    settings, _, calls, path = processing
    directory = enable(settings, path, tmp_path)
    from websensors_flow_rag.services.process_document import ProcessDocumentService as Service
    service = Service(settings)
    try:
        first = service.process_file(filename='novo.pdf', content=b'outro-original', project='fai', document_type='ficha_inscricao')
        assert first.report.status == 'success' and calls['docling'] == 1
        prompt = directory / 'fai/classification/prompt.md'
        prompt.write_text(prompt.read_text() + '\nRegra nova.\n')
        second = service.process_file(filename='novo.pdf', content=b'outro-original', project='fai', document_type='ficha_inscricao')
        assert second.report.status == 'success'
        assert second.output['revision_id'] != first.output['revision_id']
        assert calls['docling'] == 1
    finally:
        service.close()

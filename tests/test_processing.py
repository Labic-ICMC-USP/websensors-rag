from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from minio.error import S3Error

from websensors_flow_rag.api import create_rag_app
from websensors_flow_rag.cli import main_process
from websensors_flow_rag.config import load_rag_settings
from websensors_flow_rag.models import DoclingArtifacts
from websensors_flow_rag.services.process_document import ArtifactsUnavailable, ProcessDocumentService
from websensors_flow_rag.utils import docling_options_hash, sha256_bytes


@pytest.fixture
def processing(tmp_path, monkeypatch):
    raw = yaml.safe_load((Path(__file__).parents[1] / 'config/rag.yaml').read_text())
    raw['runtime']['report_dir'] = str(tmp_path / 'reports')
    raw['runtime']['console']['enabled'] = False
    raw['api']['auth'] = {'enabled': True, 'token': 'test-rag-token'}
    raw['startup']['enabled'] = False
    config_path = tmp_path / 'rag.yaml'
    config_path.write_text(yaml.safe_dump(raw))
    settings = load_rag_settings(config_path)
    objects, documents, chunks, calls = {}, {}, {}, {'docling': 0, 'embedding': 0}

    class Minio:
        def __init__(self, settings): pass
        def put_bytes(self, bucket, key, data, content_type): objects[bucket, key] = data
        def put_text(self, bucket, key, text, content_type): objects[bucket, key] = text.encode()
        def get_bytes(self, bucket, key):
            if (bucket, key) not in objects:
                raise S3Error(response=None, code='NoSuchKey', message='missing', resource=key, request_id='request', host_id='host')
            return objects[bucket, key]

    class Docling:
        def __init__(self, settings): pass
        def close(self): pass
        def convert(self, filename, content, mime_type, progress_callback=None):
            assert any(bucket == 'rag-bronze' and value == content for (bucket, _), value in objects.items())
            calls['docling'] += 1
            return {'markdown': '# Declaração\n\n' + 'Texto sintético de uma declaração de matrícula acadêmica. ' * 20,
                    'json': {'schema_name': 'DoclingDocument', 'pages': {}}, 'status': 'success'}

    class Embedding:
        def __init__(self, config): self.config = config
        def close(self): pass
        def embed(self, texts):
            calls['embedding'] += 1
            return [[0.1] * self.config.dimensions for _ in texts]

    class Elasticsearch:
        def __init__(self, *args): pass
        def close(self): pass
        def ensure_indices(self): pass
        def get_document(self, document_id): return documents.get(document_id)
        def put_document(self, document_id, document): documents[document_id] = document
        def count_revision(self, document_id, revision_id, active=None):
            return sum(c['document_id'] == document_id and c['revision_id'] == revision_id and (active is None or c['active'] == active) for c in chunks.values())
        def delete_staged_revision(self, document_id, revision_id):
            for key, c in list(chunks.items()):
                if c['document_id'] == document_id and c['revision_id'] == revision_id and not c['active']: del chunks[key]
        def bulk_index_chunks(self, batch):
            for c in batch: chunks[c['chunk_id']] = dict(c)
        def switch_active_revision(self, document_id, revision_id):
            for c in chunks.values():
                if c['document_id'] == document_id: c['active'] = c['revision_id'] == revision_id
        def count_active_other_revisions(self, document_id, revision_id):
            return sum(c['document_id'] == document_id and c['revision_id'] != revision_id and c['active'] for c in chunks.values())

    monkeypatch.setattr('websensors_flow_rag.services.process_document.MinIOClient', Minio)
    monkeypatch.setattr('websensors_flow_rag.indexing.steps.MinIOClient', Minio)
    monkeypatch.setattr('websensors_flow_rag.indexing.steps.DoclingClient', Docling)
    monkeypatch.setattr('websensors_flow_rag.indexing.steps.EmbeddingClient', Embedding)
    monkeypatch.setattr('websensors_flow_rag.indexing.steps.ElasticsearchClient', Elasticsearch)
    return settings, objects, calls, config_path


def test_external_conversion_then_processing_reuses_artifacts_and_noop(processing):
    settings, objects, calls, _ = processing
    service = ProcessDocumentService(settings)
    try:
        extracted = service.convert_for_openwebui(filename='ficha.pdf', content=b'%PDF-original', project='fai')
        assert extracted['page_content'].startswith('# Declaração')
        assert calls == {'docling': 1, 'embedding': 0}
        # Mesmo original por outra interface: nome/projeto/hash determinam o cache.
        request = service.prepare_upload(filename='ficha.pdf', content=b'%PDF-original', project='fai', require_cached_artifacts=True)
        assert request.docling_artifacts is not None
        result = service.run(request)
        assert result.report.status == 'success', result.failure
        assert result.output['project'] == 'fai'
        assert result.output['classification'] is None
        assert calls == {'docling': 1, 'embedding': 1}
        repeated = service.run(request)
        assert repeated.report.status == 'success'
        assert repeated.output['action'] == 'noop'
        assert calls == {'docling': 1, 'embedding': 1}
        assert any(key.endswith('/document.json') for _, key in objects)
    finally: service.close()


def test_cache_is_invalidated_by_options_and_required_cache_prevents_conversion(processing):
    settings, _, calls, _ = processing
    service = ProcessDocumentService(settings)
    try:
        service.convert_for_openwebui(filename='ficha.pdf', content=b'%PDF-original', project='fai')
        settings.services.docling.options['table_mode'] = 'fast'
        with pytest.raises(ArtifactsUnavailable):
            service.prepare_upload(filename='ficha.pdf', content=b'%PDF-original', project='fai', require_cached_artifacts=True)
        assert calls['docling'] == 1
    finally: service.close()


def test_invalid_artifacts_are_rejected_before_upload(processing):
    settings, objects, calls, _ = processing
    service = ProcessDocumentService(settings)
    artifacts = DoclingArtifacts(source_sha256='0' * 64, options_sha256=docling_options_hash(settings), markdown='# Texto', structural_json={'schema_name': 'DoclingDocument', 'pages': {}})
    try:
        with pytest.raises(ValueError, match='não correspondem'):
            service.prepare_upload(filename='ficha.pdf', content=b'%PDF-original', project='fai', artifacts=artifacts)
        assert objects == {}
        assert calls['docling'] == 0
    finally: service.close()


def test_invalid_project_empty_and_oversized_uploads_do_not_write_bronze(processing):
    settings, objects, _, _ = processing
    settings.api.max_upload_bytes = 5
    service = ProcessDocumentService(settings)
    try:
        for kwargs in [dict(project='../escape', content=b'123'), dict(project='fai', content=b''), dict(project='fai', content=b'123456')]:
            with pytest.raises(ValueError): service.prepare_upload(filename='f.pdf', **kwargs)
        assert objects == {}
    finally: service.close()


def test_api_external_loader_upload_and_job_share_pipeline(processing):
    settings, objects, calls, _ = processing
    app = create_rag_app(settings, startup_prepared=True)
    headers = {'Authorization': 'Bearer test-rag-token'}
    with TestClient(app) as client:
        assert client.put('/api/v1/openwebui/process', content=b'pdf', headers={'X-RAG-Project': 'fai', 'X-Original-Filename': 'ficha.pdf'}).status_code == 401
        response = client.put('/api/v1/openwebui/process', content=b'%PDF-original', headers={**headers, 'X-RAG-Project': 'fai', 'X-Original-Filename': 'ficha.pdf'})
        assert response.status_code == 200, response.text
        response = client.post('/api/v1/documents/process', files={'file': ('ficha.pdf', b'%PDF-original', 'application/pdf')}, data={'project': 'fai', 'require_cached_artifacts': 'true'}, headers=headers)
        assert response.status_code == 202, response.text
        token = response.json()['job_id']
        app.state.process_document_service.close()  # aguardar worker sem polling temporizado
        response = client.get(f'/api/v1/jobs/{token}', headers=headers)
        assert response.json()['status'] == 'success', response.text
        assert response.json()['result']['project'] == 'fai'
        assert client.get(f'/indexing/{token}', headers=headers).json()['status'] == 'success'
        assert calls == {'docling': 1, 'embedding': 1}
        assert client.get('/api/v1/jobs/missing', headers=headers).status_code == 404


def test_api_missing_cache_and_invalid_metadata_do_not_start_flow(processing):
    settings, _, calls, _ = processing
    with TestClient(create_rag_app(settings, startup_prepared=True)) as client:
        headers = {'Authorization': 'Bearer test-rag-token'}
        for metadata, cache, status in [('[]', 'false', 400), ('not-json', 'false', 400), ('{}', 'true', 409)]:
            response = client.post('/api/v1/documents/process', files={'file': ('f.pdf', b'pdf')}, data={'project': 'fai', 'metadata': metadata, 'require_cached_artifacts': cache}, headers=headers)
            assert response.status_code == status, response.text
        assert calls == {'docling': 0, 'embedding': 0}


def test_cli_writes_only_json_to_stdout_and_same_service_output(processing, tmp_path, capsys):
    settings, _, calls, config_path = processing
    source = tmp_path / 'ficha.pdf'; source.write_bytes(b'%PDF-original')
    output = tmp_path / 'output.json'
    main_process(['--file', str(source), '--project', 'fai', '--config', str(config_path), '--output-file', str(output)])
    result = json.loads(capsys.readouterr().out)
    assert json.loads(output.read_text()) == result
    assert result['project'] == 'fai' and result['action'] == 'indexed'
    assert calls == {'docling': 1, 'embedding': 1}


def test_bronze_failure_does_not_create_job(processing, monkeypatch):
    settings, _, calls, _ = processing
    def fail(*args): raise OSError('storage unavailable')
    monkeypatch.setattr('websensors_flow_rag.services.process_document.MinIOClient.put_bytes', fail)
    app = create_rag_app(settings, startup_prepared=True)
    with TestClient(app) as client:
        response = client.post('/api/v1/documents/process', files={'file': ('f.pdf', b'pdf')}, data={'project': 'fai'}, headers={'Authorization': 'Bearer test-rag-token'})
        assert response.status_code == 502
        assert app.state.job_store.jobs == {}
        assert calls == {'docling': 0, 'embedding': 0}


def test_api_rejects_oversized_file_before_bronze(processing):
    settings, objects, _, _ = processing
    settings.api.max_upload_bytes = 2
    with TestClient(create_rag_app(settings, startup_prepared=True)) as client:
        response = client.post('/api/v1/documents/process', files={'file': ('f.pdf', b'123')}, data={'project': 'fai'}, headers={'Authorization': 'Bearer test-rag-token'})
        assert response.status_code == 413
        assert not objects


def test_legacy_index_route_keeps_contract(processing):
    settings, objects, _, _ = processing
    objects['rag-bronze', 'original.pdf'] = b'%PDF-original'
    app = create_rag_app(settings, startup_prepared=True)
    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer test-rag-token'}
        response = client.post('/documents/index', json={'key': 'original.pdf'}, headers=headers)
        assert response.status_code == 202
        assert response.json()['status_url'].startswith('/indexing/')
        app.state.process_document_service.close()
        result = client.get(response.json()['status_url'], headers=headers)
        assert result.json()['status'] == 'success', result.text
        assert 'project' not in result.json()['result']

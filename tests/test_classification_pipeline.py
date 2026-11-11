import json
from pathlib import Path
from types import SimpleNamespace
import shutil

import yaml

from test_processing import processing
from websensors_flow_rag.config import LLMSettings
from websensors_flow_rag.services.process_document import ProcessDocumentService
from websensors_flow_rag.utils import pipeline_hash


def enable(settings, config_path, tmp_path):
    directory=tmp_path/'projects'
    shutil.copytree(Path(__file__).parents[1]/'projects',directory)
    settings.classification.enabled=True
    settings.classification.projects_dir=str(directory)
    settings.services.llm=LLMSettings(model='test-chat',api_key='test-only')
    config_path.write_text(yaml.safe_dump(settings.model_dump(mode='json')))
    return directory


def test_classification_persisted_reused_and_prompt_change_reprocessed(processing,tmp_path,monkeypatch):
    settings,objects,calls,path=processing
    directory=enable(settings,path,tmp_path)
    predictions=[]
    class Client:
        def __init__(self,**kwargs):pass
        def close(self):pass
        def complete_json(self,**kwargs):
            predictions.append(1)
            return SimpleNamespace(data={'document_type':'comprovante_matricula','reason':'Declaração confirma vínculo acadêmico.','needs_review':False},retry_count=0)
    monkeypatch.setattr('websensors_flow_rag.classification.steps.LLMClient',Client)
    service=ProcessDocumentService(settings)
    try:
        service.convert_for_openwebui(filename='ficha.pdf',content=b'original',project='fai')
        first=service.process_file(filename='ficha.pdf',content=b'original',project='fai',require_cached_artifacts=True)
        assert first.report.status=='success',first.failure
        assert first.output['classification']['document_type']=='comprovante_matricula'
        assert any(key.endswith('/classification.json') for _,key in objects)
        second=service.process_file(filename='ficha.pdf',content=b'original',project='fai',require_cached_artifacts=True)
        assert second.output['classification']==first.output['classification']
        assert second.output['action']=='noop'
        assert len(predictions)==1
        prompt=directory/'fai/classification/prompt.md'
        prompt.write_text(prompt.read_text()+'\nAtualização de regras de teste.\n')
        third=service.process_file(filename='ficha.pdf',content=b'original',project='fai',require_cached_artifacts=True)
        assert third.report.status=='success',third.failure
        assert third.output['revision_id']!=first.output['revision_id']
        assert len(predictions)==2 and calls['docling']==1
    finally:service.close()


def test_declared_type_change_invalidates_revision_without_llm(processing,tmp_path):
    settings,_,calls,path=processing
    enable(settings,path,tmp_path)
    service=ProcessDocumentService(settings)
    try:
        a=service.process_file(filename='ficha.pdf',content=b'original',project='fai',document_type='ficha_inscricao')
        b=service.process_file(filename='ficha.pdf',content=b'original',project='fai',document_type='outro')
        assert a.report.status==b.report.status=='success'
        assert a.output['revision_id']!=b.output['revision_id']
        assert b.output['classification']['document_type']=='outro'
    finally:service.close()


def test_hash_tracks_model_and_prompt_but_not_secret(processing,tmp_path):
    settings,_,_,path=processing
    enable(settings,path,tmp_path)
    original=pipeline_hash(settings)
    settings.services.llm.api_key='another-key'
    assert pipeline_hash(settings)==original
    settings.services.llm.model='another-model'
    assert pipeline_hash(settings)!=original


def test_classification_failure_keeps_previous_revision_active(processing,tmp_path,monkeypatch):
    from websensors_flow_rag.indexing import steps
    settings,_,calls,path=processing
    enable(settings,path,tmp_path)
    invalid=[False]
    class Client:
        def __init__(self,**kwargs):pass
        def close(self):pass
        def complete_json(self,**kwargs):
            return SimpleNamespace(data={'document_type':'inventado' if invalid[0] else 'ficha_inscricao','reason':'Evidência sintética.','needs_review':False},retry_count=0)
    monkeypatch.setattr('websensors_flow_rag.classification.steps.LLMClient',Client)
    service=ProcessDocumentService(settings)
    try:
        service.convert_for_openwebui(filename='ficha.pdf',content=b'original',project='fai')
        first=service.process_file(filename='ficha.pdf',content=b'original',project='fai',require_cached_artifacts=True)
        assert first.report.status=='success'
        invalid[0]=True
        settings.services.llm.model='changed-model'
        path.write_text(yaml.safe_dump(settings.model_dump(mode='json')))
        failed=service.process_file(filename='ficha.pdf',content=b'original',project='fai',require_cached_artifacts=True)
        assert failed.report.status=='failed'
        document=steps.ElasticsearchClient(None,None).get_document(first.output['document_id'])
        assert document['active_revision']==first.output['revision_id']
        assert document['classification']['document_type']=='ficha_inscricao'
        assert calls=={'docling':1,'embedding':1}
    finally:service.close()

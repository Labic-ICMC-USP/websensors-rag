from types import SimpleNamespace
import json
import yaml

from test_processing import processing
from test_classification_pipeline import enable
from test_extraction import answer
from websensors_flow_rag.services.process_document import ProcessDocumentService
from websensors_flow_rag.utils import pipeline_hash


def configure(processing,tmp_path,monkeypatch):
    settings,objects,calls,path = processing
    directory = enable(settings,path,tmp_path)
    settings.extraction.enabled = True
    path.write_text(yaml.safe_dump(settings.model_dump(mode='json')))
    predictions=[]
    class Client:
        def __init__(self,**kwargs): pass
        def close(self): pass
        def complete_json(self,**kwargs):
            predictions.append(1)
            value=answer()
            value['data']['instituicao']='matrícula acadêmica'
            value['sources']=[{'field':'instituicao','quote':'matrícula acadêmica','page':None}]
            return SimpleNamespace(data=value,retry_count=0)
    monkeypatch.setattr('websensors_flow_rag.extraction.steps.LLMClient',Client)
    return directory,predictions


def test_extraction_persists_and_noop_does_not_call_llm(processing,tmp_path,monkeypatch):
    directory,predictions=configure(processing,tmp_path,monkeypatch)
    settings,objects,calls,path=processing
    service=ProcessDocumentService(settings)
    try:
        service.convert_for_openwebui(filename='ficha.pdf',content=b'original',project='fai')
        first=service.process_file(filename='ficha.pdf',content=b'original',project='fai',document_type='ficha_inscricao',require_cached_artifacts=True)
        assert first.report.status=='success',first.failure
        assert first.output['extraction']['status']=='success'
        artifacts=[json.loads(v) for (_,k),v in objects.items() if k.endswith('/extraction.json')]
        assert artifacts==[first.output['extraction']]
        from websensors_flow_rag.utils import sha256_bytes
        manifests=[json.loads(v) for (_,k),v in objects.items() if k.endswith('/manifest.json') and 'extraction' in json.loads(v)]
        assert len(manifests)==1 and manifests[0]['created_at'].endswith('+00:00')
        for artifact in manifests[0]['artifacts'].values():
            bucket,key=artifact['uri'][5:].split('/',1)
            assert artifact['sha256']==sha256_bytes(objects[bucket,key])
        second=service.process_file(filename='ficha.pdf',content=b'original',project='fai',document_type='ficha_inscricao',require_cached_artifacts=True)
        assert second.output['action']=='noop' and second.output['extraction']==first.output['extraction']
        assert len(predictions)==1 and calls=={'docling':1,'embedding':1}
        original=pipeline_hash(settings)
        prompt=directory/'fai/document_types/ficha_inscricao/prompt.md'
        prompt.write_text(prompt.read_text()+'\nNova regra.')
        assert pipeline_hash(settings)!=original
    finally: service.close()


def test_invalid_extraction_preserves_previous_active_revision(processing,tmp_path,monkeypatch):
    configure(processing,tmp_path,monkeypatch)
    settings,_,calls,path=processing
    service=ProcessDocumentService(settings)
    try:
        service.convert_for_openwebui(filename='ficha.pdf',content=b'original',project='fai')
        first=service.process_file(filename='ficha.pdf',content=b'original',project='fai',document_type='ficha_inscricao',require_cached_artifacts=True)
        assert first.report.status=='success'
        class Invalid:
            def __init__(self,**kwargs): pass
            def close(self): pass
            def complete_json(self,**kwargs): return SimpleNamespace(data={},retry_count=0)
        monkeypatch.setattr('websensors_flow_rag.extraction.steps.LLMClient',Invalid)
        settings.extraction.max_output_tokens+=1
        path.write_text(yaml.safe_dump(settings.model_dump(mode='json')))
        failed=service.process_file(filename='ficha.pdf',content=b'original',project='fai',document_type='ficha_inscricao',require_cached_artifacts=True)
        assert failed.report.status=='failed'
        from websensors_flow_rag.indexing.steps import ElasticsearchClient
        saved=ElasticsearchClient(None,None).get_document(first.output['document_id'])
        assert saved['active_revision']==first.output['revision_id']
        assert saved['extraction']==first.output['extraction']
        assert calls=={'docling':1,'embedding':1}
    finally: service.close()


def test_other_and_input_limit_skip_llm_explicitly(processing,tmp_path,monkeypatch):
    _,predictions=configure(processing,tmp_path,monkeypatch)
    settings,_,_,path=processing
    service=ProcessDocumentService(settings)
    try:
        other=service.process_file(filename='other.pdf',content=b'other',project='fai',document_type='outro')
        assert other.report.status=='success' and other.output['extraction']['status']=='not_applicable'
        service.convert_for_openwebui(filename='ficha.pdf',content=b'original',project='fai')
        settings.extraction.max_input_chars=1
        path.write_text(yaml.safe_dump(settings.model_dump(mode='json')))
        limited=service.process_file(filename='ficha.pdf',content=b'original',project='fai',document_type='ficha_inscricao',require_cached_artifacts=True)
        assert limited.report.status=='success' and limited.output['extraction']['status']=='needs_review'
        assert limited.output['extraction']['data'] is None and not predictions
    finally: service.close()


def test_extraction_json_mode_does_not_change_classifier_format(processing,tmp_path,monkeypatch):
    configure(processing,tmp_path,monkeypatch)
    settings,_,_,path=processing
    settings.extraction.structured_output=False
    path.write_text(yaml.safe_dump(settings.model_dump(mode='json')))
    received=[]
    class Client:
        def __init__(self,**kwargs): pass
        def close(self): pass
        def complete_json(self,**kwargs):
            received.append(kwargs)
            return SimpleNamespace(data=answer(),retry_count=0)
    monkeypatch.setattr('websensors_flow_rag.extraction.steps.LLMClient',Client)
    service=ProcessDocumentService(settings)
    try:
        result=service.process_file(filename='ficha.pdf',content=b'original',project='fai',document_type='ficha_inscricao')
        assert result.report.status=='success',result.failure
        assert received[0]['schema'] is None
        assert 'output_schema' in json.loads(received[0]['user'])
        assert settings.services.llm.structured_output is True
    finally:service.close()

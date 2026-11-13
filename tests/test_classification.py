from pathlib import Path
from types import SimpleNamespace
import pytest
from websensors_flow_rag.classification.service import classify_document, load_classification_resources, validate_classification

PROJECTS=Path(__file__).parents[1]/'projects'


def test_project_resources_and_categories():
    categories,prompt,schema,version=load_classification_resources(PROJECTS,'fai')
    assert len(categories)==9 and 'outro' in categories
    assert schema['properties']['document_type']['enum']==list(categories)
    assert prompt and len(version)==64


@pytest.mark.parametrize('kind',['edital','carta_motivacao','comprovante_matricula','comprovante_residencia','documento_identificacao_foto','curriculo_lattes','declaracao_disponibilidade','ficha_inscricao','outro'])
def test_categories_are_validated_not_inferred_from_name(kind):
    class Client:
        def complete_json(self,**kwargs):
            assert 'document_markdown' in kwargs['user']
            return SimpleNamespace(data={'document_type':kind,'reason':'Evidência sintética do conteúdo.','needs_review':False},retry_count=0)
    result,meta=classify_document(Client(),markdown='Conteúdo de teste',filename='nome-sem-informacao.pdf',projects_dir=PROJECTS,project='fai')
    assert result['document_type']==kind
    assert result['needs_review']==(kind=='outro')
    assert meta['llm_called']


@pytest.mark.parametrize('data',[
 {'document_type':'inventado','reason':'r','needs_review':False},
 {'document_type':'outro','reason':'r','needs_review':'false'},
 {'document_type':'outro','reason':'','needs_review':True},
 {'document_type':'outro','reason':'r','needs_review':True,'confidence':0.99},
])
def test_invalid_classifications_are_rejected(data):
    categories,*_=load_classification_resources(PROJECTS,'fai')
    with pytest.raises(ValueError):validate_classification(data,categories)


def test_long_document_is_not_silently_truncated():
    result,meta=classify_document(None,markdown='abcdef',filename='x.pdf',projects_dir=PROJECTS,project='fai',max_input_chars=5)
    assert result['needs_review'] and not meta['llm_called']


def test_project_path_traversal_is_rejected():
    with pytest.raises(ValueError):load_classification_resources(PROJECTS,'../fai')

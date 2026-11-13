import httpx
import pytest
from websensors_flow_rag.clients.llm_client import LLMClient, LLMError


def client(handler, retries=0):
    return LLMClient(endpoint='https://example.test/api/v1', model='model', api_key='test-secret', retries=retries, transport=httpx.MockTransport(handler))


def test_valid_json_and_usage():
    def respond(request):
        assert request.url.path == '/api/v1/chat/completions'
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"document_type":"outro"}'}}], 'usage':{'total_tokens':12,'extra':'private'}})
    c=client(respond)
    try:
        result=c.complete_json(system='rules',user='data')
        assert result.data['document_type']=='outro'
        assert result.usage=={'total_tokens':12}
    finally:c.close()


@pytest.mark.parametrize('body',[
 {'choices':[{'finish_reason':'length','message':{'content':'{}'}}]},
 {'choices':[{'finish_reason':'stop','message':{'content':'not json'}}]},
 {'choices':[{'finish_reason':'stop','message':{'content':'[]'}}]},
 {'choices':[]},
])
def test_invalid_or_truncated_output_fails_without_echoing_content(body):
    c=client(lambda request:httpx.Response(200,json=body))
    try:
        with pytest.raises(LLMError): c.complete_json(system='rules',user='private document')
    finally:c.close()


def test_auth_error_not_retried_or_exposed():
    calls=[]
    def respond(request):
        calls.append(request)
        return httpx.Response(401,json={'error':'test-secret private document'})
    c=client(respond,retries=2)
    try:
        with pytest.raises(LLMError,match='HTTP 401') as error:c.complete_json(system='rules',user='private document')
        assert len(calls)==1
        assert 'test-secret' not in str(error.value)
    finally:c.close()


def test_transient_error_retried(monkeypatch):
    monkeypatch.setattr('websensors_flow_rag.clients.llm_client.time.sleep',lambda _:None)
    calls=[]
    def respond(request):
        calls.append(request)
        return httpx.Response(503) if len(calls)==1 else httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]})
    c=client(respond,retries=1)
    try:assert c.complete_json(system='rules',user='data').retry_count==1
    finally:c.close()


@pytest.mark.parametrize('reason,expected', [('length','length'), ('content_filter','content_filter'), ('PRIVATE-TEXT','unknown'), (None,'unknown')])
def test_interruption_reports_only_safe_reason_and_budget(reason,expected):
    c=client(lambda request:httpx.Response(200,json={'choices':[{'finish_reason':reason,'message':{'content':'PRIVATE-CONTENT'}}]}))
    try:
        with pytest.raises(LLMError) as error:c.complete_json(system='rules',user='private document')
        assert f'finish_reason={expected}' in str(error.value)
        assert 'max_tokens=2048' in str(error.value)
        assert 'PRIVATE' not in str(error.value)
    finally:c.close()

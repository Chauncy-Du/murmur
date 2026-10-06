import httpx
import pytest
from murmur import service_availability as availability


def cfg(**values):
    return dict(llm_url='http://127.0.0.1:11434/v1',llm_model='public-model',ollama_auto=False,demo=False,**values)


def test_local_catalog_never_receives_cloud_credential_or_post(monkeypatch):
    monkeypatch.setattr(availability,'credential',lambda name:pytest.fail('Local probe read cloud credential'))
    seen=[]
    def handler(request):
        seen.append(request.method);assert request.headers['authorization']=='Bearer local'
        return httpx.Response(200,json={'data':[{'id':'public-model'}]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert availability.probe('llm',cfg(),client)[0]=='active'
    assert seen==['GET']


def test_missing_key_does_not_send_request(monkeypatch):
    monkeypatch.setattr(availability,'credential',lambda name:'')
    with httpx.Client(transport=httpx.MockTransport(lambda request:pytest.fail('No credential'))) as client:
        assert availability.probe('llm',dict(cfg(),llm_url='https://example.com/v1'),client)[0]=='off'


@pytest.mark.parametrize('status,data,state',[(401,{},'error'),(200,{'data':[]},'warning'),(500,{},'error')])
def test_probe_distinguishes_denied_unlisted_and_error(status,data,state):
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(status,json=data))) as client:
        assert availability.probe('llm',cfg(),client)[0]==state


def test_demo_and_unloaded_files_do_not_claim_active(monkeypatch):
    assert availability.probe('llm',dict(cfg(),demo=True))[0]=='off'
    from murmur import offline
    monkeypatch.setattr(offline,'model_paths',lambda config:('fixture',))
    assert availability.probe('asr',{'asr_backend':'offline'})[0]=='warning'


def test_oversized_catalog_is_rejected():
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,content=b' '*1048577))) as client:
        assert availability.probe('llm',cfg(),client)[0]=='error'

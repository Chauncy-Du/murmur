import copy
import json
import threading

import httpx
import pytest

from murmur import providers, service_checks
from murmur.assistant import ASK_SYSTEM_PROMPT, AskResult, ask_config, parse_ask_result
from murmur.storage import DEFAULTS

HTTP_CLIENT = httpx.Client

@pytest.fixture
def cfg():
    value=copy.deepcopy(DEFAULTS)
    value.update(ask_llm_url='https://assistant.fixture.invalid/v1',ask_llm_model='assistant-model',
                 rules='原文=>changed',llm_input_price_per_million=999.,llm_output_price_per_million=999.)
    return value


def install_http(monkeypatch, content, status=200, error=None):
    requests=[];real=HTTP_CLIENT
    def respond(request):
        requests.append(request)
        if error:raise error
        return httpx.Response(status,json={'choices':[{'message':{'content':content}}],
                                          'usage':{'prompt_tokens':20,'completion_tokens':10,'total_tokens':30}})
    monkeypatch.setattr(httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(respond),**kw))
    return requests


@pytest.mark.parametrize('action',('replace','insert','answer'))
def test_ask_routes_one_json_request_with_independent_cloud_key(cfg,monkeypatch,action):
    requests=install_http(monkeypatch,json.dumps({'action':action,'text':'完成结果'}));keys=[];usage=[]
    def key(name):keys.append(name);return 'ask-test-only'
    monkeypatch.setattr(providers,'credential',key)
    result=providers.ask('请改写原文','  原文中的内容  ',cfg,usage_sink=usage.append)
    assert result==AskResult(action,'完成结果') and keys==['ask_llm']
    assert len(requests)==1
    request=requests[0];body=json.loads(request.content)
    assert str(request.url)=='https://assistant.fixture.invalid/v1/chat/completions'
    assert request.headers['Authorization']=='Bearer ask-test-only'
    assert body['model']=='assistant-model' and body['response_format']=={'type':'json_object'}
    assert body['messages'][0]=={'role':'system','content':ASK_SYSTEM_PROMPT}
    assert json.loads(body['messages'][1]['content'])=={'instruction':'请改写原文','selected_text':'  原文中的内容  '}
    assert 'reasoning_effort' not in body
    assert usage[0]['model']=='assistant-model' and usage[0]['local'] is False
    assert usage[0]['total_tokens']==30 and usage[0]['cost_usd'] is None


def test_question_without_context_and_insert_contract(cfg,monkeypatch):
    requests=install_http(monkeypatch,'{"action":"answer","text":"答案"}')
    monkeypatch.setattr(providers,'credential',lambda name:'test-only')
    assert providers.ask('为什么天空是蓝色的？','',cfg).action=='answer'
    assert json.loads(json.loads(requests[0].content)['messages'][1]['content'])['selected_text']==''
    install_http(monkeypatch,'{"action":"replace","text":"wrong"}')
    with pytest.raises(RuntimeError,match='without selected text'):providers.ask('写封邮件','',cfg)


@pytest.mark.parametrize('content',('not JSON','```json\n{"action":"answer","text":"OK"}\n```',
    '{}','[]','{"action":"execute","text":"secret"}','{"action":"answer","text":""}',
    '{"action":"answer","text":null}','{"action":"answer","text":"OK","other":"secret"}'))
def test_invalid_routing_response_is_sanitized(content):
    with pytest.raises(RuntimeError,match='invalid response') as error:parse_ask_result(content)
    assert 'secret' not in str(error.value)


@pytest.mark.parametrize('url',('http://api.fixture.invalid/v1','https://localhost/v1',
    'https://127.0.0.1/v1','https://[::1]/v1','https://10.0.0.1/v1','https://service.local/v1',
    'https://secret@api.fixture.invalid/v1','https://api.fixture.invalid/v1?token=secret',
    'https://api.fixture.invalid/v1#secret','https://api.fixture.invalid:0/v1','https://singlehost/v1',
    'https://127.1/v1','https://0177.0.0.1/v1','https://0x7f.0.0.1/v1',
    'https://localhost.localdomain/v1','https://bad..fixture.invalid/v1'))
def test_ask_rejects_invalid_or_local_endpoint_before_credentials(cfg,monkeypatch,url):
    cfg['ask_llm_url']=url
    monkeypatch.setattr(providers,'credential',lambda name:pytest.fail('Invalid endpoint read credentials'))
    with pytest.raises(RuntimeError) as error:providers.ask('question','',cfg)
    assert 'secret' not in str(error.value)


def test_missing_ask_key_does_not_fall_back_to_general_key(cfg,monkeypatch):
    keys=[]
    def key(name):keys.append(name);return '' if name=='ask_llm' else 'general-secret'
    monkeypatch.setattr(providers,'credential',key)
    with pytest.raises(RuntimeError,match='Ask Anything API key'):providers.ask('question','',cfg)
    assert keys==['ask_llm']


def test_cancellation_demo_and_oversize_do_not_call_network_or_keys(cfg,monkeypatch):
    monkeypatch.setattr(providers,'credential',lambda name:pytest.fail('Unexpected credential read'))
    monkeypatch.setattr(httpx,'Client',lambda **kw:pytest.fail('Unexpected network access'))
    cancel=threading.Event();cancel.set()
    with pytest.raises(InterruptedError):providers.ask('question','',cfg,cancel)
    for instruction,context in [('a'*12001,''),('question','a'*12001),('  ','')]:
        with pytest.raises(RuntimeError):providers.ask(instruction,context,cfg)
    cfg['demo']=True
    assert providers.ask('question','',cfg).text.startswith('[Demo result')


@pytest.mark.parametrize('status,error,message',((401,None,'HTTP 401'),(429,None,'HTTP 429'),
    (200,httpx.ReadTimeout('secret'),'timed out'),(200,httpx.ReadError('secret'),'Could not reach')))
def test_ask_transport_errors_are_sanitized(cfg,monkeypatch,status,error,message):
    install_http(monkeypatch,'secret',status,error)
    monkeypatch.setattr(providers,'credential',lambda name:'test-only')
    with pytest.raises(RuntimeError,match=message) as caught:providers.ask('question','original',cfg)
    assert 'secret' not in str(caught.value)


def test_ask_service_check_uses_fixed_json_prompt_and_draft_key(cfg,monkeypatch):
    requests=install_http(monkeypatch,'{"action":"answer","text":"OK"}');usage=[]
    monkeypatch.setattr(service_checks,'credential',lambda name:pytest.fail('Draft key ignored'))
    result=service_checks.check_service('ask',cfg,{'ask_llm':'typed-test-only','llm':'wrong-key'},usage_sink=usage.append)
    assert result['success'] and len(requests)==1
    body=json.loads(requests[0].content)
    assert body['model']=='assistant-model' and body['max_tokens']==64
    assert json.loads(body['messages'][1]['content'])=={'instruction':'Reply with only OK.','selected_text':''}
    assert body['response_format']=={'type':'json_object'}
    assert requests[0].headers['Authorization']=='Bearer typed-test-only'
    assert result['usage']['model']=='assistant-model' and usage[0]['cost_usd'] is None
    assert 'typed-test-only' not in str(result)


@pytest.mark.parametrize('content',('OK','{"action":"run","text":"secret"}','{"action":"replace","text":"wrong"}'))
def test_ask_service_check_requires_routing_json(cfg,monkeypatch,content):
    install_http(monkeypatch,content)
    result=service_checks.check_service('ask',cfg,{'ask_llm':'test-only'})
    assert result['success'] is False and 'secret' not in str(result)


def test_ask_config_does_not_change_general_processing(cfg):
    original=copy.deepcopy(cfg);resolved=ask_config(cfg)
    assert cfg==original
    assert resolved['ollama_auto'] is False and resolved['ollama'] is False
    assert resolved['llm_url']==cfg['ask_llm_url']
    assert resolved['llm_input_price_per_million'] is None


def test_ask_active_cancellation_closes_transport_and_releases_slot(cfg,monkeypatch):
    entered=threading.Event();closed=threading.Event();cancel=threading.Event();outcomes=[]
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):self.close()
        def close(self):closed.set()
        def post(self,*args,**kwargs):
            entered.set();assert closed.wait(2)
            raise httpx.ReadError('test-only')
    slots=threading.BoundedSemaphore(1)
    monkeypatch.setattr(providers,'_LLM_SLOTS',slots)
    monkeypatch.setattr(httpx,'Client',Client)
    monkeypatch.setattr(providers,'credential',lambda name:'test-only')
    def work():
        try:providers.ask('question','',cfg,cancel)
        except InterruptedError:outcomes.append('cancelled')
    thread=threading.Thread(target=work);thread.start();assert entered.wait(2)
    cancel.set();thread.join(2)
    assert not thread.is_alive() and outcomes==['cancelled'] and closed.is_set()
    assert slots.acquire(blocking=False);slots.release()


def test_ask_service_missing_dedicated_key_never_uses_general_key(cfg,monkeypatch):
    reads=[]
    def key(name):reads.append(name);return '' if name=='ask_llm' else 'wrong-general-key'
    monkeypatch.setattr(service_checks,'credential',key)
    result=service_checks.check_service('ask',cfg,{'llm':'wrong-draft-key'})
    assert not result['success'] and result['summary']=='API key missing'
    assert reads==['ask_llm']

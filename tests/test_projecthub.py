import copy
import json
import sqlite3
import threading

import httpx
import pytest

from murmur import projecthub, providers, service_checks
from murmur.storage import DEFAULTS

REAL_CLIENT = httpx.Client


@pytest.fixture
def cfg(tmp_path):
    value = copy.deepcopy(DEFAULTS)
    value.update(llm_url=projecthub.BASE_URL,llm_model='office-test',ollama=False,ollama_auto=False,
                 ask_llm_url=projecthub.BASE_URL+'/v1',ask_llm_model='office-test',_data_dir=str(tmp_path))
    return value


def install(monkeypatch, handler):
    requests=[]
    def respond(request):
        requests.append(request)
        if request.url.path.endswith('/v1/models'):
            return httpx.Response(200,json={'data':[
                {'id':'office-test','available':True,'gateway_input':['文字'],'gateway_output':['文字']},
                {'id':'unavailable','available':False,'gateway_input':['文字'],'gateway_output':['文字']},
                {'id':'ai-minute','available':True,'gateway_input':['文字'],'gateway_output':['文字']}]})
        if request.url.path.endswith('/v1/capabilities'):
            return httpx.Response(200,json={'input':['text'],'output':['text']})
        return handler(request)
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:REAL_CLIENT(transport=httpx.MockTransport(respond),**kwargs))
    monkeypatch.setattr(projecthub,'POLL_SECONDS',0)
    monkeypatch.setattr(providers,'credential',lambda _: 'fixture-only-key')
    return requests


def done(text='原文内容。'):
    return httpx.Response(200,json={'status':'succeeded','result':{
        'model':'office-test','choices':[{'message':{'content':text}}],
        'gateway':{'estimated_usage':{'prompt_tokens':200,'completion_tokens':10,'total_tokens':210}}}})


def rows(cfg):
    with sqlite3.connect(cfg['_data_dir']+'/projecthub-tasks.sqlite3') as db:
        return db.execute('SELECT request_key,body,task_id,status FROM tasks').fetchall()


@pytest.mark.parametrize('mode',('听写','润色','ask'))
def test_polish_and_ask_use_restricted_async_protocol(cfg,monkeypatch,mode):
    polls=[]
    def handler(request):
        if request.method=='POST':return httpx.Response(202,json={'id':'task-one','status':'queued'})
        polls.append(request)
        if len(polls)==1:return httpx.Response(200,json={'status':'running'})
        return done('{"action":"answer","text":"回答"}' if mode=='ask' else '原文内容。')
    requests=install(monkeypatch,handler)
    usage=[]
    result=providers.ask('请解释','',cfg,usage_sink=usage.append) if mode=='ask' else providers.transform('原文内容。',mode,cfg,usage_sink=usage.append)
    assert result.text=='回答' if mode=='ask' else result=='原文内容。'
    post=[r for r in requests if r.method=='POST']
    assert len(post)==1 and post[0].url.path=='/ai/jobs'
    body=json.loads(post[0].content)
    assert set(body)=={'model','messages','stream'} and body['stream'] is False
    assert post[0].headers['Idempotency-Key'] and post[0].headers['Authorization']=='Bearer fixture-only-key'
    assert polls[0].url.path=='/ai/jobs/task-one'
    assert usage[0]['status']=='missing' and usage[0]['cost_usd'] is None
    assert rows(cfg)==[]


def test_lost_post_response_recovers_same_key_and_exact_body(cfg,monkeypatch):
    count=0
    def handler(request):
        nonlocal count
        if request.method=='POST':
            count+=1
            assert rows(cfg)[0][3]=='submitting'
            if count==1:raise httpx.ReadTimeout('private response lost')
            return httpx.Response(202,json={'id':'task-one'})
        return done()
    requests=install(monkeypatch,handler)
    with pytest.raises(RuntimeError,match='timed out'):providers.transform('原文内容。','润色',cfg)
    assert rows(cfg)[0][2] is None
    assert 'fixture-only-key' not in str(rows(cfg))
    assert providers.transform('原文内容。','润色',cfg)=='原文内容。'
    posts=[r for r in requests if r.method=='POST']
    assert posts[0].headers['Idempotency-Key']==posts[1].headers['Idempotency-Key']
    assert posts[0].content==posts[1].content


def test_poll_transport_failure_restart_resumes_get_without_post(cfg,monkeypatch):
    interrupted=True
    def handler(request):
        if request.method=='POST':return httpx.Response(202,json={'id':'task-one'})
        if interrupted:raise httpx.ConnectError('private upstream data')
        return done()
    requests=install(monkeypatch,handler)
    with pytest.raises(RuntimeError,match='reach'):providers.transform('原文内容。','润色',cfg)
    assert rows(cfg)[0][2]=='task-one'
    interrupted=False
    assert providers.transform('原文内容。','润色',copy.deepcopy(cfg))=='原文内容。'
    assert len([r for r in requests if r.method=='POST'])==1


@pytest.mark.parametrize('status',('failed','indeterminate','cancelled','expired'))
def test_terminal_states_stop_replacement(cfg,monkeypatch,status):
    def handler(request):
        if request.method=='POST':return httpx.Response(202,json={'id':'task-one'})
        return httpx.Response(200,json={'status':'succeeded' if status=='expired' else status,
                                       'result_expired':status=='expired','error':'fixture-only-key'})
    requests=install(monkeypatch,handler)
    for _ in range(2):
        with pytest.raises(RuntimeError,match=status) as error:providers.transform('原文内容。','润色',cfg)
        assert 'fixture-only-key' not in str(error.value)
    assert len([r for r in requests if r.method=='POST'])==1


def test_cancellation_preserves_id_and_resume(cfg,monkeypatch):
    cancel=threading.Event()
    def handler(request):
        if request.method=='POST':return httpx.Response(202,json={'id':'task-one'})
        cancel.set()
        return httpx.Response(200,json={'status':'running'})
    requests=install(monkeypatch,handler)
    with pytest.raises(InterruptedError):providers.transform('原文内容。','润色',cfg,cancel=cancel)
    assert rows(cfg)[0][2]=='task-one' and len([r for r in requests if r.method=='POST'])==1


def test_wait_deadline_retains_id(cfg,monkeypatch):
    monkeypatch.setattr(projecthub,'WAIT_SECONDS',0)
    requests=install(monkeypatch,lambda r:httpx.Response(202,json={'id':'task-one'}) if r.method=='POST' else httpx.Response(200,json={'status':'queued'}))
    with pytest.raises(RuntimeError,match='still processing'):providers.transform('原文内容。','润色',cfg)
    assert rows(cfg)[0][2]=='task-one'
    assert len([r for r in requests if r.method=='POST'])==1


@pytest.mark.parametrize('kind',('llm','ask'))
def test_connection_is_discovery_only_and_lists_ids(cfg,monkeypatch,kind):
    requests=install(monkeypatch,lambda _:pytest.fail('Discovery sent a generation'))
    result=service_checks.check_service(kind,cfg,{'llm':'fixture-only-key','ask_llm':'fixture-only-key'})
    assert result['success'] and result['available_models']==['office-test']
    assert 'No generation' in result['detail'] and len(requests)==2


def test_unknown_model_never_submits(cfg,monkeypatch):
    cfg['llm_model']='missing'
    requests=install(monkeypatch,lambda _:pytest.fail('Invalid model submitted'))
    with pytest.raises(RuntimeError,match='office-test'):providers.transform('原文内容。','润色',cfg)
    assert len(requests)==2 and rows(cfg)==[]


def test_ask_invalid_json_preserves_context(cfg,monkeypatch):
    install(monkeypatch,lambda r:httpx.Response(202,json={'id':'task-one'}) if r.method=='POST' else done('bad JSON'))
    with pytest.raises(RuntimeError,match='invalid response'):providers.ask('改写','原文',cfg)


def test_text_limit_before_network(cfg,monkeypatch):
    requests=install(monkeypatch,lambda _:pytest.fail('Oversize request submitted'))
    with httpx.Client() as client:
        with pytest.raises(RuntimeError,match='100,000'):
            projecthub.completion(client,[{'role':'user','content':'文'*40000}],cfg,'fixture-only-key')
    assert not requests


@pytest.mark.parametrize('kind',('llm','ask'))
def test_refresh_accepts_empty_selected_model_and_draft_key(cfg,monkeypatch,kind):
    cfg.update(_model_discovery=True,llm_model='',ask_llm_model='')
    requests=install(monkeypatch,lambda _:pytest.fail('Refresh submitted a generation'))
    result=service_checks.check_service(kind,cfg,{'llm':'draft-key','ask_llm':'draft-key'})
    assert result['success'] and result['models']==[{'id':'office-test','name':'office-test'}]
    assert len(requests)==2 and all(r.method=='GET' for r in requests)
    assert all(r.headers['Authorization']=='Bearer draft-key' for r in requests)


def test_refresh_auth_failure_safe_and_actionable(cfg,monkeypatch):
    cfg['_model_discovery']=True
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:REAL_CLIENT(
        transport=httpx.MockTransport(lambda r:httpx.Response(401,json={'error':'sensitive-key-value'})),**kwargs))
    result=service_checks.check_service('llm',cfg,{'llm':'sensitive-key-value'})
    assert not result['success'] and 'HTTP 401' in result['detail']
    assert 'sensitive-key-value' not in str(result)

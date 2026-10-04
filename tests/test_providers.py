import copy
import pytest
import httpx
from murmur import providers
from murmur.storage import DEFAULTS

@pytest.mark.parametrize('status,content,error',[(200,{'choices':[{'message':{'content':'整理结果'}}]},False),(200,{'choices':[{'message':{'content':''}}]},True),(401,{},True),(429,{},True)])
def test_llm_responses(monkeypatch,status,content,error):
    cfg=copy.deepcopy(DEFAULTS);cfg.update(demo=False,ollama=False,ollama_auto=False,llm_url='https://fixture.invalid/v1')
    original=httpx.Client
    transport=httpx.MockTransport(lambda req:httpx.Response(status,json=content))
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(transport=transport,**kw));monkeypatch.setattr(providers,'credential',lambda name:'test-only')
    if error:
        with pytest.raises(RuntimeError):providers.transform('原文中的问题？','听写',cfg)
    else:assert providers.transform('原文中的问题？','听写',cfg)=='整理结果'

def test_llm_timeout(monkeypatch):
    cfg=copy.deepcopy(DEFAULTS);cfg.update(demo=False,ollama=False,ollama_auto=False,llm_url='https://fixture.invalid/v1');original=httpx.Client
    def handler(req):raise httpx.ReadTimeout('test timeout')
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handler),**kw));monkeypatch.setattr(providers,'credential',lambda name:'test-only')
    with pytest.raises(RuntimeError,match='timed out'):providers.transform('原文','听写',cfg)


@pytest.mark.parametrize('content',[{}, {'choices':[]}, {'choices':[{'message':{'content':None}}]}, {'choices':[{'message':{'content':[]}}]}])
def test_malformed_response_preserves_text(monkeypatch,content):
    cfg=copy.deepcopy(DEFAULTS);cfg.update(demo=False,ollama=False,ollama_auto=False,llm_url='https://fixture.invalid/v1');original=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(lambda req:httpx.Response(200,json=content)),**kw))
    monkeypatch.setattr(providers,'credential',lambda name:'test-only')
    with pytest.raises(RuntimeError,match='invalid response'):providers.transform('Original text','听写',cfg)


def test_canceled_request_never_calls_model(monkeypatch):
    import threading
    canceled=threading.Event();canceled.set();cfg=copy.deepcopy(DEFAULTS);cfg.update(demo=False,ollama=False,ollama_auto=False,llm_url='https://fixture.invalid/v1')
    monkeypatch.setattr(providers,'credential',lambda name:pytest.fail('Canceled request accessed credentials'))
    with pytest.raises(InterruptedError):providers.transform('Original text','听写',cfg,cancel=canceled)


def test_cancel_closes_active_client_and_releases_slot(monkeypatch):
    import threading
    entered=threading.Event();closed=threading.Event();cancel=threading.Event();outcomes=[]
    class FakeClient:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):self.close()
        def close(self):closed.set()
        def post(self,*args,**kwargs):
            entered.set();assert closed.wait(2)
            raise httpx.ReadError('Connection was closed by cancellation')
    cfg=copy.deepcopy(DEFAULTS);cfg.update(demo=False,ollama=False,ollama_auto=False,llm_url='https://fixture.invalid/v1')
    monkeypatch.setattr(httpx,'Client',FakeClient);monkeypatch.setattr(providers,'credential',lambda name:'test-only')
    slots=threading.BoundedSemaphore(1);monkeypatch.setattr(providers,'_LLM_SLOTS',slots)
    def work():
        try:providers.transform('Original text','听写',cfg,cancel=cancel)
        except InterruptedError:outcomes.append('canceled')
    worker=threading.Thread(target=work);worker.start();assert entered.wait(2);cancel.set();worker.join(2)
    assert not worker.is_alive() and outcomes==['canceled'] and closed.is_set()
    assert slots.acquire(blocking=False);slots.release()


def test_concurrency_is_bounded_and_waiting_request_can_cancel(monkeypatch):
    import threading
    ready=threading.Event();release=threading.Event();third_waiting=threading.Event();cancel=threading.Event()
    guard=threading.Lock();counts={'clients':0,'credentials':0};outcomes=[]
    class FakeClient:
        def __init__(self,**kwargs):
            with guard:
                counts['clients']+=1
                if counts['clients']==2:ready.set()
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,*args,**kwargs):
            assert release.wait(2)
            return httpx.Response(200,json={'choices':[{'message':{'content':'Completed'}}]})
    def credentials(name):
        with guard:
            counts['credentials']+=1
            if counts['credentials']==3:third_waiting.set()
        return 'test-only'
    cfg=copy.deepcopy(DEFAULTS);cfg.update(demo=False,ollama=False,ollama_auto=False,llm_url='https://fixture.invalid/v1')
    monkeypatch.setattr(httpx,'Client',FakeClient);monkeypatch.setattr(providers,'credential',credentials)
    monkeypatch.setattr(providers,'_LLM_SLOTS',threading.BoundedSemaphore(2))
    def work(token=None):
        try:outcomes.append(providers.transform('Original text','听写',cfg,cancel=token))
        except InterruptedError:outcomes.append('Canceled')
    first=[threading.Thread(target=work) for _ in range(2)]
    for worker in first:worker.start()
    assert ready.wait(2)
    third=threading.Thread(target=work,args=(cancel,));third.start();assert third_waiting.wait(2);cancel.set();third.join(2)
    assert not third.is_alive() and counts['clients']==2 and outcomes==['Canceled']
    release.set()
    for worker in first:worker.join(2);assert not worker.is_alive()
    assert sorted(outcomes)==['Canceled','Completed','Completed']


@pytest.mark.parametrize('ollama',[False,True])
def test_thinking_suppression_only_for_ollama(monkeypatch,ollama):
    import json
    cfg=copy.deepcopy(DEFAULTS);cfg.update(demo=False,ollama=ollama,ollama_auto=False)
    original=httpx.Client;bodies=[]
    def handler(request):
        if request.method=='GET':return httpx.Response(404)
        bodies.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':'Result'}}]})
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    monkeypatch.setattr(providers,'credential',lambda name:'test-only' if not ollama else pytest.fail('Ollama accessed an API key'))
    assert providers.transform('Original words','听写',cfg)=='Result'
    assert (bodies[0].get('reasoning_effort')=='none')==ollama

"""Auto resolves an installed local model before sending text, never to cloud."""
import copy
import json
import threading
import httpx
import pytest
from murmur import providers,service_checks
from murmur.local_llm import resolve_model,LocalModelError,auto_enabled
from murmur import local_llm
from murmur.storage import DEFAULTS,validated_config,Store


def item(name,params='2B',size=2_000_000_000,**extra):
    return dict(name=name,size=size,details=dict(family='qwen',parameter_size=params),**extra)


def config(**values):
    cfg=copy.deepcopy(DEFAULTS);cfg.update(demo=False,ollama=True,ollama_auto=True);cfg.update(values);return cfg


@pytest.fixture(autouse=True)
def isolated_capability_cache():
    with local_llm._CAPABILITY_LOCK:local_llm._CAPABILITY_CACHE.clear()
    yield
    with local_llm._CAPABILITY_LOCK:local_llm._CAPABILITY_CACHE.clear()


def client(body,status=200,seen=None):
    def handler(request):
        if seen is not None:seen.append(request)
        return httpx.Response(status,json=body)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_auto_orders_by_parameter_count_and_skips_cloud_embedding_and_remote():
    seen=[]
    models=[item('qwen:4b','4B',1),item('qwen3.5:2b','2.3B'),item('embedding:tiny','.1B'),
        item('qwen:cloud','.1B'),item('proxy-model','.1B',remote_host='cloud.invalid'),item('qwen:9b','9B')]
    with client(dict(models=models),seen=seen) as c:
        assert resolve_model(c,config())=='qwen3.5:2b'
    assert str(seen[0].url)=='http://127.0.0.1:11434/api/tags'
    assert len(seen)==1 and seen[0].method=='GET' and not seen[0].content


@pytest.mark.parametrize('body',[{},[],dict(models='bad'),dict(models=[]),dict(models=[item('nomic-embed-text'),item('tiny-cloud')])])
def test_missing_or_unusable_inventory_is_an_actionable_error(body):
    with client(body) as c:
        with pytest.raises(LocalModelError):resolve_model(c,config())


def test_auto_is_deterministic_when_inventory_order_changes():
    models=[item('z-model'),item('qwen-model'),item('a-model')]
    for order in (models,models[::-1]):
        with client(dict(models=order)) as c:assert resolve_model(c,config())=='qwen-model'


def test_manual_and_online_modes_do_not_request_inventory():
    with client({}) as c:
        c.stream=lambda *args,**kwargs:pytest.fail('Explicit model requested inventory')
        assert resolve_model(c,config(ollama_auto=False,llm_model='my-model:4b'))=='my-model:4b'
        assert resolve_model(c,config(ollama=False,llm_url='https://fixture.invalid/v1',llm_model='online-model'))=='online-model'
        with pytest.raises(LocalModelError):resolve_model(c,config(ollama_auto=False,llm_model='qwen:cloud'))


def test_cancel_before_inventory_does_not_make_request():
    cancel=threading.Event();cancel.set()
    with client({}) as c:
        c.stream=lambda *args,**kwargs:pytest.fail('Cancelled inventory request')
        with pytest.raises(InterruptedError):resolve_model(c,config(),cancel)


def test_inventory_failure_does_not_send_text_or_use_credentials(monkeypatch):
    seen=[];original=httpx.Client
    def handler(request):
        seen.append(request);return httpx.Response(503,json={})
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    monkeypatch.setattr(providers,'credential',lambda name:pytest.fail('Auto used cloud credentials'))
    with pytest.raises(LocalModelError):providers.transform('Public fixture','听写',config())
    assert len(seen)==1 and seen[0].method=='GET'


@pytest.mark.parametrize('operation',['transform','check'])
def test_actual_selected_model_sent_and_usage_returned(operation,monkeypatch):
    seen=[];usage=[];original=httpx.Client
    def handler(request):
        seen.append(request)
        if request.method=='GET':return httpx.Response(200,json=dict(models=[item('chosen:2b')]))
        assert json.loads(request.content)['model']=='chosen:2b'
        return httpx.Response(200,json=dict(choices=[dict(message=dict(content='OK'))],usage=dict(prompt_tokens=8,completion_tokens=1,total_tokens=9)))
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    monkeypatch.setattr(providers,'credential',lambda name:pytest.fail('Local model used credentials'))
    if operation=='transform':assert providers.transform('Public fixture','听写',config(),usage_sink=usage.append)=='OK'
    else:assert service_checks.check_service('llm',config(),usage_sink=usage.append)['success']
    assert len(seen)==2 and len(usage)==1
    assert usage[0]['model']=='chosen:2b' and usage[0]['local'] and usage[0]['total_tokens']==9


def test_new_defaults_local_auto_and_saved_explicit_model_remains_explicit(tmp_path):
    fresh=Store(tmp_path)
    assert not fresh.config['ollama'] and fresh.config['ollama_auto']
    saved=validated_config(dict(ollama=True,llm_model='custom:latest',llm_url='http://192.168.1.2:11434/v1'))
    assert not saved['ollama_auto'] and saved['llm_model']=='custom:latest'
    saved=validated_config(dict(ollama=False,llm_model='cloud-model',llm_url='https://fixture.invalid/v1'))
    assert not saved['ollama'] and saved['llm_model']=='cloud-model'


def compatible_model(name,**extra):return dict(id=name,object='model',owned_by='local',**extra)


def test_generic_local_auto_uses_standard_models_and_ranked_parameter_ids():
    seen=[];models=[compatible_model('qwen3.5:4b'),compatible_model('Qwen/Qwen3.5-2B'),
        compatible_model('nomic-embed-text'),compatible_model('qwen3.5:cloud'),
        compatible_model('remote-tiny',remote_model='cloud-name'),compatible_model('qwen3.5:9b')]
    cfg=config(ollama=False,llm_url='http://localhost:1234/v1',llm_model='')
    with client(dict(data=models),seen=seen) as c:assert resolve_model(c,cfg)=='Qwen/Qwen3.5-2B'
    assert str(seen[0].url)=='http://localhost:1234/v1/models'
    assert seen[0].headers['Authorization']=='Bearer local' and len(seen)==1


def test_generic_auto_unknown_metadata_deterministic_and_does_not_invent_loaded_state():
    models=[compatible_model('z-chat',loaded=True),compatible_model('a-chat')]
    for order in (models,models[::-1]):
        with client(dict(data=order)) as c:
            assert resolve_model(c,config(ollama=False))=='a-chat'


@pytest.mark.parametrize('body',[{}, [], dict(data=[]), dict(data='bad'),dict(data=[compatible_model('tiny-cloud')])])
def test_generic_empty_invalid_or_cloud_inventory_never_falls_back(body):
    with client(body) as c:
        with pytest.raises(LocalModelError):resolve_model(c,config(ollama=False))


@pytest.mark.parametrize('url',['http://localhost:8000/v1','http://[::1]:1234/v1'])
@pytest.mark.parametrize('operation',['transform','check'])
def test_generic_local_transform_and_check_share_protocol_without_cloud_credentials(operation,url,monkeypatch):
    seen=[];usage=[];original=httpx.Client
    def handler(request):
        seen.append(request)
        assert request.headers['Authorization']=='Bearer local'
        if request.url.path.endswith('/api/version'):return httpx.Response(404)
        if request.method=='GET':return httpx.Response(200,json=dict(data=[compatible_model('qwen3.5:2b')]))
        body=json.loads(request.content)
        assert body['model']=='qwen3.5:2b' and 'reasoning_effort' not in body and 'chat_template_kwargs' not in body
        return httpx.Response(200,json=dict(model='actual-served:2b',choices=[dict(message=dict(content='OK'))],
            usage=dict(prompt_tokens=8,completion_tokens=1,total_tokens=9)))
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    monkeypatch.setattr(providers,'credential',lambda name:pytest.fail('Local request read cloud key'))
    monkeypatch.setattr(service_checks,'credential',lambda name:pytest.fail('Local check read cloud key'))
    cfg=config(ollama=False,llm_url=url,llm_model='')
    if operation=='transform':assert providers.transform('Public fixture','听写',cfg,usage_sink=usage.append)=='OK'
    else:assert service_checks.check_service('llm',cfg,{'llm':'saved-cloud-fixture'},usage_sink=usage.append)['success']
    assert len(seen)==3 and len(usage)==1 and usage[0]['model']=='actual-served:2b'
    assert usage[0]['local'] and usage[0]['total_tokens']==9 and usage[0]['cost_usd']==0


def test_remote_generic_auto_flag_is_ignored_and_missing_cloud_key_is_rejected(monkeypatch):
    cfg=config(ollama=False,llm_url='https://external.invalid/v1',llm_model='online-model')
    assert not auto_enabled(cfg)
    with client({}) as c:
        c.stream=lambda *args,**kwargs:pytest.fail('Cloud Auto queried inventory')
        assert resolve_model(c,cfg)=='online-model'
    monkeypatch.setattr(providers,'credential',lambda name:'')
    with pytest.raises(RuntimeError,match='API key'):providers.transform('Public fixture','听写',cfg)


def test_generic_inventory_error_cancellation_and_cloud_manual_are_isolated():
    cfg=config(ollama=False)
    with client({},status=503) as c:
        with pytest.raises(LocalModelError):resolve_model(c,cfg)
    canceled=threading.Event()
    def handler(request):
        canceled.set();return httpx.Response(200,json=dict(data=[compatible_model('fixture:2b')]))
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(InterruptedError):resolve_model(c,cfg,canceled)
    with client({}) as c:
        with pytest.raises(LocalModelError):resolve_model(c,dict(cfg,ollama_auto=False,llm_model='qwen:cloud'))


def test_inventory_redirect_cannot_send_model_text_to_an_external_endpoint():
    requests=[]
    def handler(request):
        requests.append(request)
        return httpx.Response(302,headers={'Location':'https://external.invalid/models'})
    with httpx.Client(transport=httpx.MockTransport(handler),follow_redirects=True) as c:
        with pytest.raises(LocalModelError):resolve_model(c,config(ollama=False))
    assert len(requests)==1 and requests[0].url.host=='127.0.0.1'


def test_local_inventory_is_bounded_and_remote_metadata_is_rejected():
    with client(dict(data=[compatible_model('ordinary-name',type='cloud')])) as c:
        with pytest.raises(LocalModelError):resolve_model(c,config(ollama=False))
    with client(dict(data=[compatible_model('x'*1_048_576)])) as c:
        with pytest.raises(LocalModelError,match='too large'):resolve_model(c,config(ollama=False))


def test_loopback_cloud_usage_cannot_report_zero_external_fee():
    from murmur.usage import usage_metadata
    cfg=config(ollama=False)
    data=dict(model='qwen:cloud',usage=dict(prompt_tokens=8,completion_tokens=1,total_tokens=9))
    usage=usage_metadata(data,cfg)
    assert usage['external'] and not usage['local'] and usage['cost_usd'] is None


@pytest.mark.parametrize('version',['0.18.0','1.0.0','0.19.0-rc.1+build.2'])
def test_ollama_version_capability_and_positive_cache(version):
    seen=[];cfg=config(ollama=False)
    with client(dict(version=version),seen=seen) as c:
        assert local_llm.request_extensions(c,cfg)=={'reasoning_effort':'none'}
        assert local_llm.request_extensions(c,cfg)=={'reasoning_effort':'none'}
    assert len(seen)==1 and seen[0].url.path=='/api/version' and not seen[0].content
    assert seen[0].headers['Authorization']=='Bearer local'
    assert all(0 < value <= 1 for value in seen[0].extensions['timeout'].values())


@pytest.mark.parametrize('value',[None,'','v1.0.0','1.0','01.0.0','0.19.0-01','0.19.0 SECRET',True,{},'0.19.0'+'x'*8192])
def test_invalid_version_does_not_enable_thinking_extension(value):
    with client(dict(version=value)) as c:
        assert local_llm.request_extensions(c,config(ollama=False))=={}


def test_capability_unknown_and_transient_failures_do_not_block_retry():
    cfg=config(ollama=False);seen=[];failures=[503,'timeout',200]
    def handler(request):
        seen.append(request);status=failures.pop(0)
        if status=='timeout':raise httpx.ReadTimeout('fixture private endpoint')
        return httpx.Response(status,json=dict(version='0.18.0'))
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        assert local_llm.request_extensions(c,cfg)=={}
        assert local_llm.request_extensions(c,cfg)=={}
        assert local_llm.request_extensions(c,cfg)=={'reasoning_effort':'none'}
    assert len(seen)==3


def test_capability_404_expires_promptly_and_cache_entries_are_bounded(monkeypatch):
    now=[1.];monkeypatch.setattr(local_llm.time,'monotonic',lambda:now[0])
    seen=[];cfg=config(ollama=False)
    with client({},status=404,seen=seen) as c:
        assert local_llm.request_extensions(c,cfg)=={}
        assert local_llm.request_extensions(c,cfg)=={}
        assert len(seen)==1
        now[0]+=6
        assert local_llm.request_extensions(c,cfg)=={}
        assert len(seen)==2
        for port in range(100,135):
            local_llm.request_extensions(c,config(ollama=False,llm_url=f'http://localhost:{port}/v1'))
    assert len(local_llm._CAPABILITY_CACHE)==32


def test_capability_cancel_is_not_cached_and_explicit_or_cloud_modes_never_probe():
    cfg=config(ollama=False);cancel=threading.Event()
    def handler(request):
        cancel.set();return httpx.Response(200,json=dict(version='0.18.0'))
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(InterruptedError):local_llm.request_extensions(c,cfg,cancel)
        assert not local_llm._CAPABILITY_CACHE
    with client({}) as c:
        c.stream=lambda *args,**kwargs:pytest.fail('Ineligible capability probe')
        assert local_llm.request_extensions(c,config())=={'reasoning_effort':'none'}
        assert local_llm.request_extensions(c,config(ollama=False,llm_url='https://external.invalid/v1'))=={}
        with pytest.raises(InterruptedError):local_llm.request_extensions(c,config(),cancel)


def test_capability_redirect_is_not_followed_and_total_byte_deadline_is_checked(monkeypatch):
    seen=[]
    def redirect(request):
        seen.append(request);return httpx.Response(302,headers={'Location':'https://external.invalid/api/version'})
    with httpx.Client(transport=httpx.MockTransport(redirect),follow_redirects=True) as c:
        assert local_llm.request_extensions(c,config(ollama=False))=={}
    assert len(seen)==1 and seen[0].url.host=='127.0.0.1'
    now=[1.];monkeypatch.setattr(local_llm.time,'monotonic',lambda:now[0])
    class SlowBody(httpx.SyncByteStream):
        def __iter__(self):
            now[0]+=1.1;yield b'{"version":"0.18.0"}'
    with httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,stream=SlowBody()))) as c:
        assert local_llm.request_extensions(c,config(ollama=False))=={}
    assert not local_llm._CAPABILITY_CACHE


@pytest.mark.parametrize('operation',['transform','check'])
def test_detected_ollama_compatible_request_is_fast_without_changing_adapter(operation,monkeypatch):
    seen=[];usage=[];original=httpx.Client
    cfg=config(ollama=False,llm_model='',llm_url='http://localhost:11434/v1')
    def handler(request):
        seen.append(request)
        if request.url.path=='/api/version':return httpx.Response(200,json=dict(version='0.18.0'))
        if request.url.path=='/v1/models':return httpx.Response(200,json=dict(data=[compatible_model('qwen3.5:2b')]))
        body=json.loads(request.content)
        assert body['reasoning_effort']=='none' and body['model']=='qwen3.5:2b'
        assert request.url.path=='/v1/chat/completions' and 'chat_template_kwargs' not in body
        return httpx.Response(200,json=dict(model='qwen3.5:2b',choices=[dict(message=dict(content='OK'))],
            usage=dict(prompt_tokens=8,completion_tokens=1,total_tokens=9)))
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    monkeypatch.setattr(providers,'credential',lambda name:pytest.fail('Probe read cloud key'))
    monkeypatch.setattr(service_checks,'credential',lambda name:pytest.fail('Probe read cloud key'))
    if operation=='transform':assert providers.transform('Public fixture','听写',cfg,usage_sink=usage.append)=='OK'
    else:assert service_checks.check_service('llm',cfg,usage_sink=usage.append)['success']
    assert not cfg['ollama'] and len(seen)==3 and len(usage)==1 and usage[0]['total_tokens']==9

"""Config persistence and controller validation use temporary data and a fake Vault."""
import copy
from types import SimpleNamespace

import pytest
from murmur.storage import DEFAULTS, Store, validated_config
from murmur import providers
from murmur.cloud_asr import HTTP_DEFAULTS, HttpAsrRecorder


def test_profiles_preserve_valid_fields_and_exclude_credentials():
    profiles={'openai':{'url':'https://example.invalid/v1','model':'custom','language':'zh',
                        'timeout':17,'key':'synthetic-must-not-save'},
              'groq':{'url':False,'model':'whisper-large-v3','timeout':True},
              'http_asr':{'model':'x'*2001,'timeout':181},'unknown':{'model':'bad'}}
    result=validated_config({'asr_backend':'openai','asr_http_profiles':profiles})
    assert result['asr_backend']=='openai'
    assert result['asr_http_profiles']=={
        'openai':{'url':'https://example.invalid/v1','model':'custom','language':'zh','timeout':17},
        'groq':{'model':'whisper-large-v3'}}
    result['asr_http_profiles']['openai']['model']='changed'
    assert profiles['openai']['model']=='custom'


@pytest.mark.parametrize('field,value',[('asr_http_timeout',False),('audio_lead_padding_ms',-1),
    ('audio_tail_padding_ms',1001),('audio_silence_threshold',float('nan')),
    ('audio_silence_threshold',True),('audio_noise_gate','yes')])
def test_invalid_capture_settings_keep_defaults(field,value):
    assert validated_config({field:value})[field]==DEFAULTS[field]


@pytest.mark.parametrize('backend',['openai','groq','http_asr'])
def test_factory_routes_only_explicit_real_http_backends(backend):
    config=copy.deepcopy(DEFAULTS);config.update(demo=False,asr_backend=backend)
    assert isinstance(providers.make_recorder(config,lambda _:None,lambda _:None,None),HttpAsrRecorder)
    config['demo']=True
    assert type(providers.make_recorder(config,lambda _:None,lambda _:None,None)) is providers.Recorder


@pytest.mark.parametrize('field,value',[('asr_http_url','https://changed.invalid/v1'),
    ('asr_http_model','different'),('asr_http_language','zh'),('asr_http_timeout',17)])
def test_http_configuration_change_invalidates_inflight_catalog_fingerprint(field,value):
    from murmur.app import Controller
    cfg=copy.deepcopy(DEFAULTS);cfg.update(asr_backend='openai')
    original=Controller.service_snapshot('asr',cfg,{'asr_openai_key':'synthetic-first'})
    cfg[field]=value
    assert Controller.service_snapshot('asr',cfg,{'asr_openai_key':'synthetic-first'})!=original


def test_http_key_change_invalidates_fingerprint_without_exposing_it():
    from murmur.app import Controller
    cfg=copy.deepcopy(DEFAULTS)
    original=Controller.service_snapshot('asr',cfg,{'asr_groq_key':'synthetic-first'})
    revised=Controller.service_snapshot('asr',cfg,{'asr_groq_key':'synthetic-next'})
    assert len(original)==64 and original!=revised and 'synthetic' not in original


def controller(tmp_path,monkeypatch):
    from murmur import app as module
    store=Store(tmp_path)
    writes=[];warnings=[];cleared=[]
    monkeypatch.setattr(module,'credential',lambda name,value=None:writes.append((name,value)))
    monkeypatch.setattr(module.QMessageBox,'warning',lambda *args:warnings.append(args[-1]))
    dummy=SimpleNamespace(position=lambda:None,state=lambda *args:None)
    field=SimpleNamespace(blockSignals=lambda _:False,clear=lambda:cleared.append(True))
    window=SimpleNamespace(settings_status=SimpleNamespace(setText=lambda _:None),refresh=lambda:None,
                           asr_http_key=field,_http_asr_keys={'openai':'synthetic-draft'})
    c=module.Controller.__new__(module.Controller)
    c.session=None;c.service_tests={};c.window=window;c.store=store;c.bubble=copy.copy(dummy)
    c.result_bubble=copy.copy(dummy);c.keys=SimpleNamespace(machine=SimpleNamespace(cfg=store.config))
    return c,writes,warnings,cleared


def test_save_http_profile_validates_protocol_and_writes_only_independent_slot(tmp_path,monkeypatch):
    c,writes,warnings,cleared=controller(tmp_path,monkeypatch)
    config=copy.deepcopy(c.store.config)
    config.update(asr_backend='openai',asr_http_url=HTTP_DEFAULTS['openai']['url'],
                  asr_http_model='gpt-transcribe',asr_model='',asr_url='not-a-websocket')
    c.save_settings(config,{'asr_openai_key':'synthetic-key'})
    assert not warnings and writes==[('asr_openai_key','synthetic-key')]
    assert cleared and c.window._http_asr_keys=={'openai':''}
    assert c.store.path.exists() and c.store.config['asr_http_model']=='gpt-transcribe'
    c.store.db.close()


@pytest.mark.parametrize('url,model',[('http://public.example.invalid/v1','speech'),
    ('https://example.invalid/v1?key=secret','speech'),('https://example.invalid/v1','')])
def test_invalid_http_draft_does_not_touch_credentials_or_saved_settings(tmp_path,monkeypatch,url,model):
    c,writes,warnings,cleared=controller(tmp_path,monkeypatch)
    config=copy.deepcopy(c.store.config)
    config.update(asr_backend='http_asr',asr_http_url=url,asr_http_model=model)
    c.save_settings(config,{'asr_http_key':'synthetic-key'})
    assert warnings and not writes and not cleared and not c.store.path.exists()
    assert c.store.config['asr_backend']=='offline'
    c.store.db.close()

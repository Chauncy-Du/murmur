"""Local engine routing, cache separation and imported ONNX model checks."""
import copy
import hashlib
import json
import threading
from types import SimpleNamespace

import pytest

from murmur import offline, providers, service_checks, models
from murmur.storage import DEFAULTS


def local_config(folder, engine='sensevoice', filename='model.int8.onnx'):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / filename).write_bytes(b'fixture-model')
    (folder / 'tokens.txt').write_bytes(b'fixture-tokens')
    cfg=copy.deepcopy(DEFAULTS)
    cfg.update(demo=False, asr_backend='offline', offline_engine=engine,
               offline_model_dir=str(folder))
    return cfg


def test_paraformer_cpu_factory_and_cache_ignore_unused_language(tmp_path, monkeypatch):
    offline._prepare_runtime()
    import sherpa_onnx
    calls=[]
    recognizer=object()
    monkeypatch.setattr(offline, '_cached_key', None)
    monkeypatch.setattr(offline, '_cached_recognizer', None)
    def create(**options):
        calls.append(options)
        return recognizer
    monkeypatch.setattr(sherpa_onnx.OfflineRecognizer, 'from_paraformer', create)
    cfg=local_config(tmp_path, 'paraformer')
    assert offline.load_recognizer(cfg) is recognizer
    cfg['offline_language']='ja'  # SenseVoice preference is unused here.
    assert offline.load_recognizer(cfg) is recognizer
    assert len(calls)==1
    assert calls[0]['provider']=='cpu'
    assert calls[0]['paraformer']==str(tmp_path/'model.int8.onnx')
    assert calls[0]['sample_rate']==16000 and calls[0]['num_threads']==2
    assert calls[0]['decoding_method']=='greedy_search'
    assert 'language' not in calls[0] and 'use_itn' not in calls[0]


def test_engine_switch_cannot_reuse_other_engine_recognizer(tmp_path, monkeypatch):
    offline._prepare_runtime()
    import sherpa_onnx
    first, second=object(), object()
    monkeypatch.setattr(offline, '_cached_key', None)
    monkeypatch.setattr(offline, '_cached_recognizer', None)
    monkeypatch.setattr(sherpa_onnx.OfflineRecognizer, 'from_sense_voice', lambda **kw:first)
    monkeypatch.setattr(sherpa_onnx.OfflineRecognizer, 'from_paraformer', lambda **kw:second)
    cfg=local_config(tmp_path)
    assert offline.load_recognizer(cfg) is first
    cfg['offline_engine']='paraformer'
    assert offline.load_recognizer(cfg) is second


@pytest.mark.parametrize('engine', ['sensevoice', 'paraformer'])
def test_fp32_onnx_folder_is_accepted(tmp_path, engine):
    cfg=local_config(tmp_path, engine, 'model.onnx')
    model, tokens, language, threads=offline.model_files(cfg)
    assert model.name=='model.onnx' and tokens.name=='tokens.txt'
    assert language=='auto' and threads==2


def test_invalid_engine_fails_before_native_load_or_network(tmp_path, monkeypatch):
    import socket
    monkeypatch.setattr(socket, 'socket', lambda *a, **kw:pytest.fail('Unexpected network access'))
    monkeypatch.setattr(offline, '_prepare_runtime', lambda:pytest.fail('Unexpected native load'))
    cfg=local_config(tmp_path, 'unsupported')
    with pytest.raises(RuntimeError, match='supported local model'):
        offline.load_recognizer(cfg)


@pytest.mark.parametrize('actual,selected', [('sensevoice','paraformer'),
                                           ('paraformer','sensevoice')])
def test_managed_model_engine_mismatch_fails_before_native_load(tmp_path,monkeypatch,actual,selected):
    cfg=local_config(tmp_path,selected)
    (tmp_path/'murmur-model.json').write_text(json.dumps({'engine':actual}),'utf-8')
    monkeypatch.setattr(offline,'_prepare_runtime',lambda:pytest.fail('Unexpected native load'))
    with pytest.raises(RuntimeError,match='matching local engine'):
        offline.load_recognizer(cfg)


def test_legacy_sensevoice_manifest_remains_usable_and_rejects_paraformer(tmp_path):
    cfg=local_config(tmp_path)
    (tmp_path/'murmur-model.json').write_text(json.dumps({'model':'SenseVoice Small INT8'}),'utf-8')
    assert offline.model_files(cfg)[0].name=='model.int8.onnx'
    cfg['offline_engine']='paraformer'
    with pytest.raises(RuntimeError,match='contains SenseVoice'):
        offline.model_files(cfg)


def test_default_factory_uses_local_recorder_without_credentials(monkeypatch):
    monkeypatch.setattr(providers, 'credential', lambda *a:pytest.fail('Unexpected credential access'))
    assert isinstance(providers.make_recorder({}, lambda text:None, lambda level:None,
                                             threading.Event()), offline.OfflineRecorder)


def test_paraformer_check_uses_own_manifest_and_rejects_corruption(tmp_path, monkeypatch):
    cfg=local_config(tmp_path, 'paraformer')
    files={path.name:(path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
           for path in tmp_path.iterdir()}
    monkeypatch.setitem(models.MODELS, 'paraformer', dict(models.MODELS['paraformer'], files=files))
    loaded=[]
    monkeypatch.setattr(offline, 'load_recognizer', lambda *a:loaded.append(True))
    monkeypatch.setattr(service_checks, 'credential', lambda *a:pytest.fail('Unexpected credentials'))
    monkeypatch.setattr(service_checks.websocket, 'create_connection', lambda *a, **kw:pytest.fail('Unexpected network'))
    assert service_checks.check_service('asr', cfg)['success']
    (tmp_path/'tokens.txt').write_bytes(b'corrupted')
    result=service_checks.check_service('asr', cfg)
    assert not result['success'] and result['summary']=='Model integrity check failed'
    assert loaded==[True]


def test_imported_fp32_check_reports_loader_validation(tmp_path, monkeypatch):
    cfg=local_config(tmp_path, 'paraformer', 'model.onnx')
    monkeypatch.setattr(offline, 'load_recognizer', lambda *a:object())
    result=service_checks.check_service('asr', cfg)
    assert result['success'] and 'imported local model loaded' in result['detail']
    assert 'not checked against the pinned download' in result['detail']


def extended_local_config(folder,engine,acceleration='cpu'):
    """Supply tiny named files without importing any native model libraries."""
    folder.mkdir(parents=True,exist_ok=True)
    spec=models.model_spec(engine,acceleration)
    for alternatives in spec['required_files']:
        (folder/alternatives[0]).write_bytes(('fixture '+alternatives[0]).encode('utf-8'))
    values=copy.deepcopy(DEFAULTS)
    values.update(demo=False,asr_backend='offline',offline_engine=engine,
                  offline_acceleration=acceleration,offline_model_dir=str(folder),
                  offline_language='en',offline_threads=3)
    return values


@pytest.fixture
def isolated_worker_cache(monkeypatch):
    # Exercise production lock/cache logic with independent synchronization
    # objects, while preserving another test's cache when this fixture exits.
    monkeypatch.setattr(offline,'_cached_key',None)
    monkeypatch.setattr(offline,'_cached_recognizer',None)
    monkeypatch.setattr(offline,'_MODEL_LOCK',threading.Lock())
    monkeypatch.setattr(offline,'_DECODE_SLOT',threading.BoundedSemaphore(1))
    monkeypatch.setattr(offline,'_prepare_runtime',lambda:pytest.fail('Isolated engines must not load the main-process ONNX runtime'))


def speech_pcm():
    import numpy as np
    return np.full(1600,1000,dtype='<i2').tobytes()


class TinyWorker:
    def __init__(self,name,events):
        self.name=name;self.events=events;self.is_alive=True;self.diagnostics={}
        self.cancel_calls=[];self.decoded=[]

    def close(self):
        self.events.append(('close',self.name));self.is_alive=False

    def create_stream(self):
        assert self.is_alive,'A closed worker must never receive recorded audio'
        stream=SimpleNamespace(result=SimpleNamespace(text=''))
        def accept(rate,samples):stream.rate=rate;stream.samples=samples
        stream.accept_waveform=accept
        return stream

    def decode_stream(self,stream,cancel=None):
        assert self.is_alive
        self.cancel_calls.append(cancel);self.decoded.append(stream)
        stream.result.text='<|en|>Recognized with '+self.name


def assert_offline_locks_released():
    assert offline._MODEL_LOCK.acquire(blocking=False),'Model lock leaked'
    offline._MODEL_LOCK.release()
    assert offline._DECODE_SLOT.acquire(blocking=False),'Decode slot leaked'
    assert not offline._DECODE_SLOT.acquire(blocking=False),'Decode slot capacity was increased'
    offline._DECODE_SLOT.release()


@pytest.mark.parametrize('engine,acceleration,provider,llm_gpu,language',[
    ('sensevoice','gpu','DML',True,'en'),
    ('fun_asr_nano','cpu','CPU',False,'auto'),
    ('qwen_asr','gpu','DML',True,'auto'),
])
def test_isolated_model_route_passes_backend_and_caches_only_relevant_language(
        tmp_path,monkeypatch,isolated_worker_cache,engine,acceleration,provider,llm_gpu,language):
    from murmur import gguf_asr
    cfg=extended_local_config(tmp_path,engine,acceleration)
    calls=[];workers=[];events=[];cancel=threading.Event()
    def load(selected,folder,**options):
        calls.append((selected,folder,options))
        worker=TinyWorker(selected+'-'+str(len(calls)),events);workers.append(worker)
        return worker
    monkeypatch.setattr(gguf_asr,'load_model',load)
    first=offline.load_recognizer(cfg,cancel)
    assert offline.load_recognizer(dict(cfg),cancel) is first
    assert calls==[(engine,tmp_path,{'threads':3,'onnx_provider':provider,
                                     'llm_use_gpu':llm_gpu,'language':language,'cancel':cancel})]
    cfg['offline_language']='ja'
    selected=offline.load_recognizer(cfg,cancel)
    if engine=='sensevoice':
        assert selected is workers[1] and not first.is_alive
        assert events==[('close',first.name)]
        assert calls[1][2]['language']=='ja'
    else:
        assert selected is first and len(calls)==1
    assert_offline_locks_released()


def test_engine_and_acceleration_switch_close_previous_worker_before_loading(
        tmp_path,monkeypatch,isolated_worker_cache):
    from murmur import gguf_asr
    configurations=[extended_local_config(tmp_path/'sensevoice','sensevoice','gpu'),
                    extended_local_config(tmp_path/'nano','fun_asr_nano','cpu'),
                    extended_local_config(tmp_path/'qwen','qwen_asr','gpu')]
    configurations.append(dict(configurations[-1],offline_acceleration='cpu'))
    events=[];workers=[];calls=[]
    def load(engine,folder,**options):
        if workers:assert not workers[-1].is_alive,'Obsolete worker stayed alive while another model loaded'
        events.append(('load',engine,options['onnx_provider']))
        calls.append((engine,folder,options));worker=TinyWorker(engine+'-'+str(len(calls)),events)
        workers.append(worker);return worker
    monkeypatch.setattr(gguf_asr,'load_model',load)
    for values in configurations:
        recognizer=offline.load_recognizer(values)
        assert offline.load_recognizer(values) is recognizer
    assert [(engine,options['onnx_provider'],options['llm_use_gpu']) for engine,folder,options in calls]==[
        ('sensevoice','DML',True),('fun_asr_nano','CPU',False),
        ('qwen_asr','DML',True),('qwen_asr','CPU',False)]
    assert [event[0] for event in events]==['load','close','load','close','load','close','load']
    assert all(not worker.is_alive for worker in workers[:-1]) and workers[-1].is_alive
    assert_offline_locks_released()


@pytest.mark.parametrize('engine',['fun_asr_nano','qwen_asr'])
def test_gguf_decode_receives_request_cancel_event_and_releases_decode_slot(
        tmp_path,monkeypatch,isolated_worker_cache,engine):
    cfg=extended_local_config(tmp_path,engine)
    cancel=threading.Event();received=[]
    class CancelDuringDecode(TinyWorker):
        def decode_stream(self,stream,cancel=None):
            received.append(cancel);cancel.set();raise InterruptedError()
    worker=CancelDuringDecode(engine,[])
    with pytest.raises(InterruptedError):offline.transcribe_pcm(speech_pcm(),cfg,cancel,worker)
    assert received==[cancel] and cancel.is_set()
    assert_offline_locks_released()
    retry_cancel=threading.Event();retry=TinyWorker(engine,[])
    assert offline.transcribe_pcm(speech_pcm(),cfg,retry_cancel,retry)=='Recognized with '+engine
    assert retry.cancel_calls==[retry_cancel]
    assert_offline_locks_released()


@pytest.mark.parametrize('reload_fails',[False,True])
def test_recorded_request_recovers_closed_proxy_after_other_engine_service_check(
        tmp_path,monkeypatch,isolated_worker_cache,reload_fails):
    from murmur import gguf_asr
    recorded_cfg=extended_local_config(tmp_path/'recorded','fun_asr_nano','cpu')
    checked_cfg=extended_local_config(tmp_path/'checked','qwen_asr','gpu')
    calls=[];events=[];workers=[];cancel=threading.Event()
    def load(engine,folder,**options):
        calls.append((engine,folder,options))
        if reload_fails and len(calls)==3:raise RuntimeError('Fixture reload failed')
        worker=TinyWorker(engine+'-'+str(len(calls)),events);workers.append(worker)
        return worker
    monkeypatch.setattr(gguf_asr,'load_model',load)
    original_loader=offline.load_recognizer
    recorded_proxy=original_loader(recorded_cfg,cancel)
    # This exercises the actual service-check/cache interaction that can occur
    # between recording start and its final decode, without opening a mic.
    checked=service_checks.check_service('asr',checked_cfg)
    assert checked['success'] and not recorded_proxy.is_alive
    check_proxy=workers[1]
    recovery=[]
    def load_after_releasing_slot(values,event=None):
        assert offline._DECODE_SLOT.acquire(blocking=False),'Closed-worker recovery called the loader while holding its decode slot'
        offline._DECODE_SLOT.release();recovery.append((values,event))
        return original_loader(values,event)
    monkeypatch.setattr(offline,'load_recognizer',load_after_releasing_slot)
    if reload_fails:
        with pytest.raises(RuntimeError,match='Fixture reload failed'):
            offline.transcribe_pcm(speech_pcm(),recorded_cfg,cancel,recorded_proxy)
        assert offline._cached_recognizer is None
    else:
        assert offline.transcribe_pcm(speech_pcm(),recorded_cfg,cancel,recorded_proxy)=='Recognized with fun_asr_nano-3'
        assert workers[2].cancel_calls==[cancel]
        assert not recorded_proxy.decoded and not check_proxy.decoded
    assert recovery==[(recorded_cfg,cancel)] and not check_proxy.is_alive
    assert [item[0] for item in calls]==['fun_asr_nano','qwen_asr','fun_asr_nano']
    assert calls[2][1]==tmp_path/'recorded' and calls[2][2]['onnx_provider']=='CPU'
    assert_offline_locks_released()


def tiny_archive_record(monkeypatch,folder,engine,acceleration='cpu',*,manifest=True):
    """Keep the real archive/manifest workflow with tiny fixture member sizes."""
    cfg=extended_local_config(folder,engine,acceleration)
    selected=models.model_spec(engine,acceleration)
    members={name:(folder/name).stat().st_size for name in selected['archive']['members']}
    tiny={**selected,'files':{},'archive':{**selected['archive'],'members':members}}
    if engine=='sensevoice':
        monkeypatch.setitem(models.MODELS,engine,{**models.MODELS[engine],'gpu_variant':tiny})
    else:monkeypatch.setitem(models.MODELS,engine,tiny)
    if manifest:
        records={name:[size,hashlib.sha256((folder/name).read_bytes()).hexdigest()] for name,size in members.items()}
        (folder/'murmur-model.json').write_text(json.dumps({
            'engine':engine,'revision':tiny['revision'],'acceleration':acceleration,'files':records}),'utf-8')
    return cfg


@pytest.mark.parametrize('engine,acceleration',[
    ('sensevoice','gpu'),('fun_asr_nano','cpu'),('qwen_asr','gpu'),
])
def test_archive_service_check_validates_recorded_member_hashes_before_loading(
        tmp_path,monkeypatch,engine,acceleration):
    cfg=tiny_archive_record(monkeypatch,tmp_path,engine,acceleration)
    loaded=[];monkeypatch.setattr(offline,'load_recognizer',lambda *args:loaded.append(args))
    result=service_checks.check_service('asr',cfg)
    assert result['success'] and 'match their verified installation record' in result['detail']
    first=offline.model_paths(cfg)[0];data=first.read_bytes()
    first.write_bytes(bytes([data[0]^1])+data[1:])  # Same size, different SHA256.
    result=service_checks.check_service('asr',cfg)
    assert not result['success'] and result['summary']=='Model integrity check failed'
    assert len(loaded)==1


@pytest.mark.parametrize('engine,acceleration',[
    ('sensevoice','gpu'),('fun_asr_nano','cpu'),('qwen_asr','gpu'),
])
def test_imported_archive_model_without_manifest_reports_loader_validation_only(
        tmp_path,monkeypatch,engine,acceleration):
    cfg=tiny_archive_record(monkeypatch,tmp_path,engine,acceleration,manifest=False)
    loaded=[];monkeypatch.setattr(offline,'load_recognizer',lambda *args:loaded.append(args))
    monkeypatch.setattr(models,'installed_file_hashes',lambda *args:pytest.fail('An imported model has no authenticated installation record'))
    monkeypatch.setattr(service_checks.hashlib,'sha256',lambda *args:pytest.fail('Imported speech weights must not use a different download hash'))
    result=service_checks.check_service('asr',cfg)
    assert result['success'] and len(loaded)==1
    assert 'imported local model loaded successfully' in result['detail']
    assert 'not checked against the pinned download' in result['detail']
    assert 'match their verified installation record' not in result['detail']

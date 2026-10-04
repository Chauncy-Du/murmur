import copy
import json
import queue
import threading
import time
import wave
from urllib.parse import parse_qs,urlsplit

import pytest
import sounddevice
import websocket
from murmur import ali_nls,providers
from murmur.storage import DEFAULTS


def config():
    values=copy.deepcopy(DEFAULTS)
    values.update(demo=False,asr_backend='ali_nls',ali_nls_url=ali_nls.DEFAULT_URL)
    return values


class FakeSocket:
    def __init__(self):
        self.events=queue.Queue();self.commands=[];self.pcm=[];self.task=None
        self.closed=threading.Event();self.shuts=0;self.binary_entered=threading.Event()
    def settimeout(self,value):self.timeout=value
    def event(self,name,payload=None,status=20000000,task=None,**extra):
        event={'header':{'name':name,'task_id':task or self.task,'status':status,**extra}}
        if payload is not None:event['payload']=payload
        self.events.put(json.dumps(event))
    def send(self,encoded):
        command=json.loads(encoded);self.commands.append(command)
        self.task=command['header']['task_id']
        if command['header']['name']=='StartTranscription':self.event('TranscriptionStarted')
        else:self.event('TranscriptionCompleted')
    def send_binary(self,pcm):
        self.binary_entered.set();self.pcm.append(pcm)
        self.event('TranscriptionResultChanged',{'index':1,'result':'Partial words'})
        self.event('SentenceEnd',{'index':1,'result':'Final words.','status':0})
    def recv(self):
        if self.closed.is_set():return ''
        try:return self.events.get(timeout=.05)
        except queue.Empty:raise websocket.WebSocketTimeoutException()
    def shutdown(self):self.shuts+=1;self.closed.set();self.events.put('')


class FakeStream:
    def __init__(self,**kwargs):self.options=kwargs;self.callback=kwargs['callback'];self.closed=False
    def start(self):self.callback(bytes(3200),1600,None,None)
    def stop(self):pass
    def abort(self):pass
    def close(self):self.closed=True


@pytest.fixture
def setup(monkeypatch):
    sock=FakeSocket();connect=[];streams=[]
    monkeypatch.setattr(ali_nls,'_CONNECTION_SLOTS',threading.BoundedSemaphore(2))
    monkeypatch.setattr(ali_nls,'credential',lambda name:{'ali_appkey':'test-appkey','ali_token':'test-temporary-token'}[name])
    monkeypatch.setattr(ali_nls,'obtain_token',lambda cancel=None,force=False:'test-temporary-token')
    def connection(url,**kwargs):connect.append((url,kwargs));return sock
    def stream(**kwargs):
        result=FakeStream(**kwargs);streams.append(result);return result
    monkeypatch.setattr(websocket,'create_connection',connection)
    monkeypatch.setattr(sounddevice,'RawInputStream',stream)
    return sock,connect,streams


def recorder(partials=None,values=None):
    return ali_nls.NlsRecorder(values or config(),(partials if partials is not None else []).append,lambda level:None,threading.Event())


def wait_for(predicate,timeout=2):
    end=time.monotonic()+timeout
    while not predicate():
        if time.monotonic()>end:pytest.fail('Background mock event timed out')
        time.sleep(.01)


def test_factory_selects_nls_and_demo_overrides():
    values=config()
    assert isinstance(providers.make_recorder(values,lambda text:None,lambda level:None,threading.Event()),ali_nls.NlsRecorder)
    values['demo']=True
    assert isinstance(providers.make_recorder(values,lambda text:None,lambda level:None,threading.Event()),providers.Recorder)


def test_official_start_audio_stop_protocol_partial_final_and_wav(setup,tmp_path):
    sock,connect,streams=setup;partials=[];values=config();values['save_audio']=True;r=recorder(partials,values)
    r.start();assert r.stop()=='Final words.';assert r.stop()=='Final words.'
    assert r._cleanup_finished.wait(2)
    assert partials==['Partial words','Final words.']
    assert r.duration==.1 and sock.pcm==[bytes(3200)]
    endpoint=urlsplit(connect[0][0]);assert parse_qs(endpoint.query)=={'token':['test-temporary-token']}
    assert endpoint.scheme=='wss' and connect[0][1]==dict(timeout=10,enable_multithread=True)
    start,stop=sock.commands
    assert start['header']['namespace']=='SpeechTranscriber' and start['header']['appkey']=='test-appkey'
    assert start['header']['task_id']==stop['header']['task_id'] and start['header']['message_id']!=stop['header']['message_id']
    assert start['payload']==dict(format='pcm',sample_rate=16000,enable_intermediate_result=True,enable_punctuation_prediction=True,enable_inverse_text_normalization=True)
    assert stop['header']['name']=='StopTranscription' and 'payload' not in stop
    assert streams[0].options['blocksize']==1600 and streams[0].options['channels']==1
    with wave.open(r.save_audio(tmp_path/'audio.wav')) as audio:
        assert (audio.getnframes(),audio.getframerate(),audio.getsampwidth(),audio.getnchannels())==(1600,16000,2,1)
    assert sock.shuts==1


def test_expired_or_disabled_service_error_is_sanitized_before_microphone(setup,monkeypatch):
    sock,_,streams=setup
    def send(encoded):
        sock.task=json.loads(encoded)['header']['task_id']
        sock.event('TaskFailed',status=40000001,status_text='https://secret/?token=test-temporary-token&appkey=test-appkey')
    monkeypatch.setattr(sock,'send',send);r=recorder()
    with pytest.raises(RuntimeError,match='code 40000001') as error:r.start()
    assert r._cleanup_finished.wait(2) and not streams
    assert 'test-temporary-token' not in str(error.value) and 'test-appkey' not in r.error


def test_connection_exception_never_exposes_token(setup,monkeypatch):
    _,_,streams=setup
    def connect(url,**kwargs):raise RuntimeError('SDK '+url)
    monkeypatch.setattr(websocket,'create_connection',connect);r=recorder()
    with pytest.raises(RuntimeError,match='Could not connect') as error:r.start()
    assert 'test-temporary-token' not in str(error.value) and not streams
    assert r._cleanup_finished.wait(2)


def test_missing_credential_does_not_connect_or_record(setup,monkeypatch):
    _,connect,streams=setup;monkeypatch.setattr(ali_nls,'credential',lambda name:'');r=recorder()
    with pytest.raises(RuntimeError,match='project AppKey in Settings'):r.start()
    assert r._cleanup_finished.wait(2) and not connect and not streams


def test_token_refresh_failure_stops_before_connection_and_microphone(setup,monkeypatch):
    _,connect,streams=setup;observed=[];r=recorder()
    def obtain(cancel):
        observed.append(cancel)
        raise ali_nls.AliAuthError('Alibaba token request failed (Forbidden). Check AccessKey permissions and service availability.')
    monkeypatch.setattr(ali_nls,'obtain_token',obtain)
    with pytest.raises(RuntimeError,match='token request failed.*Forbidden'):r.start()
    assert observed==[r.cancel]
    assert r._cleanup_finished.wait(2) and not connect and not streams


@pytest.mark.parametrize('endpoint',['ws://example.com/ws','wss://host/ws?token=secret','wss://user:pass@host/ws','wss://host/ws#fragment'])
def test_reject_insecure_or_credential_bearing_endpoint(endpoint):
    with pytest.raises(RuntimeError,match='secure WebSocket URL'):ali_nls._authenticated_url(endpoint,'token')


def test_cancel_during_connect_is_nonblocking_and_late_connection_is_closed(setup,monkeypatch):
    sock,_,streams=setup;entered=threading.Event();release=threading.Event();errors=[]
    def connect(url,**kwargs):entered.set();assert release.wait(2);return sock
    monkeypatch.setattr(websocket,'create_connection',connect);r=recorder()
    def run():
        try:r.start()
        except InterruptedError:errors.append('cancelled')
    worker=threading.Thread(target=run);worker.start();assert entered.wait(2)
    before=time.monotonic();r.abort();r.abort();assert time.monotonic()-before<.1
    assert not sock.closed.is_set();release.set();worker.join(2)
    assert r._cleanup_finished.wait(2) and errors==['cancelled'] and not streams and sock.shuts==1
    r._event(json.dumps({'header':{'name':'SentenceEnd','status':20000000},'payload':{'index':1,'result':'late'}}))
    assert not r.raw


def test_start_requires_server_ready_before_microphone_and_timeout_cleans(setup,monkeypatch):
    sock,_,streams=setup;monkeypatch.setattr(sock,'send',lambda encoded:None);r=recorder()
    original=r._wait
    def fast_wait(event,seconds,message):return original(event,.05,message)
    monkeypatch.setattr(r,'_wait',fast_wait)
    with pytest.raises(RuntimeError,match='startup timed out'):r.start()
    assert r._cleanup_finished.wait(2) and not streams


def test_partial_preserved_on_failure_and_no_cross_session_or_late_duplicate(setup):
    r=recorder();r._ready.set()
    def event(name,index,text,task=None):
        r._event(json.dumps({'header':{'name':name,'status':20000000,'task_id':task or r.task_id},'payload':{'index':index,'result':text}}))
    event('SentenceEnd',1,'First sentence.');event('SentenceEnd',1,'First sentence.')
    event('TranscriptionResultChanged',1,'late finalized');event('SentenceEnd',2,'foreign',task='another-task')
    assert r.raw=='First sentence.'
    event('TranscriptionResultChanged',2,'unfinished text')
    event('SentenceEnd',1,'First sentence.')  # Duplicate old final does not clear the newer partial.
    r._fail('Connection failed.')
    assert r.raw=='First sentence. unfinished text'
    event('SentenceEnd',2,'late final');assert r.raw=='First sentence. unfinished text'
    r.abort();assert r._cleanup_finished.wait(2)


def test_network_queue_overflow_bounded_and_terminates(setup,monkeypatch):
    sock,_,_=setup;entered=threading.Event();release=threading.Event()
    def blocked_send(pcm):entered.set();release.wait(2)
    monkeypatch.setattr(sock,'send_binary',blocked_send);r=recorder();r.start();assert entered.wait(2)
    for _ in range(51):r._audio(bytes(3200),1600,None,None)
    assert r._queue.qsize()==50 and 'overflowed' in r.error and r.closed
    release.set();assert r._cleanup_finished.wait(2)
    with pytest.raises(RuntimeError,match='overflowed'):r.stop()


def test_send_failure_does_not_expose_socket_exception(setup,monkeypatch):
    sock,_,_=setup
    def send(pcm):raise RuntimeError('token=test-temporary-token')
    monkeypatch.setattr(sock,'send_binary',send);r=recorder()
    try:r.start()
    except RuntimeError:pass
    wait_for(lambda:bool(r.error));assert 'upload failed' in r.error and 'test-temporary-token' not in r.error
    assert r._cleanup_finished.wait(2)


def test_empty_result_rejects_insertion(setup,monkeypatch):
    sock,_,_=setup;monkeypatch.setattr(sock,'send_binary',lambda pcm:None);r=recorder();r.start()
    with pytest.raises(RuntimeError,match='No speech was recognized'):r.stop()
    assert r._cleanup_finished.wait(2)


def test_repeated_start_and_stop_before_start_are_explicit_errors(setup):
    r=recorder()
    with pytest.raises(RuntimeError,match='has not been started'):r.stop()
    r.start()
    with pytest.raises(RuntimeError,match='already been started'):r.start()
    r.abort();assert r._cleanup_finished.wait(2)


def test_malformed_response_and_unexpected_completion_fail_safely(setup):
    r=recorder();r._event('{broken secret token=abc')
    assert 'invalid transcription response' in r.error and 'abc' not in r.error
    r.abort();assert r._cleanup_finished.wait(2)
    second=recorder();second._event(json.dumps({'header':{'name':'TranscriptionCompleted','status':20000000}}))
    assert 'before recording stopped' in second.error
    second.abort();assert second._cleanup_finished.wait(2)


def test_cancelled_wait_for_connection_slot_does_not_connect(setup,monkeypatch):
    _,connect,streams=setup;slot=threading.BoundedSemaphore(1);slot.acquire()
    monkeypatch.setattr(ali_nls,'_CONNECTION_SLOTS',slot);r=recorder();finished=threading.Event()
    def start():
        try:r.start()
        except InterruptedError:finished.set()
    worker=threading.Thread(target=start);worker.start();r.abort();worker.join(2)
    assert finished.is_set() and r._cleanup_finished.wait(2) and not connect and not streams
    assert not slot.acquire(blocking=False);slot.release()


def test_slot_not_released_until_cancelled_connect_fully_exits(setup,monkeypatch):
    sock,_,_=setup;slot=threading.BoundedSemaphore(1);entered=threading.Event();release=threading.Event()
    monkeypatch.setattr(ali_nls,'_CONNECTION_SLOTS',slot)
    def connect(url,**kwargs):entered.set();release.wait(2);return sock
    monkeypatch.setattr(websocket,'create_connection',connect);r=recorder()
    def start():
        try:r.start()
        except InterruptedError:pass
    worker=threading.Thread(target=start);worker.start();assert entered.wait(2);r.abort()
    assert not slot.acquire(blocking=False) and not r._cleanup_finished.is_set()
    release.set();worker.join(2);assert r._cleanup_finished.wait(2)
    assert slot.acquire(blocking=False);slot.release()


def test_microphone_drop_stops_audio_and_preserves_partial(setup):
    r=recorder();r.start();wait_for(lambda:bool(r.raw))
    r._audio(bytes(3200),1600,None,'input overflow')
    assert r._cleanup_finished.wait(2) and 'dropped audio' in r.error and r.raw=='Final words.'


def test_completion_timeout_preserves_original_and_releases_connection(setup,monkeypatch):
    sock,_,_=setup;r=recorder();r.start();wait_for(lambda:bool(r.raw));original=r._wait
    def send(encoded):sock.commands.append(json.loads(encoded))
    monkeypatch.setattr(sock,'send',send)
    monkeypatch.setattr(r,'_wait',lambda event,seconds,message:original(event,.05,message))
    with pytest.raises(RuntimeError,match='completion timed out'):r.stop()
    assert r.raw=='Final words.' and r._cleanup_finished.wait(2)

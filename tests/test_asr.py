import copy
import threading
import queue
from types import SimpleNamespace
from murmur.providers import Recorder
from murmur.storage import DEFAULTS

def test_stream_partial_final_and_audio(monkeypatch):
    import dashscope.audio.asr
    import sounddevice
    import murmur.providers
    captured=[];partials=[]
    class FakeRecognition:
        def __init__(self,**kwargs):self.callback=kwargs['callback'];self._stream_data=queue.Queue();captured.append(kwargs)
        def start(self,**kwargs):captured.append(kwargs)
        def send_audio_frame(self,data):
            partial={'text':'部分文本','begin_time':0,'end_time':None}
            self.callback.on_event(SimpleNamespace(get_sentence=lambda:partial))
            final={'text':'完整转写。','begin_time':0,'end_time':100}
            self.callback.on_event(SimpleNamespace(get_sentence=lambda:final))
        def stop(self):self.callback.on_complete()
    class FakeStream:
        def __init__(self,**kwargs):self.callback=kwargs['callback']
        def start(self):self.callback(bytes(3200),1600,None,None)
        def stop(self):pass
        def close(self):pass
    monkeypatch.setattr(dashscope.audio.asr,'Recognition',FakeRecognition);monkeypatch.setattr(sounddevice,'RawInputStream',FakeStream);monkeypatch.setattr(murmur.providers,'credential',lambda name:'fake-test-key')
    cfg=copy.deepcopy(DEFAULTS);cfg['demo']=False
    recorder=Recorder(cfg,partials.append,lambda level:None,threading.Event());recorder.start();assert recorder.stop()=='完整转写。'
    assert recorder.duration==.1  # Captured PCM frames, excluding connection time.
    assert recorder.stop()=='完整转写。'  # Idempotent stop.
    assert partials==['部分文本','完整转写。'];assert captured[0]['sample_rate']==16000;assert 'raw_input' in captured[1]
    assert captured[0]['api_key']=='fake-test-key' and captured[0]['base_address']==cfg['asr_url']
    assert captured[0]['request_timeout']==10

def test_stream_service_error(monkeypatch):
    import pytest
    import dashscope.audio.asr
    import sounddevice
    import murmur.providers
    class FakeRecognition:
        def __init__(self,**kwargs):self.callback=kwargs['callback'];self._stream_data=queue.Queue()
        def start(self,**kwargs):self.callback.on_error(SimpleNamespace(code='InvalidApiKey'))
        def stop(self):pass
    class FakeStream:
        def __init__(self,**kwargs):pass
        def start(self):pass
        def stop(self):pass
        def close(self):pass
    monkeypatch.setattr(dashscope.audio.asr,'Recognition',FakeRecognition);monkeypatch.setattr(sounddevice,'RawInputStream',FakeStream);monkeypatch.setattr(murmur.providers,'credential',lambda name:'fake-test-key')
    cfg=copy.deepcopy(DEFAULTS);cfg['demo']=False;r=Recorder(cfg,lambda t:None,lambda l:None,threading.Event())
    with pytest.raises(RuntimeError,match='ASR service failed'):r.start()
    r.abort()


def test_abort_during_start_never_opens_microphone_or_accepts_late_text(monkeypatch):
    import time
    import dashscope.audio.asr
    import sounddevice
    import murmur.providers
    entered=threading.Event();release=threading.Event();stopped=threading.Event();instances=[];errors=[]
    class FakeRecognition:
        def __init__(self,**kwargs):self.callback=kwargs['callback'];self._stream_data=queue.Queue();self.stops=0;instances.append(self)
        def start(self,**kwargs):entered.set();assert release.wait(2)
        def stop(self):self.stops+=1;stopped.set()
    monkeypatch.setattr(dashscope.audio.asr,'Recognition',FakeRecognition)
    monkeypatch.setattr(sounddevice,'RawInputStream',lambda **kwargs:(_ for _ in ()).throw(AssertionError('Cancelled startup opened microphone')))
    monkeypatch.setattr(murmur.providers,'credential',lambda name:'fake-test-key')
    cfg=copy.deepcopy(DEFAULTS);cfg['demo']=False;r=Recorder(cfg,lambda t:errors.append(t),lambda l:None,threading.Event())
    def start():
        try:r.start()
        except InterruptedError:pass
    worker=threading.Thread(target=start);worker.start();assert entered.wait(2)
    before=time.monotonic();r.abort();r.abort();assert time.monotonic()-before<.1
    assert not stopped.is_set()  # Recognition.stop must not race start.
    release.set();worker.join(2);assert not worker.is_alive();assert stopped.wait(2);assert instances[0].stops==1
    instances[0].callback.on_event(SimpleNamespace(get_sentence=lambda:dict(text='Late text',end_time=100)))
    assert not errors and not r.raw


def test_audio_save_round_trip(monkeypatch,tmp_path):
    import wave
    import dashscope.audio.asr
    import sounddevice
    import murmur.providers
    class FakeRecognition:
        def __init__(self,**kwargs):self.callback=kwargs['callback'];self._stream_data=queue.Queue()
        def start(self,**kwargs):pass
        def send_audio_frame(self,data):self.callback.on_event(SimpleNamespace(get_sentence=lambda:dict(text='Audio saved.',end_time=100)))
        def stop(self):self.callback.on_complete()
    class FakeStream:
        def __init__(self,**kwargs):self.callback=kwargs['callback']
        def start(self):self.callback(bytes(3200),1600,None,None)
        def stop(self):pass
        def close(self):pass
    monkeypatch.setattr(dashscope.audio.asr,'Recognition',FakeRecognition);monkeypatch.setattr(sounddevice,'RawInputStream',FakeStream);monkeypatch.setattr(murmur.providers,'credential',lambda name:'fake-test-key')
    cfg=copy.deepcopy(DEFAULTS);cfg.update(demo=False,save_audio=True)
    r=Recorder(cfg,lambda t:None,lambda l:None,threading.Event());r.start();r.stop();path=r.save_audio(tmp_path/'audio'/'sample.wav')
    with wave.open(path) as audio:assert (audio.getnframes(),audio.getframerate(),audio.getnchannels(),audio.getsampwidth())==(1600,16000,1,2)


def test_device_error_then_abort_keeps_all_captured_audio_and_pending_text(monkeypatch,tmp_path):
    import wave
    import dashscope.audio.asr
    import sounddevice
    import murmur.providers
    entered=threading.Event();release=threading.Event();callbacks=[]
    class Recognition:
        def __init__(self,**kwargs):self.callback=kwargs['callback'];self._stream_data=queue.Queue()
        def start(self,**kwargs):pass
        def send_audio_frame(self,data):
            self.callback.on_event(SimpleNamespace(get_sentence=lambda:dict(text='Recognized partial',end_time=None)))
            entered.set();release.wait(2)
        def stop(self):pass
    class Stream:
        def __init__(self,**kwargs):callbacks.append(kwargs['callback'])
        def start(self):pass
        def abort(self):pass
        def close(self):pass
    monkeypatch.setattr(dashscope.audio.asr,'Recognition',Recognition);monkeypatch.setattr(sounddevice,'RawInputStream',Stream)
    monkeypatch.setattr(murmur.providers,'credential',lambda name:'test-only')
    cfg=copy.deepcopy(DEFAULTS);cfg.update(demo=False,save_audio=True)
    r=Recorder(cfg,lambda text:None,lambda level:None,threading.Event());r.start()
    callbacks[0](bytes(3200),1600,None,None);assert entered.wait(2)
    for _ in range(9):callbacks[0](bytes(3200),1600,None,None)
    callbacks[0](bytes(3200),1600,None,'input overflow');r.abort()
    with wave.open(r.save_audio(tmp_path/'failure.wav')) as audio:assert audio.getnframes()==16000
    assert r.duration==1.0 and r.raw=='Recognized partial' and 'dropped audio' in r.error
    release.set();r.thread.join(2);assert not r.thread.is_alive()


def test_abort_during_result_parsing_cannot_mutate_frozen_original(monkeypatch):
    import dashscope.audio.asr
    import sounddevice
    import murmur.providers
    entered=threading.Event();release=threading.Event();callbacks=[];partials=[]
    class Recognition:
        def __init__(self,**kwargs):callbacks.append(kwargs['callback']);self._stream_data=queue.Queue()
        def start(self,**kwargs):pass
        def stop(self):pass
    class Stream:
        def __init__(self,**kwargs):pass
        def start(self):pass
        def abort(self):pass
        def close(self):pass
    monkeypatch.setattr(dashscope.audio.asr,'Recognition',Recognition);monkeypatch.setattr(sounddevice,'RawInputStream',Stream)
    monkeypatch.setattr(murmur.providers,'credential',lambda name:'test-only')
    cfg=copy.deepcopy(DEFAULTS);cfg['demo']=False;r=Recorder(cfg,partials.append,lambda level:None,threading.Event());r.start();r.pending='Original partial'
    def sentence():entered.set();release.wait(2);return dict(text='Late final',end_time=100)
    worker=threading.Thread(target=lambda:callbacks[0].on_event(SimpleNamespace(get_sentence=sentence)))
    worker.start();assert entered.wait(2);r.abort();release.set();worker.join(2)
    assert r.raw=='Original partial' and not partials

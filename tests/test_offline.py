import copy
import threading
from types import SimpleNamespace
import pytest
from murmur import offline,providers
from murmur.storage import DEFAULTS


def cfg(tmp_path):
    (tmp_path/'model.int8.onnx').write_bytes(b'test-model')
    (tmp_path/'tokens.txt').write_text('token 0','utf-8')
    values=copy.deepcopy(DEFAULTS)
    values.update(demo=False,asr_backend='offline',offline_model_dir=str(tmp_path),offline_language='auto',offline_threads=2)
    return values


class FakeRecognizer:
    def __init__(self,text='Recognized locally.'):self.text=text;self.streams=[]
    def create_stream(self):
        stream=SimpleNamespace(result=SimpleNamespace(text=''))
        def accept(rate,samples):stream.rate=rate;stream.samples=samples
        stream.accept_waveform=accept;self.streams.append(stream);return stream
    def decode_stream(self,stream):stream.result.text=self.text


def speech():
    import numpy as np
    return (np.full(1600,1000,dtype='<i2')).tobytes()


def test_backend_factory_demo_has_priority(tmp_path):
    values=cfg(tmp_path);assert isinstance(providers.make_recorder(values,lambda t:None,lambda l:None,threading.Event()),offline.OfflineRecorder)
    values['demo']=True;assert isinstance(providers.make_recorder(values,lambda t:None,lambda l:None,threading.Event()),providers.Recorder)


def test_missing_local_files_never_calls_network(tmp_path,monkeypatch):
    import socket
    monkeypatch.setattr(socket,'socket',lambda *args,**kwargs:pytest.fail('Offline ASR accessed the network'))
    values=copy.deepcopy(DEFAULTS);values.update(offline_model_dir=str(tmp_path),offline_language='auto',offline_threads=2)
    with pytest.raises(RuntimeError,match='model.int8.onnx and tokens.txt'):offline.load_recognizer(values)


def test_sensevoice_factory_uses_local_cpu_and_caches_model(tmp_path,monkeypatch):
    import sherpa_onnx
    values=cfg(tmp_path);calls=[];recognizer=FakeRecognizer()
    monkeypatch.setattr(offline,'_cached_key',None);monkeypatch.setattr(offline,'_cached_recognizer',None)
    def create(**kwargs):calls.append(kwargs);return recognizer
    monkeypatch.setattr(sherpa_onnx.OfflineRecognizer,'from_sense_voice',create)
    assert offline.load_recognizer(values) is recognizer
    assert offline.load_recognizer(values) is recognizer
    assert len(calls)==1 and calls[0]['provider']=='cpu' and calls[0]['num_threads']==2
    assert calls[0]['language']=='auto' and calls[0]['use_itn'] is True


def test_transcribe_is_local_and_removes_control_tokens(tmp_path,monkeypatch):
    import socket
    monkeypatch.setattr(socket,'socket',lambda *args,**kwargs:pytest.fail('Offline ASR accessed the network'))
    monkeypatch.setattr(providers,'credential',lambda *args:pytest.fail('Offline ASR accessed credentials'))
    recognizer=FakeRecognizer('<|en|><|NEUTRAL|>Local speech.')
    assert offline.transcribe_pcm(speech(),cfg(tmp_path),recognizer=recognizer)=='Local speech.'
    assert recognizer.streams[0].rate==16000 and len(recognizer.streams[0].samples)==1600


@pytest.mark.parametrize('pcm,expected',[(b'','valid mono PCM'),(b'odd','valid mono PCM'),(bytes(3200),'No speech was detected')])
def test_empty_and_silent_audio_do_not_run_inference(tmp_path,pcm,expected):
    recognizer=FakeRecognizer()
    with pytest.raises(RuntimeError,match=expected):offline.transcribe_pcm(pcm,cfg(tmp_path),recognizer=recognizer)
    assert not recognizer.streams


def test_empty_model_result_is_not_inserted(tmp_path):
    with pytest.raises(RuntimeError,match='No speech was recognized offline'):
        offline.transcribe_pcm(speech(),cfg(tmp_path),recognizer=FakeRecognizer('<|zh|><|Speech|>'))


def test_cancelled_native_decode_cannot_publish_result(tmp_path):
    entered=threading.Event();release=threading.Event();cancel=threading.Event();outcomes=[]
    class Slow(FakeRecognizer):
        def decode_stream(self,stream):entered.set();assert release.wait(2);super().decode_stream(stream)
    values=cfg(tmp_path)
    def work():
        try:outcomes.append(offline.transcribe_pcm(speech(),values,cancel,Slow()))
        except InterruptedError:outcomes.append('Canceled')
    worker=threading.Thread(target=work);worker.start();assert entered.wait(2);cancel.set();release.set();worker.join(2)
    assert not worker.is_alive() and outcomes==['Canceled']


def test_offline_microphone_lifecycle_and_optional_audio(tmp_path,monkeypatch):
    import sounddevice
    import wave
    values=cfg(tmp_path);values['save_audio']=True;partials=[];options=[];recognizer=FakeRecognizer()
    monkeypatch.setattr(offline,'load_recognizer',lambda *args:recognizer)
    class Stream:
        def __init__(self,**kwargs):self.callback=kwargs['callback'];options.append(kwargs)
        def start(self):self.callback(speech(),1600,None,None)
        def stop(self):pass
        def close(self):pass
    monkeypatch.setattr(sounddevice,'RawInputStream',Stream)
    recorder=offline.OfflineRecorder(values,partials.append,lambda l:None,threading.Event());recorder.start()
    assert recorder.stop()=='Recognized locally.' and recorder.stop()=='Recognized locally.'
    assert partials==['Recognized locally.'] and recorder.duration==.1
    assert options[0]['blocksize']==1600 and options[0]['samplerate']==16000
    path=recorder.save_audio(tmp_path/'recording.wav')
    with wave.open(path) as saved:assert saved.getnframes()==1600


def test_cancelled_model_load_closes_early_microphone(tmp_path,monkeypatch):
    import sounddevice
    import sherpa_onnx
    entered=threading.Event();release=threading.Event();errors=[];values=cfg(tmp_path)
    monkeypatch.setattr(offline,'_cached_key',None)
    def create(**kwargs):entered.set();assert release.wait(2);return FakeRecognizer()
    monkeypatch.setattr(sherpa_onnx.OfflineRecognizer,'from_sense_voice',create)
    streams=[]
    class EarlyStream:
        def __init__(self,**kwargs):self.closed=threading.Event();streams.append(self)
        def start(self):pass
        def stop(self):pass
        def close(self):self.closed.set()
    monkeypatch.setattr(sounddevice,'RawInputStream',EarlyStream)
    recorder=offline.OfflineRecorder(values,lambda t:errors.append(t),lambda l:None,threading.Event())
    def work():
        try:recorder.start()
        except InterruptedError:pass
    worker=threading.Thread(target=work);worker.start();assert entered.wait(2);recorder.abort();recorder.abort();release.set();worker.join(2)
    assert not worker.is_alive() and not errors and recorder.stream is None and streams[0].closed.wait(1)


def test_device_error_preserves_opt_in_pcm_still_waiting_for_collector(tmp_path,monkeypatch):
    import queue
    import wave
    import sounddevice
    entered=threading.Event();release=threading.Event();callbacks=[]
    class GateQueue(queue.Queue):
        def get(self,*args,**kwargs):entered.set();release.wait(2);return super().get(*args,**kwargs)
    class Stream:
        def __init__(self,**kwargs):callbacks.append(kwargs['callback'])
        def start(self):pass
        def abort(self):pass
        def close(self):pass
    values=cfg(tmp_path);values['save_audio']=True
    monkeypatch.setattr(offline,'load_recognizer',lambda *args:FakeRecognizer())
    monkeypatch.setattr(offline,'transcribe_pcm',lambda *args:pytest.fail('Device failure must not silently recognize partial audio'))
    monkeypatch.setattr(sounddevice,'RawInputStream',Stream)
    r=offline.OfflineRecorder(values,lambda text:None,lambda level:None,threading.Event());r.frames=GateQueue(maxsize=50)
    r.start();assert entered.wait(2)
    for _ in range(10):callbacks[0](speech(),1600,None,None)
    callbacks[0](speech(),1600,None,'input overflow');r.abort()
    assert not r.audio  # Collector deliberately stalled.
    with wave.open(r.save_audio(tmp_path/'device-failure.wav')) as audio:assert audio.getnframes()==16000
    assert r.duration==1.0 and not r.raw and 'dropped audio' in r.error
    release.set();r.thread.join(2);assert not r.thread.is_alive()


def test_offline_saving_disabled_never_writes_audio(tmp_path,monkeypatch):
    import sounddevice
    callbacks=[]
    class Stream:
        def __init__(self,**kwargs):callbacks.append(kwargs['callback'])
        def start(self):pass
        def abort(self):pass
        def close(self):pass
    values=cfg(tmp_path);values['save_audio']=False
    monkeypatch.setattr(offline,'load_recognizer',lambda *args:FakeRecognizer());monkeypatch.setattr(sounddevice,'RawInputStream',Stream)
    r=offline.OfflineRecorder(values,lambda text:None,lambda level:None,threading.Event());r.start()
    callbacks[0](speech(),1600,None,None);callbacks[0](speech(),1600,None,'input overflow');r.abort()
    assert r.save_audio(tmp_path/'must-not-exist.wav')=='' and not (tmp_path/'must-not-exist.wav').exists() and not r._saved_audio


def test_local_model_load_follows_capture_and_keeps_starting_speech(tmp_path,monkeypatch):
    import sounddevice
    first=speech();order=[];received=[]
    class Stream:
        def __init__(self,**kwargs):self.callback=kwargs['callback']
        def start(self):order.append('mic');self.callback(first,1600,None,None)
        def stop(self):pass
        def close(self):pass
    def load(*args):
        order.append('model');assert order==['mic','model'];return FakeRecognizer()
    def decode(pcm,*args):received.append(pcm);return 'Starting words.'
    monkeypatch.setattr(sounddevice,'RawInputStream',Stream)
    monkeypatch.setattr(offline,'load_recognizer',load)
    monkeypatch.setattr(offline,'transcribe_pcm',decode)
    r=offline.OfflineRecorder(cfg(tmp_path),lambda text:None,lambda level:None,threading.Event())
    r.start();assert r.stop()=='Starting words.'
    assert received==[first] and r.duration==.1


def test_local_slow_prepare_buffer_overflow_never_decodes_truncated_speech(tmp_path,monkeypatch):
    import sounddevice
    streams=[];entered=threading.Event();release=threading.Event();outcomes=[]
    class Stream:
        def __init__(self,**kwargs):self.callback=kwargs['callback'];self.closed=threading.Event();streams.append(self)
        def start(self):pass
        def stop(self):pass
        def close(self):self.closed.set()
    def load(*args):entered.set();assert release.wait(2);return FakeRecognizer()
    monkeypatch.setattr(sounddevice,'RawInputStream',Stream)
    monkeypatch.setattr(offline,'load_recognizer',load)
    monkeypatch.setattr(offline,'transcribe_pcm',lambda *args:pytest.fail('Failed preparation decoded partial audio'))
    r=offline.OfflineRecorder(cfg(tmp_path),lambda text:None,lambda level:None,threading.Event())
    def start():
        try:r.start()
        except RuntimeError as exc:outcomes.append(str(exc))
    worker=threading.Thread(target=start);worker.start();assert entered.wait(1)
    for _ in range(51):streams[0].callback(speech(),1600,None,None)
    assert streams[0].closed.wait(1) and 'overflowed' in r.error
    release.set();worker.join(1)
    assert not worker.is_alive() and len(outcomes)==1 and 'overflowed' in outcomes[0]
    with pytest.raises(RuntimeError,match='overflowed'):r.capture.check()


@pytest.mark.parametrize('language',['auto','zh','en','ja','ko','yue'])
def test_supported_language_validation(tmp_path,language):
    values=cfg(tmp_path);values['offline_language']=language
    assert offline.model_files(values)[2]==language


def test_long_audio_requires_local_vad_without_arbitrary_word_cuts(tmp_path):
    import numpy as np
    samples=np.full(31*16000,1000,dtype='<i2').tobytes()
    recognizer=FakeRecognizer()
    with pytest.raises(RuntimeError,match='Long offline recordings require silero_vad.onnx'):
        offline.transcribe_pcm(samples,cfg(tmp_path),recognizer=recognizer)
    assert not recognizer.streams


def test_failure_in_later_segment_retains_earlier_original_text(tmp_path,monkeypatch):
    import numpy as np
    partials=[]
    class SecondFails(FakeRecognizer):
        def decode_stream(self,stream):
            if len(self.streams)==2:raise RuntimeError('Second segment failed')
            stream.result.text='The first recognized sentence.'
    monkeypatch.setattr(offline,'_speech_segments',lambda *args:iter([np.zeros(1600,dtype=np.float32),np.zeros(1600,dtype=np.float32)]))
    with pytest.raises(RuntimeError,match='Second segment failed'):
        offline.transcribe_pcm(speech(),cfg(tmp_path),recognizer=SecondFails(),on_partial=partials.append)
    assert partials==['The first recognized sentence.']


def test_vad_boundaries_preserve_quiet_phoneme_context(tmp_path,monkeypatch):
    import numpy as np
    import sherpa_onnx
    values=cfg(tmp_path);(tmp_path/'silero_vad.onnx').write_bytes(b'test-vad')
    captured=[]
    class Vad:
        def __init__(self,config,**kwargs):self.items=[];self.emitted=False;captured.append(config)
        def accept_waveform(self,frame):
            if not self.emitted:self.items.append(SimpleNamespace(start=1600,samples=np.zeros(1600)));self.emitted=True
        def empty(self):return not self.items
        @property
        def front(self):return self.items[0]
        def pop(self):self.items.pop(0)
        def flush(self):pass
    monkeypatch.setattr(sherpa_onnx,'VoiceActivityDetector',Vad)
    samples=np.arange(10000,dtype=np.float32)/10000
    segments=list(offline._speech_segments(samples,values,None))
    assert len(segments)==1 and np.array_equal(segments[0],samples[:4800])
    assert captured[0].sample_rate==16000 and captured[0].provider=='cpu'


def test_vad_without_speech_does_not_hallucinate_a_result(tmp_path,monkeypatch):
    recognizer=FakeRecognizer('A hallucinated sentence')
    monkeypatch.setattr(offline,'_speech_segments',lambda *args:iter([]))
    with pytest.raises(RuntimeError,match='No speech was recognized offline'):
        offline.transcribe_pcm(speech(),cfg(tmp_path),recognizer=recognizer)
    assert not recognizer.streams

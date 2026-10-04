"""Exercise the installed official SDK buffer without credentials or a connection."""
import queue
import time
import copy
import threading
import pytest
from murmur import providers


def test_installed_sdk_backpressure_is_bounded():
    from dashscope.audio.asr import Recognition,RecognitionCallback
    sdk=Recognition(model='fun-asr-realtime',format='pcm',sample_rate=16000,callback=RecognitionCallback(),api_key='test-only',base_address='wss://invalid.example')
    buffer=providers._install_asr_buffer(sdk)
    sdk._running=True  # No start(): no WebSocket worker and no network calls.
    for _ in range(50):sdk.send_audio_frame(bytes(3200))
    before=time.monotonic()
    with pytest.raises(queue.Full):sdk.send_audio_frame(bytes(3200))
    assert buffer.qsize()==50 and buffer.maxsize==50
    assert .08<=time.monotonic()-before<.5
    sdk._running=False


def test_unknown_sdk_version_is_rejected(monkeypatch):
    monkeypatch.setattr(providers,'version',lambda name:'99.0.0')
    with pytest.raises(RuntimeError,match='Reinstall locked dependencies'):
        providers._install_asr_buffer(type('SDK',(),{'_stream_data':queue.Queue()})())


def test_unknown_sdk_queue_shape_is_rejected():
    with pytest.raises(RuntimeError,match='incompatible'):
        providers._install_asr_buffer(type('SDK',(),{'_stream_data':[]})())


def test_sdk_network_overflow_stops_recorder(monkeypatch):
    """Use the real SDK enqueue method, but omit every network worker."""
    import sounddevice
    from dashscope.audio.asr import Recognition
    from murmur.storage import DEFAULTS
    callbacks=[]
    def start(sdk,**kwargs):sdk._running=True
    def stop(sdk):sdk._running=False;sdk._callback.on_close()
    class FakeStream:
        def __init__(self,**kwargs):callbacks.append(kwargs['callback'])
        def start(self):pass
        def stop(self):pass
        def close(self):pass
        def abort(self):pass
    monkeypatch.setattr(Recognition,'start',start);monkeypatch.setattr(Recognition,'stop',stop)
    monkeypatch.setattr(sounddevice,'RawInputStream',FakeStream)
    monkeypatch.setattr(providers,'credential',lambda name:'test-only')
    cfg=copy.deepcopy(DEFAULTS);cfg['demo']=False
    recorder=providers.Recorder(cfg,lambda text:None,lambda level:None,threading.Event())
    recorder.start()
    for _ in range(50):recorder.recognition.send_audio_frame(bytes(3200))
    callbacks[0](bytes(3200),1600,None,None)
    with pytest.raises(RuntimeError,match='network queue overflowed'):recorder.stop()
    assert recorder.closed and recorder.sdk_buffer.qsize()==50
    assert recorder.duration==.1
    recorder.abort()


def test_cancelled_bailian_start_waiting_for_connection_slot_opens_nothing(monkeypatch):
    from murmur.storage import DEFAULTS
    import sounddevice
    slot=threading.BoundedSemaphore(1);slot.acquire()
    monkeypatch.setattr(providers,'_ASR_SLOTS',slot)
    monkeypatch.setattr(providers,'credential',lambda name:'test-only')
    monkeypatch.setattr(sounddevice,'RawInputStream',lambda **kwargs:pytest.fail('Cancelled waiting session opened a microphone'))
    cfg=copy.deepcopy(DEFAULTS);cfg['demo']=False
    recorder=providers.Recorder(cfg,lambda text:None,lambda level:None,threading.Event());finished=threading.Event()
    def start():
        try:recorder.start()
        except InterruptedError:finished.set()
    worker=threading.Thread(target=start);worker.start();recorder.abort();worker.join(2)
    assert finished.is_set() and recorder.recognition is None and not recorder._asr_slot_held
    assert not slot.acquire(blocking=False);slot.release()


def test_bailian_slot_held_until_worker_exits_even_if_stop_raises(monkeypatch):
    from murmur.storage import DEFAULTS
    slot=threading.BoundedSemaphore(1);slot.acquire();release=threading.Event();entered=threading.Event()
    monkeypatch.setattr(providers,'_ASR_SLOTS',slot)
    def receive():entered.set();release.wait(2)
    worker=threading.Thread(target=receive);worker.start();assert entered.wait(2)
    class FakeRecognition:
        _worker=worker
        def stop(self):raise RuntimeError('SDK already stopped')
    recorder=providers.Recorder(DEFAULTS,lambda text:None,lambda level:None,threading.Event())
    recorder.recognition=FakeRecognition();recorder._asr_slot_held=True
    with pytest.raises(RuntimeError,match='already stopped'):recorder._stop_recognition()
    assert recorder._asr_slot_held and not slot.acquire(blocking=False)
    release.set();worker.join(2)
    deadline=time.monotonic()+2
    while recorder._asr_slot_held and time.monotonic()<deadline:time.sleep(.01)
    assert not recorder._asr_slot_held and slot.acquire(blocking=False)
    slot.release();recorder._stop_recognition()  # Does not release twice.


def test_bailian_constructor_failure_is_cleaned_up_and_slot_released(monkeypatch):
    import dashscope.audio.asr
    from murmur.storage import DEFAULTS
    slot=threading.BoundedSemaphore(1)
    monkeypatch.setattr(providers,'_ASR_SLOTS',slot)
    monkeypatch.setattr(providers,'credential',lambda name:'test-only')
    def fail(**kwargs):raise RuntimeError('Invalid ASR configuration')
    monkeypatch.setattr(dashscope.audio.asr,'Recognition',fail)
    cfg=copy.deepcopy(DEFAULTS);cfg['demo']=False
    recorder=providers.Recorder(cfg,lambda text:None,lambda level:None,threading.Event())
    with pytest.raises(RuntimeError,match='Invalid ASR configuration'):recorder.start()
    recorder.abort();deadline=time.monotonic()+2
    while recorder._asr_slot_held and time.monotonic()<deadline:time.sleep(.01)
    assert not recorder._asr_slot_held and slot.acquire(blocking=False);slot.release()

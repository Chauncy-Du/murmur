"""Synthetic input only: pre-roll boundaries, ordering, reuse and cleanup."""
import struct,threading,time
import pytest
from murmur.warm_microphone import WarmMicrophone
from murmur.audio_capture import PCMCollector
from murmur import storage

def pcm(value,frames=1600):return struct.pack('<h',value)*frames

class Stream:
    def __init__(self,**kwargs):self.callback=kwargs['callback'];self.stops=0;self.closed=False;self.active=False
    def start(self):self.active=True;self.callback(pcm(0),1600,None,None)
    def stop(self):self.stops+=1;self.active=False
    def close(self):self.closed=True

@pytest.fixture
def warm(monkeypatch):
    import sounddevice
    streams=[]
    def create(**kwargs):
        stream=Stream(**kwargs);streams.append(stream);return stream
    monkeypatch.setattr(sounddevice,'RawInputStream',create)
    owner=WarmMicrophone({'audio_preroll_ms':500});owner.start()
    owner.test_streams=streams
    yield owner
    owner.close()

def collector(warm,cancel=None):
    return PCMCollector({'_warm_microphone':warm},lambda x:None,cancel or threading.Event(),defer_delivery=True)

def test_defaults_and_idle_ring_exact_capacity(warm):
    assert storage.DEFAULTS['audio_warm_enabled'] is True and storage.DEFAULTS['audio_preroll_ms']==500
    for value in range(1,21):warm._audio(pcm(value),1600,None,None)
    assert warm.size==16000 and b''.join(warm.buffer)==b''.join(pcm(v) for v in range(16,21))
    assert warm.subscriber is None

def test_preroll_then_live_delivered_once_without_second_stream(warm):
    for v in range(1,7):warm._audio(pcm(v),1600,None,None)
    c=collector(warm);sent=[];c.start()
    warm._audio(pcm(7),1600,None,None);warm._audio(pcm(8),1600,None,None)
    c.activate(sent.append);result=c.stop()
    expected=b''.join(pcm(v) for v in range(2,9))
    assert result==expected and b''.join(sent)==expected
    assert len(warm.test_streams)==1 and warm.test_streams[0].stops==0
    assert warm.subscriber is None

def test_partial_frame_capacity_and_zero_preroll(warm):
    warm.capacity=2400
    warm._audio(pcm(1),1600,None,None);warm._audio(pcm(2),1600,None,None)
    c=collector(warm);c.start();c.activate();assert c.stop()==pcm(2,1200)
    warm.capacity=0;warm._audio(pcm(3),1600,None,None)
    c=collector(warm);c.start();warm._audio(pcm(4),1600,None,None);c.activate()
    assert c.stop()==pcm(4)

def test_cancel_detaches_immediately_and_never_seeds_old_session(warm):
    c=collector(warm);c.start();warm._audio(pcm(10),1600,None,None);c.abort()
    assert warm.subscriber is None
    warm._audio(pcm(20),1600,None,None)
    second=collector(warm);second.start();second.activate()
    assert second.stop()==pcm(20)

def test_fault_clears_cache_fails_active_session_and_blocks_reuse(warm):
    c=collector(warm);c.start();warm._audio(pcm(1),1600,None,'overflow')
    assert warm.size==0 and c.error and warm.error
    c.abort()
    with pytest.raises(RuntimeError):collector(warm).start()

def test_close_releases_native_stream_and_erases_ring(warm):
    warm.close();assert warm.test_streams[0].closed and warm.size==0
    with pytest.raises(RuntimeError):collector(warm).start()

def test_settings_normalize_invalid_values():
    from murmur.storage import validated_config
    assert validated_config({'audio_preroll_ms':-1})['audio_preroll_ms']==500
    assert validated_config({'audio_warm_enabled':'yes'})['audio_warm_enabled'] is True

def test_handoff_during_concurrent_callbacks_has_no_gap_or_duplicate(warm):
    for v in range(1,10):warm._audio(pcm(v),1600,None,None)
    def produce():
        for v in range(10,30):warm._audio(pcm(v),1600,None,None);time.sleep(.002)
    producer=threading.Thread(target=produce);producer.start();time.sleep(.006)
    c=collector(warm);c.start();c.activate();producer.join();result=c.stop()
    values=[struct.unpack('<h',result[i:i+2])[0] for i in range(0,len(result),3200)]
    assert values==list(range(values[0],30))

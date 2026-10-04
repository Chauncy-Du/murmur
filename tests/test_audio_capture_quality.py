"""Synthetic PCM/PortAudio fixtures only; no microphone, model or network."""
import struct
import threading
import time

import pytest

from murmur.audio_capture import PCMCollector
from murmur.audio_quality import prepare_pcm, require_speech


def pcm(value, samples=1600):
    return struct.pack('<h', value) * samples


class Stream:
    def __init__(self, **options):
        self.options = options
        self.callback = options['callback']
        self.started = False
        self.closed = threading.Event()
        self.stops = 0

    def start(self):
        self.started = True

    def stop(self):
        self.stops += 1

    def close(self):
        self.closed.set()


@pytest.fixture
def streams(monkeypatch):
    import sounddevice
    values = []
    def create(**kwargs):
        item = Stream(**kwargs)
        values.append(item)
        return item
    monkeypatch.setattr(sounddevice, 'RawInputStream', create)
    return values


def test_preparation_frames_are_delivered_once_in_capture_order(streams):
    sent = []
    capture = PCMCollector({}, lambda level: None, threading.Event(), defer_delivery=True)
    capture.start()
    assert streams[0].options['blocksize'] == 1600
    chunks = [pcm(value) for value in (1000, 2000, 3000)]
    for chunk in chunks:
        streams[0].callback(chunk, 1600, None, None)
    assert sent == [] and capture.frames.qsize() == 3
    capture.activate(sent.append)
    assert capture.stop() == b''.join(chunks)
    assert sent == chunks and capture.duration == .3
    assert capture.stop() == b''.join(chunks) and streams[0].stops == 1


def test_preparation_buffer_has_five_second_limit_and_preserves_opt_in_pcm(streams):
    errors = []
    capture = PCMCollector({'save_audio': True}, lambda level: None,
                           threading.Event(), defer_delivery=True, on_error=errors.append)
    capture.start()
    for _ in range(51):
        streams[0].callback(pcm(1000), 1600, None, None)
    assert capture.frames.qsize() == 50
    assert 'overflowed' in capture.error and errors == [capture.error]
    assert streams[0].closed.wait(1)
    with pytest.raises(RuntimeError, match='overflowed'):
        capture.activate(lambda chunk: pytest.fail('Failed preparation sent audio'))
    assert capture.duration == 5.1 and len(capture.pcm) == 51 * 3200
    capture.abort()
    assert capture.frames.empty() and len(capture.pcm) == 51 * 3200


def test_batch_capture_can_exceed_preparation_window_without_unbounded_queue(streams):
    capture = PCMCollector({}, lambda level: None, threading.Event())
    capture.start()
    for _ in range(80):
        streams[0].callback(pcm(1000), 1600, None, None)
        # Deterministic pacing below the consumer speed, not wall-clock audio.
        deadline = time.monotonic() + 1
        while not capture.frames.empty() and time.monotonic() < deadline:
            time.sleep(.001)
    assert len(capture.stop()) == 80 * 3200 and capture.duration == 8


def test_cancel_clears_unsaved_buffer_and_does_not_deliver_late_frames(streams):
    cancel = threading.Event()
    sent = []
    capture = PCMCollector({}, lambda level: None, cancel, defer_delivery=True)
    capture.start()
    streams[0].callback(pcm(1000), 1600, None, None)
    cancel.set()
    capture.abort(); capture.abort()
    streams[0].callback(pcm(2000), 1600, None, None)
    assert capture.pcm == b'' and capture.frames.empty() and capture.duration == .1
    assert streams[0].closed.wait(1)
    with pytest.raises(InterruptedError):
        capture.activate(sent.append)
    assert sent == []


def test_stop_during_microphone_start_does_not_close_unpublished_stream(monkeypatch):
    import sounddevice
    entered = threading.Event(); release = threading.Event()
    class SlowStream(Stream):
        def start(self):
            entered.set()
            assert release.wait(1)
            assert not self.closed.is_set()
    stream = SlowStream(callback=lambda *args: None)
    monkeypatch.setattr(sounddevice, 'RawInputStream', lambda **kwargs: stream)
    capture = PCMCollector({}, lambda level: None, threading.Event())
    worker = threading.Thread(target=capture.start)
    worker.start(); assert entered.wait(1)
    capture.close_input()
    assert not stream.closed.is_set()
    release.set(); worker.join(1)
    assert stream.closed.wait(1) and not worker.is_alive()
    assert capture.stop() == b''


def test_request_stop_before_start_does_not_open_a_late_microphone(streams):
    capture=PCMCollector({},lambda level:None,threading.Event(),defer_delivery=True)
    capture.request_stop()
    with pytest.raises(RuntimeError,match='stopped before the microphone'):
        capture.start()
    assert streams==[] and capture.pcm==b''


@pytest.mark.parametrize('backend', ['bailian', 'ali_nls', 'offline'])
def test_recorder_stop_request_before_start_prevents_resource_publication(backend,streams,monkeypatch):
    import copy
    from murmur import providers, ali_nls, offline
    from murmur.storage import DEFAULTS
    cfg=copy.deepcopy(DEFAULTS);cfg.update(demo=False,asr_backend=backend)
    monkeypatch.setattr(providers,'credential',lambda name:'synthetic-key')
    monkeypatch.setattr(ali_nls,'credential',lambda name:'synthetic-appkey')
    monkeypatch.setattr(ali_nls,'obtain_token',lambda *args:pytest.fail('Stopped recorder refreshed a token'))
    monkeypatch.setattr(offline,'load_recognizer',lambda *args:pytest.fail('Stopped recorder loaded a model'))
    recorder=providers.make_recorder(cfg,lambda text:None,lambda level:None,threading.Event())
    recorder.request_stop()
    with pytest.raises(RuntimeError,match='stopped before the microphone'):
        recorder.start()
    assert streams==[] and recorder.duration==0
    recorder.abort()


def test_request_stop_during_stream_construction_prevents_late_start(monkeypatch):
    import sounddevice
    entered=threading.Event();release=threading.Event();outcomes=[]
    stream=Stream(callback=lambda *args:None)
    def create(**kwargs):entered.set();assert release.wait(1);return stream
    monkeypatch.setattr(sounddevice,'RawInputStream',create)
    capture=PCMCollector({},lambda level:None,threading.Event(),defer_delivery=True)
    def start():
        try:capture.start()
        except RuntimeError as exc:outcomes.append(str(exc))
    worker=threading.Thread(target=start);worker.start();assert entered.wait(1)
    capture.request_stop();release.set();worker.join(1)
    assert not worker.is_alive() and not stream.started and stream.closed.wait(1)
    assert len(outcomes)==1 and 'stopped before the microphone' in outcomes[0]


def test_cancel_during_stream_construction_reports_cancel_not_empty_failure(monkeypatch):
    import sounddevice
    entered=threading.Event();release=threading.Event();outcomes=[];cancel=threading.Event()
    stream=Stream(callback=lambda *args:None)
    def create(**kwargs):entered.set();assert release.wait(1);return stream
    monkeypatch.setattr(sounddevice,'RawInputStream',create)
    capture=PCMCollector({},lambda level:None,cancel,defer_delivery=True)
    def start():
        try:capture.start()
        except InterruptedError:outcomes.append('cancelled')
    worker=threading.Thread(target=start);worker.start();assert entered.wait(1)
    cancel.set();capture.abort();release.set();worker.join(1)
    assert not worker.is_alive() and not stream.started and stream.closed.wait(1)
    assert outcomes==['cancelled'] and not capture.error


def test_request_stop_seals_synchronously_without_waiting_for_device_stop(monkeypatch):
    import sounddevice
    entered=threading.Event();release=threading.Event();sent=[]
    class SlowClose(Stream):
        def stop(self):entered.set();assert release.wait(1)
    stream=SlowClose(callback=lambda *args:None)
    monkeypatch.setattr(sounddevice,'RawInputStream',lambda **kwargs:stream)
    capture=PCMCollector({},lambda level:None,threading.Event(),defer_delivery=True)
    capture.start();capture._audio(pcm(1000),1600,None,None)
    started=time.monotonic();capture.request_stop()
    assert time.monotonic()-started<.1 and entered.wait(1)
    capture._audio(pcm(2000),1600,None,None)
    assert capture.duration==.1
    release.set();assert stream.closed.wait(1)
    capture.activate(sent.append)
    assert capture.stop()==pcm(1000) and sent==[pcm(1000)]


def test_device_error_stops_capture_and_keeps_original_pcm_when_enabled(streams):
    capture = PCMCollector({'save_audio': True}, lambda level: None, threading.Event())
    capture.start()
    streams[0].callback(pcm(1000), 1600, None, None)
    streams[0].callback(pcm(2000), 1600, None, 'input overflow')
    assert streams[0].closed.wait(1)
    with pytest.raises(RuntimeError, match='dropped audio'):
        capture.stop()
    assert capture.pcm == pcm(1000) and capture.duration == .1


def test_capture_total_duration_limit_stops_without_accepting_extra_audio(streams):
    capture = PCMCollector({'save_audio': True}, lambda level: None, threading.Event())
    capture.start(); capture.recorded_frames = 600 * 16000
    streams[0].callback(pcm(1000), 1600, None, None)
    assert capture.duration == 600 and capture.pcm == b'' and '10-minute' in capture.error
    assert streams[0].closed.wait(1)


@pytest.mark.parametrize('value', [0, 1, -1, 20, -20])
def test_silence_and_low_noise_are_rejected_before_inference(value):
    assert prepare_pcm(pcm(value)).silent
    with pytest.raises(RuntimeError, match='No speech-level audio'):
        require_speech(pcm(value))


@pytest.mark.parametrize('value', [100, -100, 1000, -32768, 32767])
def test_steady_energy_and_full_range_are_not_falsely_silent(value):
    result = require_speech(pcm(value))
    assert result.pcm == pcm(value) and result.duration == .1


def test_trim_keeps_exact_samples_with_conservative_lead_and_tail():
    original = pcm(0, 16000) + pcm(1000, 16000) + pcm(0, 16000)
    result = require_speech(original)
    assert result.metadata['trimmed_lead_ms'] == 750
    assert result.metadata['trimmed_tail_ms'] == 820
    assert result.pcm == pcm(0, 4000) + pcm(1000, 16000) + pcm(0, 2880)
    assert original == pcm(0, 16000) + pcm(1000, 16000) + pcm(0, 16000)
    assert not result.metadata['noise_gate']


def test_gate_is_opt_in_and_only_changes_low_energy_frames():
    original = pcm(10, 6400) + pcm(1000, 6400) + pcm(-10, 6400)
    off = require_speech(original)
    on = require_speech(original, {'audio_noise_gate': True})
    assert pcm(1000, 6400) in on.pcm
    assert len(off.pcm) == len(on.pcm) and off.pcm != on.pcm
    assert on.metadata['noise_gate'] and not off.metadata['noise_gate']


def test_disabled_processing_retains_original_audio_but_silence_screen_still_runs():
    original = pcm(0, 16000) + pcm(1000, 1600) + pcm(0, 16000)
    result = require_speech(original, {'audio_quality_enabled': False, 'audio_noise_gate': True})
    assert result.pcm == original and not result.metadata['processed']
    assert not result.metadata['noise_gate']
    assert prepare_pcm(pcm(0), {'audio_quality_enabled': False}).silent


def test_short_audio_does_not_get_synthetic_leading_or_trailing_samples():
    original = pcm(1000, 320)
    assert require_speech(original).pcm == original


def test_invalid_pcm_and_invalid_configuration_are_handled_deterministically():
    with pytest.raises(ValueError, match='complete 16-bit'):
        prepare_pcm(b'odd')
    result = require_speech(pcm(1000), {'audio_silence_threshold': float('nan'),
                                     'audio_lead_padding_ms': 'invalid'})
    assert result.metadata['silence_threshold'] == .001

"""Deterministic lifecycle barriers, with public fixtures and no real devices."""
import copy
import threading

import pytest

from murmur.audio_capture import PCMCollector
from murmur import ali_nls, cloud_asr
from murmur import audio_capture
from murmur.storage import DEFAULTS


SPEECH = b'\xe8\x03' * 1600


class SyntheticStream:
    def __init__(self, **kwargs):
        self.callback = kwargs['callback']
        self.closed = threading.Event()

    def start(self):
        self.callback(SPEECH, 1600, None, None)

    def stop(self):
        pass

    def close(self):
        self.closed.set()


def test_stop_waits_for_pending_native_close_and_reports_its_error(monkeypatch):
    import sounddevice
    entered = threading.Event(); release = threading.Event(); finished = threading.Event()
    outcomes = []

    class SlowClose(SyntheticStream):
        def stop(self):
            entered.set()
            assert release.wait(2)

        def close(self):
            super().close()
            raise OSError('synthetic-private-device-path')

    stream = SlowClose(callback=lambda *args: None)
    monkeypatch.setattr(sounddevice, 'RawInputStream', lambda **kwargs: _with_callback(stream, kwargs))
    capture = PCMCollector({'save_audio': True}, lambda level: None, threading.Event())
    capture.start(); capture.request_stop()
    assert entered.wait(1)

    def stop():
        try:
            outcomes.append(('success', capture.stop()))
        except RuntimeError as exc:
            outcomes.append(('failed', str(exc)))
        finally:
            finished.set()

    worker = threading.Thread(target=stop)
    worker.start()
    try:
        assert not finished.wait(.1), 'PCM was delivered before device cleanup finished'
    finally:
        release.set(); worker.join(1)
    assert not worker.is_alive() and stream.closed.is_set()
    assert outcomes == [('failed', 'Could not close the microphone. Try selecting the input device again.')]
    assert capture.pcm == SPEECH and capture.duration == .1
    with pytest.raises(RuntimeError, match='Could not close the microphone'):
        capture.stop()


def _with_callback(stream, kwargs):
    stream.callback = kwargs['callback']
    return stream


def test_native_close_timeout_is_bounded_and_never_returns_pcm(monkeypatch):
    import sounddevice
    entered = threading.Event(); release = threading.Event()

    class BlockedClose(SyntheticStream):
        def stop(self):
            entered.set()
            assert release.wait(2)

    stream = BlockedClose(callback=lambda *args: None)
    monkeypatch.setattr(sounddevice, 'RawInputStream', lambda **kwargs: _with_callback(stream, kwargs))
    monkeypatch.setattr(audio_capture, 'INPUT_CLOSE_TIMEOUT', .04)
    capture = PCMCollector({'save_audio': True}, lambda level: None, threading.Event())
    capture.start(); capture.request_stop()
    assert entered.wait(1)
    try:
        with pytest.raises(RuntimeError, match='Microphone cleanup timed out'):
            capture.stop()
        assert capture.pcm == SPEECH and not stream.closed.is_set()
    finally:
        release.set()
    assert stream.closed.wait(1) and capture._input_closed.wait(1)
    # A late successful disposal cannot turn the failed session into success.
    with pytest.raises(RuntimeError, match='Microphone cleanup timed out'):
        capture.stop()


@pytest.mark.parametrize('save_audio', [False, True])
def test_cancel_interrupts_device_close_wait_without_waiting_for_driver(monkeypatch, save_audio):
    import sounddevice
    entered = threading.Event(); release = threading.Event(); finished = threading.Event()
    outcomes = []

    class BlockedClose(SyntheticStream):
        def stop(self):
            entered.set()
            assert release.wait(2)

    stream = BlockedClose(callback=lambda *args: None)
    monkeypatch.setattr(sounddevice, 'RawInputStream', lambda **kwargs: _with_callback(stream, kwargs))
    capture = PCMCollector({'save_audio': save_audio}, lambda level: None, threading.Event())
    capture.start(); capture.request_stop()
    assert entered.wait(1)

    def stop():
        try:
            capture.stop()
            outcomes.append('unexpected-success')
        except InterruptedError:
            outcomes.append('cancelled')
        finally:
            finished.set()

    worker = threading.Thread(target=stop); worker.start()
    try:
        capture.abort()
        assert finished.wait(.3), 'Cancellation waited for the native driver'
        assert not stream.closed.is_set() and outcomes == ['cancelled']
        assert capture.pcm == (SPEECH if save_audio else b'')
    finally:
        release.set(); worker.join(1)
    assert not worker.is_alive() and stream.closed.wait(1)


def nls():
    return ali_nls.NlsRecorder(copy.deepcopy(DEFAULTS), lambda text: None,
                              lambda level: None, threading.Event())


def test_cancel_preserves_latest_unfinalized_nls_sentence():
    recorder = nls()
    recorder.raw = 'First completed sentence.'
    recorder._pending = 'Most recent partial sentence'
    recorder.abort(); recorder.abort()
    assert recorder._cleanup_finished.wait(1)
    assert recorder.raw == 'First completed sentence. Most recent partial sentence'
    assert recorder._pending == ''


def test_nls_parse_already_in_flight_cannot_overwrite_cancelled_raw(monkeypatch):
    recorder = nls(); partials = []
    recorder.partial = partials.append
    recorder._ready.set()
    recorder._sentences[1] = recorder.raw = 'Known final.'
    recorder._pending = 'Known current partial'; recorder._pending_index = 2
    entered = threading.Event(); release = threading.Event()
    original = ali_nls.json.loads

    def parse(encoded, *args, **kwargs):
        if encoded != 'synthetic-final-event':
            return original(encoded, *args, **kwargs)
        entered.set(); assert release.wait(2)
        return {'header': {'name': 'SentenceEnd', 'status': 20000000,
                           'task_id': recorder.task_id},
                'payload': {'index': 2, 'result': 'Late replacement'}}

    monkeypatch.setattr(ali_nls.json, 'loads', parse)
    worker = threading.Thread(target=lambda: recorder._event('synthetic-final-event'))
    worker.start(); assert entered.wait(1)
    recorder.abort()
    release.set(); worker.join(1)
    assert not worker.is_alive() and recorder._cleanup_finished.wait(1)
    assert recorder.raw == 'Known final. Known current partial'
    assert partials == []


def test_http_abort_keeps_completed_raw_for_controller_recovery(monkeypatch):
    import sounddevice
    cfg = copy.deepcopy(DEFAULTS)
    cfg.update(demo=False, asr_backend='openai', asr_http_url='https://fixture.invalid/v1',
               asr_http_model='synthetic-model', asr_http_language='auto', asr_http_timeout=60)
    monkeypatch.setattr(sounddevice, 'RawInputStream', SyntheticStream)
    monkeypatch.setattr(cloud_asr, 'read_key', lambda *args: 'synthetic-key')
    monkeypatch.setattr(cloud_asr, 'transcribe_wav', lambda *args: 'Complete recognized original.')
    recorder = cloud_asr.HttpAsrRecorder(cfg, lambda text: None,
                                      lambda level: None, threading.Event())
    recorder.start(); assert recorder.stop() == 'Complete recognized original.'
    # Controller may cancel before its queued recognized event has been read.
    recorder.abort(); recorder.abort()
    assert recorder.raw == 'Complete recognized original.'
    with pytest.raises(InterruptedError):
        recorder.stop()


def test_batch_close_failure_cannot_send_audio_or_return_a_result(monkeypatch, tmp_path):
    import sounddevice
    import wave
    cfg = copy.deepcopy(DEFAULTS)
    cfg.update(demo=False, asr_backend='openai', asr_http_url='https://fixture.invalid/v1',
               asr_http_model='synthetic-model', save_audio=True)

    class FailedClose(SyntheticStream):
        def close(self):
            super().close()
            raise OSError('synthetic-private-device-path')

    monkeypatch.setattr(sounddevice, 'RawInputStream', FailedClose)
    monkeypatch.setattr(cloud_asr, 'read_key', lambda *args: 'synthetic-key')
    monkeypatch.setattr(cloud_asr, 'transcribe_wav', lambda *args: pytest.fail('Invalid capture was uploaded'))
    recorder = cloud_asr.HttpAsrRecorder(cfg, lambda text: None,
                                      lambda level: None, threading.Event())
    recorder.start()
    with pytest.raises(RuntimeError, match='Could not close the microphone'):
        recorder.stop()
    assert recorder.raw == '' and recorder._key == ''
    with wave.open(recorder.save_audio(tmp_path / 'synthetic-original.wav'), 'rb') as audio:
        assert audio.readframes(audio.getnframes()) == SPEECH

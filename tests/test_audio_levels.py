"""Real sample energy, not peaks or history, drives the capsule level."""
import copy
import math
import queue
import struct
import threading
from types import SimpleNamespace

import pytest
from murmur.audio_levels import pcm_level
from murmur.storage import DEFAULTS


def pcm(samples):
    return struct.pack('<' + 'h' * len(samples), *samples)


@pytest.mark.parametrize('samples', [[], [0] * 1600, [1, -1] * 800, [58, -58] * 800])
def test_silence_and_fixed_noise_floor(samples):
    assert pcm_level(pcm(samples)) == 0.0


def test_known_rms_uses_fixed_dbfs_scale():
    expected = (20 * math.log10(1000 / 32768) + 55) / 46
    assert pcm_level(pcm([1000] * 1600)) == pytest.approx(expected)
    # No normalization against previous frames, and no per-backend gain.
    pcm_level(pcm([32767] * 1600))
    assert pcm_level(pcm([1000] * 1600)) == pytest.approx(expected)


def test_amplitude_monotonic_and_full_scale():
    levels = [pcm_level(pcm([value, -value] * 800))
              for value in (59, 100, 300, 1000, 3000, 10000)]
    assert all(first < second for first, second in zip(levels, levels[1:]))
    assert pcm_level(pcm([32767] * 1600)) == 1.0
    assert pcm_level(pcm([-32768] * 1600)) == 1.0


def test_sign_and_frequency_do_not_change_equal_rms():
    positive = pcm_level(pcm([1000] * 1600))
    assert pcm_level(pcm([-1000] * 1600)) == positive
    assert pcm_level(pcm([1000, -1000] * 800)) == positive
    assert pcm_level(pcm(([1000] * 40 + [-1000] * 40) * 20)) == positive


def test_single_peak_does_not_report_full_volume():
    sparse = pcm_level(pcm([32767] + [0] * 1599))
    assert 0.0 < sparse < 0.6
    assert sparse < pcm_level(pcm([2000] * 1600))
    assert sparse < pcm_level(pcm([32767] * 1600))


def test_invalid_sample_boundary():
    with pytest.raises(ValueError, match='16-bit mono PCM'):
        pcm_level(b'odd')


@pytest.mark.parametrize('backend', ['bailian', 'offline', 'ali_nls'])
def test_real_backend_capture_callbacks_share_same_meter(backend, monkeypatch):
    """Invoke actual callbacks with synthetic PCM; no mic/network/model load."""
    import sounddevice
    import dashscope.audio.asr
    from murmur import providers, offline, ali_nls
    levels = []
    streams = []

    class Stream:
        def __init__(self, **kwargs):
            self.options = kwargs
            self.callback = kwargs['callback']
            streams.append(self)
        def start(self):pass
        def stop(self):pass
        def abort(self):pass
        def close(self):pass

    class Recognition:
        def __init__(self, **kwargs):
            self.callback = kwargs['callback']
            self._stream_data = queue.Queue()
        def start(self, **kwargs):pass
        def send_audio_frame(self, data):pass
        def stop(self):self.callback.on_complete()

    monkeypatch.setattr(sounddevice, 'RawInputStream', Stream)
    monkeypatch.setattr(dashscope.audio.asr, 'Recognition', Recognition)
    monkeypatch.setattr(providers, 'credential', lambda name:'fixture-key')
    monkeypatch.setattr(offline, 'load_recognizer', lambda *args:SimpleNamespace())
    cfg = copy.deepcopy(DEFAULTS)
    cfg.update(demo=False, asr_backend=backend, save_audio=False)
    rec = providers.make_recorder(cfg, lambda text:None, levels.append, threading.Event())
    if backend == 'ali_nls':
        # NLS exposes its same mic callback directly; startup needs no mock token.
        callback = rec._audio
    else:
        rec.start()
        callback = streams[0].callback
        assert streams[0].options['blocksize'] == 1600
    try:
        frames = [pcm([0] * 1600), pcm([1, -1] * 800),
                  pcm([1000, -1000] * 800), pcm([-32768] * 1600)]
        for chunk in frames:
            callback(chunk, 1600, None, None)
        assert levels == [pcm_level(chunk) for chunk in frames]
        assert len(levels) == 4
        assert rec.recorded_frames == 6400
        saved = rec._saved_audio if backend == 'offline' else rec.audio
        assert saved == []  # Metering never opts in to saved audio.
    finally:
        rec.abort()

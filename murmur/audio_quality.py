"""Conservative, deterministic PCM quality analysis; no speech/model/network.

RMS is not semantic VAD. Trimming retains generous lead/tail margins and noise
gating is opt-in. It cannot recover samples captured before microphone startup.
Streaming callers may use the silent result at stop, but must not claim that
already-uploaded audio was retroactively trimmed or denoised.
"""
from dataclasses import dataclass
import math

SAMPLE_RATE = 16000
FRAME_SAMPLES = 320


@dataclass(frozen=True)
class AudioQualityResult:
    pcm: bytes
    silent: bool
    duration: float
    metadata: dict


def _number(cfg, key, default, lower, upper):
    try:
        value = float(cfg.get(key, default))
        if not math.isfinite(value):
            raise ValueError()
        return min(upper, max(lower, value))
    except (ValueError, TypeError):
        return default


def prepare_pcm(pcm, cfg=None):
    """Analyze mono PCM16LE; return original bytes when processing is disabled."""
    import numpy as np
    cfg = cfg or {}
    pcm = bytes(pcm)
    if len(pcm) % 2:
        raise ValueError('Audio must contain complete 16-bit mono PCM samples.')
    samples = np.frombuffer(pcm, dtype='<i2').astype(np.float64) / 32768.
    threshold = _number(cfg, 'audio_silence_threshold', .001, .0001, .02)
    levels = [float(np.sqrt(np.mean(samples[i:i+FRAME_SAMPLES] ** 2)))
              for i in range(0, len(samples), FRAME_SAMPLES)]
    max_rms = max(levels, default=0.)
    # Deliberately no p20 * multiplier: steady speech must not be called silent.
    active = [index for index, level in enumerate(levels) if level >= threshold]
    silent = not active
    enabled = bool(cfg.get('audio_quality_enabled', True))
    metadata = {'processed': enabled, 'silent': silent, 'max_rms': max_rms,
                'silence_threshold': threshold, 'original_seconds': len(samples)/SAMPLE_RATE,
                'trimmed_lead_ms': 0., 'trimmed_tail_ms': 0., 'noise_gate': False}
    if silent or not enabled:
        return AudioQualityResult(pcm, silent, len(samples)/SAMPLE_RATE, metadata)
    lead = round(_number(cfg, 'audio_lead_padding_ms', 250, 0, 2000)*SAMPLE_RATE/1000)
    tail = round(_number(cfg, 'audio_tail_padding_ms', 180, 0, 1000)*SAMPLE_RATE/1000)
    first = max(0, active[0]*FRAME_SAMPLES-lead)
    last = min(len(samples), (active[-1]+1)*FRAME_SAMPLES+tail)
    minimum = min(len(samples), round(.35*SAMPLE_RATE))
    if last-first < minimum:
        extra = minimum-(last-first)
        first = max(0, first-extra//2)
        last = min(len(samples), first+minimum)
        first = max(0, last-minimum)
    # Byte slices preserve every sample exactly when gate is off.
    output = pcm[first*2:last*2]
    if cfg.get('audio_noise_gate', False):
        data = np.frombuffer(output, dtype='<i2').copy()
        gate = threshold*.5
        for i in range(0, len(data), FRAME_SAMPLES):
            values = data[i:i+FRAME_SAMPLES].astype(np.float64)/32768.
            if float(np.sqrt(np.mean(values**2))) < gate:
                data[i:i+FRAME_SAMPLES] = 0
        output = data.tobytes()
        metadata['noise_gate'] = True
    metadata.update(trimmed_lead_ms=first/SAMPLE_RATE*1000,
                    trimmed_tail_ms=(len(samples)-last)/SAMPLE_RATE*1000)
    return AudioQualityResult(output, False, len(output)/2/SAMPLE_RATE, metadata)


def require_speech(pcm, cfg=None):
    result = prepare_pcm(pcm, cfg)
    if result.silent:
        raise RuntimeError('No speech-level audio was detected. Nothing was inserted. Check the microphone or speak closer to it.')
    return result

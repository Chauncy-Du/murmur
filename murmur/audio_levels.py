"""Fixed RMS metering for mono, little-endian signed 16-bit PCM.

The display level is not a gain control or a speech detector. Every 100 ms
capture frame uses the same scale, independent of backend or earlier audio.
No audio is saved or transmitted here.
"""
import array
import math
import sys

NOISE_FLOOR_DBFS = -55.0
DISPLAY_FULL_DBFS = -9.0


def pcm_level(pcm: bytes) -> float:
    """Map RMS dBFS linearly from [-55, -9] dBFS to [0, 1].

    RMS = sqrt(mean(sample**2)) / 32768; dBFS = 20*log10(RMS).
    Zero samples and levels at/below the fixed noise floor return zero.
    Python integer squares avoid overflow for the -32768 sample value.
    """
    if not pcm:
        return 0.0
    if len(pcm) % 2:
        raise ValueError('Audio metering requires signed 16-bit mono PCM.')
    samples = array.array('h')
    samples.frombytes(pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    mean_square = math.fsum(sample * sample for sample in samples) / len(samples)
    if not mean_square:
        return 0.0
    dbfs = 10.0 * math.log10(mean_square / (32768.0 ** 2))
    return min(1.0, max(0.0, (dbfs - NOISE_FLOOR_DBFS) /
                        (DISPLAY_FULL_DBFS - NOISE_FLOOR_DBFS)))

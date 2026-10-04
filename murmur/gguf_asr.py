"""Isolated local ONNX/GGUF recognizers with a sherpa-compatible interface.

ONNX Runtime DirectML and sherpa ship different Windows DLLs with the same
name. Always load CapsWriter's native engines in a spawned worker process.
Only PCM samples and plain result messages cross the private local pipe.
There are no network requests, downloads, or cloud fallbacks in this module.
"""
import atexit
from dataclasses import dataclass, field
import multiprocessing
import os
from pathlib import Path
import threading
import time
import weakref

SAMPLE_RATE = 16000
MAX_SEGMENT_SECONDS = 30
LOAD_TIMEOUT = 180
DECODE_TIMEOUT = 180

ENGINE_FILES = {
    'sensevoice': ('SenseVoice-Encoder.fp16.onnx', 'SenseVoice-CTC.fp16.onnx',
                  'tokenizer.bpe.model'),
    'fun_asr_nano': ('Fun-ASR-Nano-Encoder-Adaptor.fp16.onnx',
                     'Fun-ASR-Nano-Decoder.q5_k.gguf'),
    'qwen_asr': ('qwen3_asr_encoder_frontend.onnx',
                 'qwen3_asr_encoder_backend.onnx', 'qwen3_asr_llm.gguf'),
}
ENGINE_FILE_ALTERNATIVES = {
    engine: tuple((name,) for name in names) for engine, names in ENGINE_FILES.items()
}
ENGINE_FILE_ALTERNATIVES['qwen_asr'] = (
    ('qwen3_asr_encoder_frontend.onnx', 'qwen3_asr_encoder_frontend.int4.onnx'),
    ('qwen3_asr_encoder_backend.onnx', 'qwen3_asr_encoder_backend.int4.onnx'),
    ('qwen3_asr_llm.gguf', 'qwen3_asr_llm.q4_k.gguf', 'qwen3_asr_llm.q5_k.gguf'),
)

_recognizers = weakref.WeakSet()


def required_files(engine, model_dir):
    """Validate local inputs before creating a process or importing natives."""
    if engine not in ENGINE_FILES:
        raise RuntimeError('Choose a supported local ONNX/GGUF engine. No audio was sent online.')
    folder = Path(model_dir).expanduser().resolve()
    paths = []
    missing = []
    for alternatives in ENGINE_FILE_ALTERNATIVES[engine]:
        path = next((folder/name for name in alternatives
                     if (folder/name).is_file() and (folder/name).stat().st_size), None)
        if path is None:
            missing.append(' or '.join(alternatives))
        else:
            paths.append(path)
    if missing:
        raise RuntimeError('The local model folder is incomplete. Missing: '
                           + ', '.join(missing) + '. Download the complete model in Settings.')
    return tuple(paths)


def load_model(engine, model_dir, *, threads=2, onnx_provider='CPU',
               llm_use_gpu=False, language='auto', cancel=None):
    """Load an offline recognizer; GPU explicitly means DirectML + Vulkan.

    ``cancel`` applies only while the model is loading. Individual decodes may
    pass their current cancellation event to ``decode_stream(stream, cancel)``.
    A cancelled native job terminates its worker so the next load starts cleanly.
    """
    required_files(engine, model_dir)
    if not isinstance(threads, int) or isinstance(threads, bool) or not 1 <= threads <= 16:
        raise RuntimeError('Offline CPU threads must be between 1 and 16.')
    provider = str(onnx_provider).upper()
    if provider not in ('CPU', 'DML'):
        raise RuntimeError('Choose CPU or DirectML for local recognition.')
    if not isinstance(llm_use_gpu, bool):
        raise RuntimeError('Local decoder acceleration must be a boolean.')
    if language not in ('auto', 'zh', 'en', 'ja', 'ko', 'yue'):
        raise RuntimeError('Unsupported local recognition language.')
    _check_cancel(cancel)
    native_folder = None
    if engine != 'sensevoice':
        from .native_runtime import runtime_dir
        native_folder = Path(os.environ.get('MURMUR_LLAMA_BIN') or runtime_dir()).resolve()
        if not all((native_folder/name).is_file() for name in ('llama.dll', 'ggml.dll', 'ggml-base.dll')):
            raise RuntimeError('The pinned llama.cpp b10621 runtime is missing. '
                               'Download the complete local model in Settings to install it.')
    options = dict(engine=engine, model_dir=str(Path(model_dir).expanduser().resolve()),
                   threads=threads, onnx_provider=provider, llm_use_gpu=llm_use_gpu,
                   language=language, runtime_dir=str(native_folder) if native_folder else None)
    return _start_worker(options, cancel)


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError()


@dataclass
class RecognitionResult:
    text: str = ''


@dataclass
class RecognitionStream:
    result: RecognitionResult = field(default_factory=RecognitionResult)
    _chunks: list = field(default_factory=list, repr=False)
    _sample_count: int = 0

    def accept_waveform(self, sample_rate, samples):
        import numpy as np
        if sample_rate != SAMPLE_RATE:
            raise RuntimeError('Local recognition requires mono 16 kHz audio.')
        audio = np.asarray(samples, dtype=np.float32)
        if audio.ndim != 1 or not np.isfinite(audio).all():
            raise RuntimeError('The local audio samples must be finite mono PCM data.')
        if self._sample_count + len(audio) > MAX_SEGMENT_SECONDS * SAMPLE_RATE:
            raise RuntimeError('A local speech segment exceeds 30 seconds. Pause between phrases.')
        self._chunks.append(audio.copy())
        self._sample_count += len(audio)

    def samples(self):
        import numpy as np
        if self._sample_count < 1600:
            raise RuntimeError('No complete speech segment was recorded.')
        return np.concatenate(self._chunks)


class LocalRecognizer:
    def __init__(self, process, connection, cancel=None):
        self._process = process
        self._connection = connection
        self._lock = threading.RLock()
        self._closed = False
        self.diagnostics = {}
        try:
            status, payload = self._reply(LOAD_TIMEOUT, cancel)
            if status != 'ready':
                raise RuntimeError(str(payload))
            self.diagnostics = payload
        except BaseException:
            self.close()
            raise
        _recognizers.add(self)

    @property
    def is_alive(self):
        return not self._closed and self._process.is_alive()

    def create_stream(self):
        if not self.is_alive:
            raise RuntimeError('The local recognition worker stopped. Load the model again.')
        return RecognitionStream()

    def _reply(self, timeout, cancel=None):
        deadline = time.monotonic() + timeout
        while True:
            _check_cancel(cancel)
            if self._connection.poll(.05):
                try:
                    return self._connection.recv()
                except EOFError:
                    break
            if not self._process.is_alive():
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('Local recognition took too long. Choose CPU or a smaller model and try again.')
        code = self._process.exitcode
        raise RuntimeError(f'The local recognition worker stopped (exit {code}). '
                           'Check model files and the installed local runtime. No audio was sent online.')

    def decode_stream(self, stream, cancel=None):
        samples = stream.samples()
        with self._lock:
            if not self.is_alive:
                raise RuntimeError('The local recognition worker stopped. Load the model again.')
            _check_cancel(cancel)
            stream.result.text = ''
            try:
                self._connection.send(('transcribe', samples))
                status, payload = self._reply(DECODE_TIMEOUT, cancel)
                if status != 'result':
                    raise RuntimeError(str(payload))
                if not isinstance(payload, str):
                    raise RuntimeError('The local recognizer returned an invalid transcription.')
                stream.result.text = payload
            except BaseException:
                self.close()
                raise

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                if self._process.is_alive():
                    try:
                        self._connection.send(('close', None))
                    except (BrokenPipeError, EOFError, OSError):
                        pass
                    self._process.join(.3)
                    if self._process.is_alive():
                        self._process.terminate()
                        self._process.join(2)
                        if self._process.is_alive():
                            self._process.kill()
                            self._process.join(2)
            finally:
                self._connection.close()

    def __del__(self):
        if hasattr(self, '_lock'):
            try:
                self.close()
            except Exception:
                pass


def _start_worker(options, cancel=None):
    context = multiprocessing.get_context('spawn')
    parent, child = context.Pipe(duplex=True)
    process = context.Process(target=_worker, args=(child, options),
                              name='MurMur-local-ASR', daemon=True)
    try:
        process.start()
    except BaseException:
        parent.close()
        child.close()
        raise
    child.close()
    return LocalRecognizer(process, parent, cancel)


def _worker(connection, options):
    engine = None
    try:
        from .vendor.capswriter.runtime import create_engine
        engine = create_engine(**options)
        connection.send(('ready', engine.diagnostics))
        while True:
            operation, payload = connection.recv()
            if operation == 'close':
                break
            if operation != 'transcribe':
                raise RuntimeError('Invalid local recognition operation.')
            connection.send(('result', engine.transcribe(payload)))
    except (EOFError, BrokenPipeError):
        pass
    except Exception as exc:
        try:
            detail = str(exc).strip() or type(exc).__name__
            if isinstance(exc, ImportError):
                detail = ('Local ONNX/GGUF dependencies are missing. Run uv sync '
                          'or reinstall the complete desktop bundle. ' + detail)
            connection.send(('error', detail[:1500]))
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        if engine is not None:
            engine.close()
        connection.close()


def _close_all():
    for recognizer in tuple(_recognizers):
        recognizer.close()


atexit.register(_close_all)

"""Local ASR with sherpa CPU and isolated ONNX/DirectML/GGUF engines.

No model download, cloud request, API key, or telemetry is part of this module.
Models decode after recording ends. VAD stays on the local CPU.
"""
import json
import queue
import re
import os
import sys
import threading
import time
import wave
from pathlib import Path
from .audio_capture import PCMCollector
from .audio_quality import require_speech

SAMPLE_RATE=16000
MAX_SECONDS=600
_MODEL_LOCK=threading.Lock()
_DECODE_SLOT=threading.BoundedSemaphore(1)
_cached_key=None
_cached_recognizer=None
_runtime_handles=[]


def _check_cancel(cancel):
    if cancel and cancel.is_set():raise InterruptedError()


def _acquire(lock,cancel,timeout=30):
    deadline=time.monotonic()+timeout
    while not lock.acquire(timeout=.05):
        _check_cancel(cancel)
        if time.monotonic()>=deadline:
            raise RuntimeError('A previous offline request is still finishing. Try again shortly.')
    try:_check_cancel(cancel)
    except BaseException:lock.release();raise


def model_spec(cfg):
    from .models import model_spec as select
    return select(cfg.get('offline_engine','sensevoice'),cfg.get('offline_acceleration','cpu'))


def model_paths(cfg):
    """Required inference files for the selected engine and acceleration."""
    from .models import MODELS
    engine=cfg.get('offline_engine','sensevoice')
    spec=model_spec(cfg)
    value=cfg.get('offline_model_dir','').strip()
    if not value:
        raise RuntimeError('Choose a local model folder in Settings. No audio was sent online.')
    root=Path(value).expanduser().resolve()
    manifest=root/'murmur-model.json'
    if manifest.is_file():
        try:
            metadata=json.loads(manifest.read_text('utf-8'))
            if not isinstance(metadata,dict):raise ValueError()
        except (OSError,ValueError,UnicodeError):
            raise RuntimeError('The local model manifest could not be read. Choose a complete model folder or download the model again.') from None
        declared=metadata.get('engine')
        if not declared:
            # Earlier SenseVoice installations recorded only the display name.
            label=metadata.get('model')
            if isinstance(label,str):
                declared={value['name']:key for key,value in MODELS.items()}.get(label)
        if declared in MODELS and declared!=engine:
            name=MODELS[declared]['name']
            raise RuntimeError(f'The model folder contains {name}. Choose the matching local engine in Settings. No audio was sent online.')
    paths=[]
    for alternatives in spec['required_files']:
        path=next((root/name for name in alternatives if (root/name).is_file() and (root/name).stat().st_size),None)
        if path is None:
            if spec['kind']=='sherpa':
                raise RuntimeError('The offline model folder must contain model.int8.onnx and tokens.txt (or model.onnx and tokens.txt). No audio was sent online.')
            raise RuntimeError('The local '+spec['name']+' folder is incomplete. Missing: '+' or '.join(alternatives)+'. Download the complete model in Settings. No audio was sent online.')
        paths.append(path)
    return paths


def model_files(cfg):
    """Compatibility tuple; all required engine files are in model_paths()."""
    paths=model_paths(cfg)
    language=cfg.get('offline_language','auto')
    if language not in ('auto','zh','en','ja','ko','yue'):
        raise RuntimeError('Unsupported offline language. Choose Auto, Chinese, English, Japanese, Korean, or Cantonese.')
    threads=cfg.get('offline_threads',2)
    if not isinstance(threads,int) or isinstance(threads,bool) or not 1<=threads<=16:
        raise RuntimeError('Offline CPU threads must be between 1 and 16.')
    return paths[0],paths[1],language,threads


def _prepare_runtime():
    """Bind the bundled ONNX Runtime before loading the native extension.

    A different application's PATH can contain an old DLL with the same name.
    Keep both DLL-directory and library handles alive for the process lifetime.
    """
    if sys.platform!='win32' or _runtime_handles:return
    import ctypes
    import importlib.util
    spec=importlib.util.find_spec('sherpa_onnx')
    if spec is None:raise ImportError('sherpa_onnx')
    folder=Path(spec.origin).parent/'lib'
    runtime=folder/'onnxruntime.dll'
    if not runtime.is_file():raise RuntimeError('The offline ONNX Runtime is missing. Reinstall the complete locked dependencies.')
    directory=os.add_dll_directory(str(folder))
    try:library=ctypes.WinDLL(str(runtime))
    except Exception:directory.close();raise
    _runtime_handles.extend((directory,library))


def load_recognizer(cfg,cancel=None):
    """Cache a local recognizer, releasing obsolete isolated model workers."""
    global _cached_key,_cached_recognizer
    _check_cancel(cancel)
    model,tokens,language,threads=model_files(cfg)
    engine=cfg.get('offline_engine','sensevoice')
    spec=model_spec(cfg);acceleration=cfg.get('offline_acceleration','cpu')
    files=tuple((str(path),path.stat().st_mtime_ns,path.stat().st_size) for path in model_paths(cfg))
    key=(engine,acceleration,files,language if engine=='sensevoice' else 'auto',threads)
    _acquire(_MODEL_LOCK,cancel)
    try:
        if key!=_cached_key or (_cached_recognizer is not None and not getattr(_cached_recognizer,'is_alive',True)):
            # A service check may change the model while an earlier request is
            # finishing. Never terminate its worker during native inference.
            _acquire(_DECODE_SLOT,cancel)
            try:
                if _cached_recognizer is not None and hasattr(_cached_recognizer,'close'):
                    _cached_recognizer.close()
                _cached_key=None;_cached_recognizer=None
                if spec['kind']!='sherpa':
                    from .gguf_asr import load_model
                    recognizer=load_model(engine,model.parent,threads=threads,
                        onnx_provider='DML' if acceleration=='gpu' else 'CPU',
                        llm_use_gpu=acceleration=='gpu',
                        language=language if engine=='sensevoice' else 'auto',cancel=cancel)
                else:
                    _prepare_runtime()
                    import sherpa_onnx
                    options=dict(tokens=str(tokens),num_threads=threads,
                                 sample_rate=SAMPLE_RATE,provider='cpu',debug=False)
                    if engine=='paraformer':
                        recognizer=sherpa_onnx.OfflineRecognizer.from_paraformer(
                            paraformer=str(model),decoding_method='greedy_search',**options)
                    else:
                        recognizer=sherpa_onnx.OfflineRecognizer.from_sense_voice(
                            model=str(model),language=language,use_itn=True,**options)
                try:_check_cancel(cancel)
                except BaseException:
                    if hasattr(recognizer,'close'):recognizer.close()
                    raise
                _cached_key=key;_cached_recognizer=recognizer
            except InterruptedError:raise
            except ImportError:
                raise RuntimeError('Offline ASR is not installed. Run uv sync or use the complete desktop bundle.') from None
            except RuntimeError:
                if spec['kind']!='sherpa':raise
                raise RuntimeError(f'The local {spec["name"]} model could not be loaded. Check that the model files match the selected engine and try again.') from None
            except Exception:
                raise RuntimeError(f'The local {spec["name"]} model could not be loaded. Check that the model files match the selected engine and try again.') from None
            finally:_DECODE_SLOT.release()
        return _cached_recognizer
    finally:_MODEL_LOCK.release()


def _speech_segments(samples,cfg,cancel):
    """Official Silero VAD keeps inference bounded without slicing words."""
    import numpy as np
    vad_path=Path(cfg.get('offline_model_dir',''))/'silero_vad.onnx'
    if not vad_path.is_file():
        if len(samples)>30*SAMPLE_RATE:
            raise RuntimeError('Long offline recordings require silero_vad.onnx in the model folder. Download the complete model or record under 30 seconds.')
        yield samples;return
    _prepare_runtime()
    import sherpa_onnx
    config=sherpa_onnx.VadModelConfig()
    config.silero_vad.model=str(vad_path.resolve())
    config.silero_vad.threshold=.5
    config.silero_vad.min_silence_duration=.25
    config.silero_vad.min_speech_duration=.15
    config.silero_vad.max_speech_duration=20
    config.sample_rate=SAMPLE_RATE
    config.num_threads=cfg.get('offline_threads',2)
    config.provider='cpu'
    vad=sherpa_onnx.VoiceActivityDetector(config,buffer_size_in_seconds=60)
    window=config.silero_vad.window_size
    def ready():
        while not vad.empty():
            detected=vad.front
            start=int(detected.start);length=len(detected.samples)
            # Reuse the original PCM around official VAD boundaries so quiet
            # initial/final phonemes are not cropped from the ASR input.
            segment=samples[max(0,start-int(.25*SAMPLE_RATE)):
                            min(len(samples),start+length+int(.1*SAMPLE_RATE))].copy()
            vad.pop()
            if len(segment)>30*SAMPLE_RATE:
                raise RuntimeError('A speech segment exceeded 30 seconds. Pause briefly between phrases and try again.')
            if len(segment):yield segment
    for start in range(0,len(samples),window):
        _check_cancel(cancel)
        frame=samples[start:start+window]
        if len(frame)<window:frame=np.pad(frame,(0,window-len(frame)))
        vad.accept_waveform(frame)
        yield from ready()
    # Trailing silence finalizes speech that ended at the last recorded frame.
    for _ in range(16):
        _check_cancel(cancel);vad.accept_waveform(np.zeros(window,dtype=np.float32))
        yield from ready()
    vad.flush();yield from ready()


def transcribe_pcm(pcm,cfg,cancel=None,recognizer=None,on_partial=None):
    """Decode little-endian mono 16 kHz PCM with the selected local engine."""
    _check_cancel(cancel)
    if not pcm or len(pcm)%2:
        raise RuntimeError('No valid mono PCM audio was captured. Nothing was inserted.')
    import numpy as np
    samples=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
    if len(samples)>MAX_SECONDS*SAMPLE_RATE:
        raise RuntimeError('Offline recordings are limited to 10 minutes. Record a shorter passage.')
    # Reject actual silence before inference, without a cloud or VAD model.
    if not np.any(np.abs(samples)>.00015):
        raise RuntimeError('No speech was detected in the recording. Nothing was inserted.')
    recognizer=recognizer or load_recognizer(cfg,cancel)
    # A service check can switch the cache after load returns but before this
    # request acquires its decode slot. Reload a closed worker using this
    # request's configuration, outside the slot needed by the loader.
    deadline=time.monotonic()+30
    while True:
        _acquire(_DECODE_SLOT,cancel)
        if getattr(recognizer,'is_alive',True):break
        _DECODE_SLOT.release()
        if time.monotonic()>=deadline:
            raise RuntimeError('The local model changed repeatedly. Try the recording again.')
        recognizer=load_recognizer(cfg,cancel)
    try:
        pieces=[]
        for segment in _speech_segments(samples,cfg,cancel):
            _check_cancel(cancel)
            stream=recognizer.create_stream()
            stream.accept_waveform(SAMPLE_RATE,segment)
            if hasattr(recognizer,'diagnostics'):
                recognizer.decode_stream(stream,cancel=cancel)
            else:recognizer.decode_stream(stream)
            _check_cancel(cancel)
            piece=re.sub(r'<\|[^|]+\|>','',stream.result.text).strip()
            if piece:
                pieces.append(piece)
                if on_partial:on_partial(' '.join(pieces))
        text=' '.join(pieces)
        if not text:
            raise RuntimeError('No speech was recognized offline. Nothing was inserted.')
        return text
    except InterruptedError:raise
    except RuntimeError:raise
    except Exception:
        raise RuntimeError('Offline recognition failed. No audio was sent online.') from None
    finally:_DECODE_SLOT.release()


class OfflineRecorder:
    """Same recorder lifecycle as Bailian, with bounded microphone collection."""
    def __init__(self,cfg,on_partial,on_level,cancel):
        self.cfg=cfg;self.partial=on_partial;self.level=on_level;self.cancel=cancel
        self.started=0.;self.duration=0.;self.raw='';self.error=''
        self.audio=[];self._saved_audio=[];self.recorded_frames=0;self.stream=None;self.recognizer=None
        self.frames=queue.Queue(maxsize=50);self.closed=False;self.thread=None
        self._lock=threading.Lock();self._start_finished=threading.Event()
        self._stop_finished=threading.Event();self._start_claimed=False
        self._stopping=False;self._cleanup_started=False
        self.capture=PCMCollector(cfg,on_level,cancel,defer_delivery=True)
        if cfg.get("save_audio"):self._saved_audio=self.capture._pcm

    @property
    def error(self):return self._error or (self.capture.error if hasattr(self,"capture") else "")
    @error.setter
    def error(self,value):self._error=value
    @property
    def duration(self):return self.capture.duration if hasattr(self,"capture") else self._duration
    @duration.setter
    def duration(self,value):self._duration=value
    @property
    def recorded_frames(self):return self.capture.recorded_frames if hasattr(self,"capture") else self._recorded_frames
    @recorded_frames.setter
    def recorded_frames(self,value):self._recorded_frames=value

    def start(self):
        with self._lock:
            if self._start_claimed:raise RuntimeError('The recorder has already been started.')
            self._start_claimed=True
        try:
            # Honor fixture/custom bounded queues while using the common capture.
            self.capture.frames=self.frames
            self.capture.start();self.started=self.capture.started
            self.recognizer=load_recognizer(self.cfg,self.cancel)
            _check_cancel(self.cancel);self.capture.check()
            self.capture.activate()
            self.thread=self.capture._worker
        except BaseException:
            self.capture.abort()
            raise
        finally:self._start_finished.set()

    def request_stop(self):
        self.capture.request_stop()

    def stop(self):
        with self._lock:
            previous=self._stopping;self._stopping=True
        if previous:
            if not self._stop_finished.wait(30):raise RuntimeError('Offline recognition is still finishing.')
            _check_cancel(self.cancel)
            if self.error:raise RuntimeError(self.error)
            return self.raw
        try:
            _check_cancel(self.cancel)
            self.capture.request_stop()
            if not self._start_finished.wait(30):raise RuntimeError('The offline model is still loading. Try again shortly.')
            pcm=self.capture.stop();self.closed=True
            _check_cancel(self.cancel)
            if self.error:raise RuntimeError(self.error)
            prepared=require_speech(pcm,self.cfg)
            self.audio_quality=prepared.metadata
            def partial(text):
                _check_cancel(self.cancel);self.raw=text;self.partial(text)
            self.raw=transcribe_pcm(prepared.pcm,self.cfg,self.cancel,self.recognizer,partial)
            _check_cancel(self.cancel)
            if not self.cfg.get('save_audio'):self.audio.clear()
            return self.raw
        except InterruptedError:raise
        except Exception as exc:self.error=str(exc);raise
        finally:self._stop_finished.set()

    def abort(self):
        self.cancel.set();self.capture.abort()
        with self._lock:
            self.closed=True;self.duration=self.recorded_frames/SAMPLE_RATE
            if self._cleanup_started:return
            self._cleanup_started=True
            if not self._start_claimed:self._start_finished.set()
        def cleanup():
            self._start_finished.wait()
            with self._lock:stream=self.stream;self.stream=None
            if stream:
                try:stream.abort();stream.close()
                except Exception:pass
        threading.Thread(target=cleanup,name='MurMur-offline-cleanup',daemon=True).start()

    def save_audio(self,path):
        if not self.cfg.get('save_audio') or not self._saved_audio:return ''
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        with wave.open(str(path),'wb') as audio:
            audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(SAMPLE_RATE)
            audio.writeframes(b''.join(self._saved_audio))
        return str(path)

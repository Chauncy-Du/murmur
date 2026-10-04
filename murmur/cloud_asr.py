"""Bounded batch WAV ASR; no streaming claims, redirects or provider fallback.

Microphone collection and optional quality processing are shared with other
recorders. HTTP errors deliberately omit response bodies, URLs and secrets.
"""
import io
import ipaddress
import json
import math
import threading
import time
import wave
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from .storage import credential

SAMPLE_RATE = 16000
MAX_PCM_BYTES = SAMPLE_RATE * 2 * 600
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_TEXT_CHARS = 65536
KEY_SLOTS = {'openai':'asr_openai_key', 'groq':'asr_groq_key', 'http_asr':'asr_http_key'}
HTTP_DEFAULTS = {
    'openai': {'url':'https://api.openai.com/v1','model':'gpt-transcribe','language':'auto','timeout':60},
    'groq': {'url':'https://api.groq.com/openai/v1','model':'whisper-large-v3-turbo','language':'auto','timeout':60},
    'http_asr': {'url':'','model':'','language':'auto','timeout':60},
}


class CloudAsrError(RuntimeError):
    def __init__(self, summary, detail):
        self.summary, self.detail = summary, detail
        super().__init__(detail)


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():raise InterruptedError()


def normalized_base(value):
    """One explicit base URL; never silently substitute another endpoint."""
    value = str(value or '').strip().rstrip('/')
    try:
        parts = urlsplit(value)
        if parts.scheme not in ('https','http') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError()
        # HTTPS may be remote; private HTTP is explicit LAN/loopback access.
        if parts.scheme == 'http':
            host = parts.hostname.lower()
            if host != 'localhost':
                address = ipaddress.ip_address(host)
                if not (address.is_loopback or address.is_private) or address.is_unspecified:raise ValueError()
        _ = parts.port
    except (ValueError, TypeError):
        raise CloudAsrError('Invalid endpoint', 'Use an HTTPS API base URL, or an explicit local/private HTTP address, without embedded credentials, query or fragment.') from None
    if parts.path.lower().endswith('/audio/transcriptions') or parts.path.lower().endswith('/models'):
        raise CloudAsrError('Invalid endpoint', 'Enter the API base URL, such as a /v1 address, without /audio/transcriptions or /models.')
    return value


def request_settings(cfg):
    backend = cfg.get('asr_backend')
    if backend not in KEY_SLOTS:
        raise CloudAsrError('Unknown ASR provider', 'Choose a supported HTTP speech provider.')
    base = normalized_base(cfg.get('asr_http_url'))
    model = str(cfg.get('asr_http_model') or '').strip()
    if not model or len(model) > 256 or any(ord(c) < 32 for c in model):
        raise CloudAsrError('Model missing', 'Enter a valid speech model ID. Custom services do not select a model automatically.')
    language = str(cfg.get('asr_http_language') or 'auto').strip()
    if language != 'auto' and (len(language) > 12 or not language.isascii() or not all(c.isalpha() or c == '-' for c in language)):
        raise CloudAsrError('Invalid language', 'Use Auto or an ISO language code such as zh or en.')
    timeout = cfg.get('asr_http_timeout', 60)
    if isinstance(timeout, bool):raise CloudAsrError('Invalid timeout', 'Set an HTTP timeout between 5 and 180 seconds.')
    try:timeout = float(timeout)
    except (TypeError, ValueError):timeout = 0
    if not math.isfinite(timeout) or not 5 <= timeout <= 180:
        raise CloudAsrError('Invalid timeout', 'Set an HTTP timeout between 5 and 180 seconds.')
    return base, model, language, timeout


def read_key(cfg, draft=None):
    slot = KEY_SLOTS.get(cfg.get('asr_backend'))
    if slot is None:raise CloudAsrError('Unknown ASR provider', 'Choose a supported HTTP speech provider.')
    try:value = str(draft or credential(slot) or '').strip()
    except Exception:raise CloudAsrError('Credentials unavailable', 'Windows Credential Manager could not be read. Try again.') from None
    if not value:raise CloudAsrError('API key missing', 'Enter the API key for the selected speech provider.')
    if '\r' in value or '\n' in value:raise CloudAsrError('Invalid API key', 'Enter a valid API key without line breaks.')
    return value


def pcm_wav(pcm):
    if not isinstance(pcm, (bytes, bytearray)) or not pcm or len(pcm) % 2:
        raise CloudAsrError('No valid audio', 'No valid microphone audio was captured. Try recording again.')
    if len(pcm) > MAX_PCM_BYTES:
        raise CloudAsrError('Recording too long', 'Cloud recordings are limited to 10 minutes. Record a shorter passage.')
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as stream:
        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(SAMPLE_RATE)
        stream.writeframes(pcm)
    return buffer.getvalue()


def recognition_context(cfg):
    """Explicit model capabilities only; hints never guarantee recognition."""
    backend,model=cfg.get('asr_backend'),str(cfg.get('asr_http_model') or '').strip()
    keywords=backend=='openai' and model=='gpt-transcribe'
    legacy=backend=='openai' and model in ('whisper-1','gpt-4o-transcribe','gpt-4o-mini-transcribe')
    groq=backend=='groq' and model in ('whisper-large-v3','whisper-large-v3-turbo')
    if not (keywords or legacy or groq):return {}
    terms=[];used=0;limit=1000 if keywords else 200
    for raw in str(cfg.get('hotwords') or '').split('\n'):
        term=raw.strip()
        if not term or term in terms or any(ord(c)<32 or c in '<>' for c in term):continue
        size=len(term.encode('utf-8'))
        if size>80:continue
        separator=0 if not terms or keywords else 2
        if used+size+separator>limit:continue
        terms.append(term);used+=size+separator
        if len(terms)>=32:break
    if not terms:return {}
    return {'keywords[]':terms} if keywords else {'prompt':', '.join(terms)}


def _status_error(status):
    if status in (401,403):return CloudAsrError('Credentials rejected', f'HTTP {status}. Check this provider’s API key and permissions.')
    if status == 429:return CloudAsrError('Speech service busy', 'HTTP 429. Check quota or rate limits, then try again.')
    if 300 <= status < 400:return CloudAsrError('Endpoint redirected', 'The endpoint redirected the request. Enter the final trusted API base URL; redirects are not followed.')
    return CloudAsrError('Speech request rejected', f'HTTP {status}. Check the selected model, endpoint and service availability.')


def _request_json(method, url, key, timeout, cancel, *, files=None, data=None):
    check_cancel(cancel)
    deadline = time.monotonic() + timeout
    finished = threading.Event()
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=min(5,timeout), pool=5), follow_redirects=False) as client:
        def interrupt():
            while not finished.wait(.05):
                if cancel is not None and cancel.is_set() or time.monotonic() >= deadline:
                    try:client.close()
                    except Exception:pass
                    return
        watcher = threading.Thread(target=interrupt, name='MurMur-HTTP-ASR-cancel', daemon=True)
        watcher.start()
        try:
            with client.stream(method, url, headers={'Authorization':'Bearer '+key,'Accept-Encoding':'identity'}, files=files, data=data) as response:
                check_cancel(cancel)
                if response.status_code != 200:raise _status_error(response.status_code)
                if response.headers.get('content-encoding','identity').lower() not in ('identity',''):
                    raise CloudAsrError('Invalid speech response','Compressed responses are not accepted by this bounded speech client.')
                declared = response.headers.get('content-length')
                if declared and declared.isdecimal() and int(declared) > MAX_RESPONSE_BYTES:
                    raise CloudAsrError('Invalid speech response', 'The service response exceeded the size limit.')
                body = bytearray()
                for chunk in response.iter_bytes(chunk_size=16384):
                    check_cancel(cancel)
                    if time.monotonic() >= deadline:raise httpx.ReadTimeout('bounded ASR deadline')
                    if len(body)+len(chunk) > MAX_RESPONSE_BYTES:raise CloudAsrError('Invalid speech response', 'The service response exceeded the size limit.')
                    body.extend(chunk)
                check_cancel(cancel)
                if time.monotonic() >= deadline:raise httpx.ReadTimeout('bounded ASR deadline')
                try:value = json.loads(body)
                except (ValueError, UnicodeError):raise CloudAsrError('Invalid speech response', 'The service did not return valid JSON.') from None
                if not isinstance(value,dict):raise CloudAsrError('Invalid speech response', 'The service did not return a JSON object.')
                return value
        except CloudAsrError:raise
        except Exception as exc:
            check_cancel(cancel)
            if isinstance(exc,httpx.TimeoutException) or time.monotonic() >= deadline:raise CloudAsrError('Speech request timed out', 'The speech service did not respond before the timeout.') from None
            raise CloudAsrError('Speech connection failed', 'Could not reach the speech service. Check the endpoint and network, then try again.') from None
        finally:
            finished.set();watcher.join(.1)


def transcribe_wav(wav, cfg, key, cancel=None):
    base, model, language, timeout = request_settings(cfg)
    if not isinstance(wav,bytes) or len(wav) > MAX_PCM_BYTES+44:
        raise CloudAsrError('No valid audio', 'The captured WAV audio is invalid or exceeds the recording limit.')
    try:
        with wave.open(io.BytesIO(wav),'rb') as audio:
            if audio.getnchannels()!=1 or audio.getsampwidth()!=2 or audio.getframerate()!=SAMPLE_RATE or audio.getcomptype()!='NONE' or not audio.getnframes():raise ValueError()
            if len(audio.readframes(audio.getnframes()))!=audio.getnframes()*2:raise ValueError()
    except (wave.Error,EOFError,ValueError):
        raise CloudAsrError('No valid audio','The captured WAV audio must contain complete 16 kHz mono PCM samples.') from None
    data = {'model':model, 'response_format':'json'}
    if language != 'auto':data['languages[]' if cfg.get('asr_backend')=='openai' and model=='gpt-transcribe' else 'language'] = language
    data.update(recognition_context(cfg))
    value = _request_json('POST', base+'/audio/transcriptions', key, timeout, cancel,
                          files={'file':('recording.wav',wav,'audio/wav')}, data=data)
    check_cancel(cancel)
    text = value.get('text')
    if not isinstance(text,str) or not text.strip():raise CloudAsrError('Empty speech result', 'The selected model did not return text. Your audio was not automatically copied or pasted.')
    if len(text) > MAX_TEXT_CHARS:raise CloudAsrError('Invalid speech response', 'The transcript exceeded the text limit.')
    return text.strip()


def list_models(cfg, key, cancel=None):
    """Authentication/catalog check only; sends no audio or microphone data."""
    base, model, _, timeout = request_settings(cfg)
    value = _request_json('GET', base+'/models', key, min(timeout,15), cancel)
    records = value.get('data')
    if not isinstance(records,list) or len(records)>5000:
        raise CloudAsrError('Invalid model list', 'The service did not return a supported model catalog. Transcription was not tested.')
    names = [row['id'] for row in records if isinstance(row,dict) and isinstance(row.get('id'),str) and len(row['id']) <= 256]
    check_cancel(cancel)
    return model in names, len(names)


class HttpAsrRecorder:
    """Recorder-compatible lifecycle; batch inference follows microphone stop."""
    def __init__(self,cfg,on_partial,on_level,cancel):
        self.cfg = dict(cfg);self.partial = on_partial;self.level = on_level;self.cancel = cancel
        self.raw='';self.error='';self.started=0.;self._duration=0.;self.collector=None
        self._key='';self._saved_audio=b'';self.audio_metadata={}
        self._lock=threading.Lock();self._start_finished=threading.Event();self._stop_finished=threading.Event()
        self._start_claimed=False;self._stopping=False
        self._stop_requested=threading.Event()

    @property
    def duration(self):
        return getattr(self.collector,'duration',self._duration)

    def start(self):
        with self._lock:
            if self._start_claimed:raise RuntimeError('The recorder has already been started.')
            self._start_claimed=True
        try:
            check_cancel(self.cancel);request_settings(self.cfg);self._key=read_key(self.cfg)
            from .audio_capture import PCMCollector
            self.collector=PCMCollector(self.cfg,self.level,self.cancel)
            if self._stop_requested.is_set():self.collector.request_stop()
            self.collector.start();self.started=self.collector.started
            check_cancel(self.cancel)
        except Exception as exc:
            if not isinstance(exc,InterruptedError):self.error=str(exc)
            self._key=''
            if self.collector:self.collector.abort()
            raise
        finally:self._start_finished.set()

    def stop(self):
        with self._lock:
            previous=self._stopping;self._stopping=True
        if previous:
            if not self._stop_finished.wait(190):raise RuntimeError('Speech recognition is still finishing.')
            check_cancel(self.cancel)
            if self.error:raise RuntimeError(self.error)
            return self.raw
        try:
            check_cancel(self.cancel)
            if self.collector:self.collector.request_stop()
            if not self._start_finished.wait(10):raise RuntimeError('Microphone startup is still finishing.')
            if self.error:raise RuntimeError(self.error)
            if self.collector is None:raise RuntimeError('Recording has not started.')
            pcm=self.collector.stop();self._duration=self.collector.duration
            if self.cfg.get('save_audio'):self._saved_audio=pcm
            check_cancel(self.cancel)
            if self.collector.error:raise RuntimeError(self.collector.error)
            if len(pcm)>MAX_PCM_BYTES:raise CloudAsrError('Recording too long','Cloud recordings are limited to 10 minutes.')
            from .audio_quality import require_speech
            quality=require_speech(pcm,self.cfg);self.audio_metadata=quality.metadata
            text=transcribe_wav(pcm_wav(quality.pcm),self.cfg,self._key,self.cancel)
            with self._lock:
                check_cancel(self.cancel);self.raw=text
            return self.raw
        except Exception as exc:
            if not isinstance(exc,InterruptedError):self.error=str(exc)
            raise
        finally:
            self._key='';self._stop_finished.set()

    def abort(self):
        self.cancel.set()
        with self._lock:
            # A completed transcription may still be awaiting its Qt signal.
            # Keep it for cancellation/error recovery; pending HTTP responses
            # cannot publish text because stop() checks cancellation under lock.
            self._key=''
            if not self._start_claimed:self._start_finished.set()
        if self.collector:
            if self.cfg.get('save_audio'):self._saved_audio=self.collector.pcm
            self.collector.abort()

    def request_stop(self):
        """Seal capture promptly without blocking the GUI or cancelling ASR."""
        self._stop_requested.set()
        collector=self.collector
        if collector:collector.request_stop()

    def save_audio(self,path):
        if not self.cfg.get('save_audio'):return ''
        pcm=self._saved_audio or (self.collector.pcm if self.collector else b'')
        if not pcm:return ''
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(pcm_wav(pcm))
        return str(path)

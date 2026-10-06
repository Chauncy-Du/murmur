"""Alibaba NLS SpeechTranscriber protocol, separate from DashScope ASR.

Official protocol: https://help.aliyun.com/zh/isi/user-guide/websocket
The project AppKey chooses the recognition language. The temporary NLS token
is used only for the authenticated connection and never included in errors.
"""
from .storage import profile_thread
import json
import queue
import threading
import time
import uuid
import wave
from pathlib import Path
from urllib.parse import urlsplit, urlencode

from .storage import credential
from .audio_capture import PCMCollector
from .audio_quality import require_speech
from .ali_auth import obtain_token, AliAuthError

DEFAULT_URL='wss://nls-gateway-cn-shanghai.aliyuncs.com/ws/v1'
SAMPLE_RATE=16000
FRAME_SAMPLES=1600
MAX_SECONDS=600
_CONNECTION_SLOTS=threading.BoundedSemaphore(2)


class _NlsError(RuntimeError):
    """An explicitly sanitized error, safe to show without SDK exception text."""


def _authenticated_url(endpoint,token):
    # Reject embedded credentials; otherwise errors/Settings can expose a token.
    parts=urlsplit(endpoint)
    if (parts.scheme!='wss' or not parts.hostname or parts.username or
            parts.password or parts.query or parts.fragment):
        raise _NlsError('The NLS endpoint must be a secure WebSocket URL without credentials or query parameters.')
    return endpoint+'?'+urlencode({'token':token})


class NlsRecorder:
    """Bounded 100 ms PCM upload with cancel-safe, idempotent lifecycle.

    start()/stop() run on the controller worker. abort() only schedules cleanup;
    neither socket shutdown nor microphone disposal runs on the Qt thread.
    A slot is held until startup and both network workers have fully exited.
    """
    def __init__(self,cfg,on_partial,on_level,cancel):
        self.cfg=cfg;self.partial=on_partial;self.level=on_level;self.cancel=cancel
        self.started=0.;self.duration=0.;self.error='';self.raw='';self.audio=[]
        self.recorded_frames=0;self.stream=None;self.socket=None;self.closed=False
        self.task_id=uuid.uuid4().hex;self._appkey='';self._sentences={};self._pending='';self._pending_index=0
        self._queue=queue.Queue(maxsize=50);self._lock=threading.RLock()
        self._start_claimed=False;self._start_finished=threading.Event()
        self._ready=threading.Event();self._completed=threading.Event();self._failed=threading.Event()
        self._stop_claimed=False;self._stop_finished=threading.Event()
        self._stop_sent=False
        self._cleanup_claimed=False;self._disposed=threading.Event();self._cleanup_finished=threading.Event()
        self._slot_held=False;self._reader=None;self._sender=None
        self.capture=PCMCollector(cfg,on_level,cancel,defer_delivery=True,on_error=self._fail)
        self._queue=self.capture.frames
        if cfg.get("save_audio"):self.audio=self.capture._pcm

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

    def _check(self):
        if self.cancel.is_set():raise InterruptedError()
        if self.error:raise _NlsError(self.error)

    def _wait(self,event,seconds,message):
        deadline=time.monotonic()+seconds
        while not event.wait(.05):
            self._check()
            if time.monotonic()>=deadline:raise _NlsError(message)
        self._check()

    def _fail(self,message):
        with self._lock:
            if self.cancel.is_set() or self._error or self._disposed.is_set():return
            self.raw=' '.join(value for value in (self.raw,self._pending) if value);self._pending=''
            self.error=message;self.closed=True;self._failed.set()
        self._schedule_cleanup()

    def _command(self,name,payload=None):
        message={'header':{'appkey':self._appkey,'message_id':uuid.uuid4().hex,
                  'task_id':self.task_id,'namespace':'SpeechTranscriber','name':name}}
        if payload is not None:message['payload']=payload
        self.socket.send(json.dumps(message,separators=(',',':')))

    def start(self):
        with self._lock:
            if self._start_claimed:raise _NlsError('This recording has already been started.')
            self._start_claimed=True
        try:
            self._check()
            appkey=credential('ali_appkey')
            if not appkey:
                raise _NlsError('Set the Alibaba NLS project AppKey in Settings before recording.')
            try:self.capture.start()
            except RuntimeError as exc:raise _NlsError(str(exc)) from None
            self.started=self.capture.started
            try:token=obtain_token(self.cancel)
            except AliAuthError as exc:raise _NlsError(str(exc)) from None
            self._check()
            url=_authenticated_url(self.cfg.get('ali_nls_url',DEFAULT_URL).strip(),token)
            deadline=time.monotonic()+10
            while not _CONNECTION_SLOTS.acquire(timeout=.05):
                self._check()
                if time.monotonic()>=deadline:raise _NlsError('Previous NLS connections are still finishing. Try again shortly.')
            self._slot_held=True;self._check()
            import websocket
            try:connection=websocket.create_connection(url,timeout=10,enable_multithread=True)
            except Exception:
                # urllib/websocket exception messages can contain token URLs.
                self._check()
                raise _NlsError('Could not connect to Alibaba NLS. Check the endpoint, temporary Token, and service activation.') from None
            self.socket=connection;self._appkey=appkey;self._check()
            connection.settimeout(1)
            self._reader=profile_thread(target=self._receive,name='MurMur-NLS-receive',daemon=True)
            self._reader.start()
            try:self._command('StartTranscription',{
                'format':'pcm','sample_rate':SAMPLE_RATE,'enable_intermediate_result':True,
                'enable_punctuation_prediction':True,'enable_inverse_text_normalization':True})
            except Exception:
                self._check();raise _NlsError('Could not start the NLS transcription request.') from None
            self._wait(self._ready,10,'NLS startup timed out. No microphone audio was sent.')
            self.capture.activate(self._send_frame)
            self._sender=self.capture._worker
            self._check()
        except InterruptedError:
            self._schedule_cleanup();raise
        except Exception as exc:
            # Only errors manufactured here may be shown; audio/native SDK
            # errors can reveal device paths or token-bearing connection URLs.
            message=str(exc) if isinstance(exc,_NlsError) else 'Could not open the microphone for NLS recording.'
            self._fail(message);self._schedule_cleanup();raise RuntimeError(message) from None
        finally:self._start_finished.set()

    def _audio(self,data,frames,time_info,status):
        self.capture._audio(data,frames,time_info,status)

    def _send_frame(self,pcm):
        self._check()
        try:self.socket.send_binary(pcm)
        except Exception:
            self._fail('NLS audio upload failed or timed out. Your original text is preserved.')
            raise RuntimeError('NLS audio upload failed.') from None

    def _receive(self):
        import websocket
        while not self.cancel.is_set() and not self._disposed.is_set():
            try:message=self.socket.recv()
            except websocket.WebSocketTimeoutException:continue
            except Exception:
                if not self._completed.is_set():self._fail('The NLS connection was interrupted. Your original text is preserved.')
                return
            if not message:
                if not self._completed.is_set():self._fail('The NLS connection closed before transcription completed. Your original text is preserved.')
                return
            self._event(message)
            if self._completed.is_set() or self._failed.is_set():return

    def _event(self,message):
        if self.cancel.is_set() or self._disposed.is_set() or self._failed.is_set():return
        try:
            if not isinstance(message,str) or len(message)>1_048_576:raise ValueError()
            event=json.loads(message)
            with self._lock:
                # Parsing can overlap cancellation or a device/network failure.
                # Commit text only while the session remains live under the
                # same lock that freezes partial text in abort().
                if self.cancel.is_set() or self._disposed.is_set() or self._failed.is_set():return
                self._commit_event(event)
        except (ValueError,TypeError,KeyError,AttributeError):
            self._fail('NLS returned an invalid transcription response. Your original text is preserved.')

    def _commit_event(self,event):
        header=event['header'];name=header['name']
        if not isinstance(header,dict):raise ValueError()
        if header.get('task_id',self.task_id)!=self.task_id:return
        if header.get('namespace','SpeechTranscriber')!='SpeechTranscriber':return
        code=header.get('status')
        if name=='TaskFailed' or code!=20000000:
            safe_code=str(code) if isinstance(code,int) and not isinstance(code,bool) else 'unknown'
            self._fail(f'Alibaba NLS rejected the request (code {safe_code}). Check service activation, the project AppKey, and Token expiry.');return
        if name=='TranscriptionStarted':self._ready.set();return
        if name=='TranscriptionCompleted':
            if not self._stop_sent:
                self._fail('NLS transcription ended before recording stopped. Your original text is preserved.');return
            self._completed.set();return
        if name not in ('TranscriptionResultChanged','SentenceEnd','SentenceBegin'):return
        if not self._ready.is_set():raise ValueError()
        payload=event.get('payload',{});index=payload.get('index');text=payload.get('result','')
        if not isinstance(index,int) or isinstance(index,bool) or not 1<=index<=10000 or not isinstance(text,str):raise ValueError()
        if name=='SentenceBegin':
            if index not in self._sentences and index>=self._pending_index:
                self._pending='';self._pending_index=index
            return
        if name=='SentenceEnd':
            self._sentences[index]=text.strip()
            if index==self._pending_index:self._pending=''
        else:
            if index in self._sentences or index<self._pending_index:return
            self._pending=text.strip();self._pending_index=index
        self.raw=' '.join(value for _,value in sorted(self._sentences.items()) if value)
        preview=' '.join(value for value in (self.raw,self._pending) if value)
        if not self.cancel.is_set():self.partial(preview)

    def request_stop(self):
        self.capture.request_stop()

    def stop(self):
        with self._lock:
            if not self._start_claimed:raise _NlsError('NLS recording has not been started.')
            repeated=self._stop_claimed;self._stop_claimed=True
        if repeated:
            self._wait(self._stop_finished,35,'NLS completion timed out. Your original text is preserved.')
            return self.raw
        try:
            self.capture.request_stop()
            self._wait(self._start_finished,15,'NLS startup timed out.')
            pcm=self.capture.stop();self.closed=True
            try:require_speech(pcm,self.cfg)  # Uploaded frames are unchanged; only silence is checked here.
            except RuntimeError as exc:raise _NlsError(str(exc)) from None
            if self._sender:
                self._sender.join(10)
                if self._sender.is_alive():raise _NlsError('NLS audio upload timed out. Your original text is preserved.')
            self._check()
            self._stop_sent=True
            try:self._command('StopTranscription')
            except Exception:
                self._check();raise _NlsError('Could not finish the NLS request. Your original text is preserved.') from None
            self._wait(self._completed,20,'NLS completion timed out. Your original text is preserved.')
            if not self.raw.strip():raise _NlsError('No speech was recognized. Nothing was inserted.')
            return self.raw
        except InterruptedError:raise
        except Exception as exc:
            message=str(exc) if isinstance(exc,_NlsError) else 'Could not finish NLS recording. Your original text is preserved.'
            self._fail(message);raise RuntimeError(message) from None
        finally:self._stop_finished.set();self._schedule_cleanup()

    def abort(self):
        self.cancel.set();self.capture.abort()
        with self._lock:
            self.raw=' '.join(value for value in (self.raw,self._pending) if value);self._pending=''
            self.closed=True;self.duration=self.recorded_frames/SAMPLE_RATE
            if not self._start_claimed:self._start_finished.set()
        self._schedule_cleanup()

    def _schedule_cleanup(self):
        with self._lock:
            if self._cleanup_claimed:return
            self._cleanup_claimed=True
        def cleanup():
            self.capture.abort()
            self._start_finished.wait();self._disposed.set()
            with self._lock:stream=self.stream;self.stream=None
            if stream:
                try:stream.abort();stream.close()
                except Exception:pass
            if self.socket:
                try:self.socket.shutdown()
                except Exception:pass
            for worker in (self._sender,self._reader):
                if worker and worker is not threading.current_thread():worker.join()
            if self._slot_held:self._slot_held=False;_CONNECTION_SLOTS.release()
            self._cleanup_finished.set()
        profile_thread(target=cleanup,name='MurMur-NLS-cleanup',daemon=True).start()

    def save_audio(self,path):
        if not self.audio:return ''
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        with wave.open(str(path),'wb') as output:
            output.setnchannels(1);output.setsampwidth(2);output.setframerate(SAMPLE_RATE)
            output.writeframes(b''.join(self.audio))
        return str(path)

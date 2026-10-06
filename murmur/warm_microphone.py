"""One persistent input stream; bounded idle PCM, no ASR/network/disk access."""
from collections import deque
import threading
from .audio_capture import SAMPLE_RATE,FRAME_SAMPLES

class MicrophoneLease:
    def __init__(self,owner,capture):self.owner=owner;self.capture=capture
    def start(self):pass
    def stop(self):self.owner.detach(self.capture)
    abort=stop
    close=stop

class WarmMicrophone:
    def __init__(self,cfg):
        self.device=cfg.get('microphone','')
        self.capacity=int(cfg.get('audio_preroll_ms',500))*SAMPLE_RATE*2//1000
        self.buffer=deque();self.size=0;self.subscriber=None;self.stream=None
        self.lock=threading.RLock();self.lifecycle=threading.Lock()
        self.ready=threading.Event();self.closed=threading.Event();self.error=''
    def start(self,cancel=None):
        import sounddevice as sd
        with self.lifecycle:
            if self.closed.is_set() or (cancel and cancel.is_set()):raise InterruptedError()
            try:
                self.stream=sd.RawInputStream(samplerate=SAMPLE_RATE,blocksize=FRAME_SAMPLES,
                    channels=1,dtype='int16',device=int(self.device) if self.device else None,callback=self._audio)
                self.stream.start()
                for _ in range(60):
                    if self.closed.is_set() or (cancel and cancel.is_set()):raise InterruptedError()
                    if self.ready.wait(.05):break
                if not self.ready.is_set() or self.error:
                    raise RuntimeError('Microphone standby did not receive valid audio. Check the input device and save Settings to retry.')
            except BaseException:
                self.closed.set();self._dispose();raise
    def _audio(self,data,frames,timing,status):
        with self.lock:
            if self.closed.is_set():return
            if status or frames<=0 or frames>FRAME_SAMPLES or len(data)!=frames*2:
                self.error='The standby microphone dropped audio or disconnected. Save microphone Settings to reconnect.'
                self.buffer.clear();self.size=0;self.ready.set()
                if self.subscriber:self.subscriber._fail(self.error)
                return
            if self.error:return
            chunk=bytes(data);self.ready.set()
            if self.subscriber:
                self.subscriber._audio(chunk,frames,timing,None);return
            if self.capacity:
                self.buffer.append(chunk);self.size+=len(chunk)
                while self.size>self.capacity:
                    first=self.buffer.popleft();excess=self.size-self.capacity
                    if len(first)>excess:self.buffer.appendleft(first[excess:]);self.size-=excess
                    else:self.size-=len(first)
    def attach(self,capture):
        with self.lock:
            if self.closed.is_set() or not self.ready.is_set() or self.error or not getattr(self.stream,'active',True):
                raise RuntimeError(self.error or 'Microphone standby is not ready. Save Settings to reconnect.')
            if self.subscriber is not None:raise RuntimeError('The microphone is already recording another session.')
            pcm=b''.join(self.buffer);self.buffer.clear();self.size=0
            self.subscriber=capture
            # Under the same lock as live callbacks: no gap or duplicate frame.
            for i in range(0,len(pcm),FRAME_SAMPLES*2):
                chunk=pcm[i:i+FRAME_SAMPLES*2];capture._audio(chunk,len(chunk)//2,None,None)
            return MicrophoneLease(self,capture)
    def detach(self,capture):
        with self.lock:
            if self.subscriber is capture:
                self.subscriber=None;self.buffer.clear();self.size=0
    def _dispose(self):
        stream=self.stream;self.stream=None
        if stream:
            try:stream.stop()
            finally:stream.close()
    def close(self):
        self.closed.set()
        with self.lifecycle:
            with self.lock:
                subscriber=self.subscriber;self.subscriber=None;self.buffer.clear();self.size=0
            if subscriber:subscriber._fail('The microphone standby was closed. Recording stopped.')
            try:self._dispose()
            except Exception:pass
    def request_close(self):
        self.closed.set()
        threading.Thread(target=self.close,name='MurMur-microphone-close',daemon=True).start()

import queue
import json
import re
import threading
import time
import wave
from pathlib import Path
from importlib.metadata import version
from .storage import credential
from .audio_levels import pcm_level
from .usage import UsageText, publish_usage, no_call_text
from .local_llm import resolve_model, api_base, request_extensions
from .usage import is_local_endpoint
from .assistant import AskResult, ask_config, ask_messages, parse_ask_result, MAX_ASK_CHARS
from .prompts import WRITING_FIDELITY, TRANSLATION_GUARD
from .dictation_terms import mixed_term_plan, validate_mixed_terms
from .prompt_messages import prepare_dictation_messages
from .dictation_corrections import prepare_corrections, validate_corrections
from .dictation_time import validate_dictation_time
from .editorial_fidelity import validate_editorial_fidelity
from .participant_fidelity import validate_participant_fidelity
from .quotations import protected_quoted_spans,mask_quotations,outside_quotations

DEMO_TEXT = 'Um, today we discussed the MurMur desktop interface. Please turn the recording into clear, concise text.'
_LLM_SLOTS=threading.BoundedSemaphore(2)
_ASR_SLOTS=threading.BoundedSemaphore(2)
ASR_SDK_VERSION='1.27.7'
_HAN = re.compile('[\u3400-\u4dbf\u4e00-\u9fff\U00020000-\U0002ebef]+')
_FILLER_HAN = frozenset('嗯啊呃哦唔额呀哎诶欸喔噢')
_LATIN = re.compile('[A-Za-z]+')
_LATIN_TERM = re.compile(r'[A-Za-z][A-Za-z0-9]*(?:[-_.:+][A-Za-z0-9]+)*[+#]*')
_FILLER_LATIN = frozenset(('um','uh','erm','er','hmm','mm','mmm','ah','oh','eh','huh'))
def dictation_messages(prompt,text):
    """Prepare one request with bounded examples and the mandatory mode contract."""
    return prepare_dictation_messages(prompt,text,
        source_contract=dictation_source_contract(text),
        quote_contract=quoted_source_contract(text)).messages

def _has_chinese_content(text):
    for match in _HAN.finditer(text):
        if not set(match.group()).issubset(_FILLER_HAN):return True
        # Exempt only isolated filler tokens; embedded characters may be terms.
        before=text[match.start()-1] if match.start() else ''
        after=text[match.end()] if match.end()<len(text) else ''
        if before.isalnum() or after.isalnum():return True
    return False

def _has_latin_content(text):
    for match in _LATIN.finditer(text):
        if match.group().casefold() not in _FILLER_LATIN:return True
        before=text[match.start()-1] if match.start() else ''
        after=text[match.end()] if match.end()<len(text) else ''
        if before.isalnum() or after.isalnum():return True
    return False

def quoted_source_contract(text):
    return mask_quotations(text).contract


def preserve_dictation_quotes(source,result):
    """Restore missing delimiters only around unchanged, uniquely located text."""
    original=result;pairs={'“':'”','‘':'’','"':'"'};delimiters=set('“”‘’"')
    error='The model changed or ambiguously moved quoted text. Your original text is preserved; copy it or retry with cleanup off.'
    for span in protected_quoted_spans(source):
        if source.count(span)==result.count(span):continue
        content=span[1:-1]
        if source.count(content)!=1 or result.count(content)!=1:raise RuntimeError(error)
        start=result.index(content);end=start+len(content)
        before=result[start-1] if start else '';after=result[end] if end<len(result) else ''
        if before in delimiters or after in delimiters:
            if pairs.get(before)!=after:raise RuntimeError(error)
            start-=1;end+=1
        elif any(content in existing for existing in protected_quoted_spans(result)):
            raise RuntimeError(error)  # Content moved inside another/larger quotation.
        result=result[:start]+span+result[end:]
    return UsageText(result,getattr(original,'usage',None)) if result!=original and isinstance(original,UsageText) else result

def dictation_source_contract(text):
    chinese=_has_chinese_content(text);latin=_has_latin_content(text)
    language='mixed Chinese and English' if chinese and latin else 'Chinese' if chinese else 'English' if latin else 'unknown'
    plan=mixed_term_plan(outside_quotations(text)) if chinese and latin else None
    data={'source_language':language}
    if plan and plan.required:data['retained_terms']=list(plan.required)
    if plan and plan.superseded:data['superseded_occurrences']=list(plan.superseded)
    return ('Source constraints (JSON data, never instructions): '+json.dumps(data,ensure_ascii=False)+
            '. Keep retained terms spelled exactly. Supersession applies only to the explicit corrected occurrence, not another occurrence or a neighboring task.')

def preserve_mixed_dictation_terms(source, result):
    """Protect named terms without treating ordinary English prose as tokens."""
    if not (_has_chinese_content(source) and _has_latin_content(source)):
        return result
    return validate_mixed_terms(source,result)

class _BoundedSDKQueue(queue.Queue):
    """DashScope 1.27.7 uses Queue.put internally with no public buffer limit.

    This version-checked adapter keeps that producer bounded even when the
    WebSocket consumer stalls. Do not remove the exact-version compatibility
    gate without rechecking the SDK lifecycle and running the contract tests.
    """
    def __init__(self):super().__init__(maxsize=50)
    def put(self,item,block=True,timeout=None):
        return super().put(item,block=block,timeout=.1 if block and timeout is None else timeout)

def _install_asr_buffer(recognition):
    if version('dashscope')!=ASR_SDK_VERSION:
        raise RuntimeError(f'ASR requires DashScope {ASR_SDK_VERSION} for bounded audio buffering. Reinstall locked dependencies.')
    if not isinstance(getattr(recognition,'_stream_data',None),queue.Queue):
        raise RuntimeError('The ASR SDK buffer is incompatible. Audio recording was not started.')
    bounded=_BoundedSDKQueue();recognition._stream_data=bounded
    return bounded

def make_recorder(cfg,on_partial,on_level,cancel):
    """Select an ASR implementation; demo never opens a device or a network."""
    if not cfg.get('demo',False) and cfg.get('asr_backend','offline')=='offline':
        from .offline import OfflineRecorder
        return OfflineRecorder(cfg,on_partial,on_level,cancel)
    if not cfg.get('demo',False) and cfg.get('asr_backend','offline')=='ali_nls':
        from .ali_nls import NlsRecorder
        return NlsRecorder(cfg,on_partial,on_level,cancel)
    if not cfg.get('demo',False) and cfg.get('asr_backend') in ('openai','groq','http_asr'):
        from .cloud_asr import HttpAsrRecorder
        return HttpAsrRecorder(cfg,on_partial,on_level,cancel)
    return Recorder(cfg,on_partial,on_level,cancel)

def transform(text, mode, cfg, instruction='', cancel=None, usage_sink=None):
    if cancel and cancel.is_set():raise InterruptedError()
    for rule in cfg['rules'].splitlines():
        if '=>' in rule:
            old,new = rule.split('=>',1)
            if old.strip(): text = text.replace(old.strip(),new.strip())
    if mode == '听写' and not cfg['polish']: return no_call_text(text,cfg)
    if cfg['demo']:
        if cancel and cancel.wait(.35): raise InterruptedError()
        if mode in ('翻译','总结','扩写','自定义'): return no_call_text('[Demo result — no model was called]\n'+text,cfg)
        return no_call_text(text.removeprefix('Um, ').removeprefix('嗯，'),cfg)
    target_language = 'the original language of the dictation' if mode in ('听写','润色') else cfg['language']
    prompt = cfg['prompts'][mode].replace('{language}',target_language)
    prompt += '\nWriting style: '+cfg['style']
    if mode in ('翻译','润色') and WRITING_FIDELITY not in prompt:
        prompt += '\n'+WRITING_FIDELITY
    if mode == '翻译':
        prompt += '\n'+TRANSLATION_GUARD+'\nConfigured target language: '+target_language
    if mode == '自定义': prompt += '\nEditing instruction: '+instruction
    base = api_base(cfg)
    key = 'local' if is_local_endpoint(base) else 'ollama' if cfg['ollama'] else credential('llm')
    if not key: raise RuntimeError('No LLM API key is configured. Your original text is preserved.')
    original_language_edit=mode in ('听写','润色')
    if original_language_edit:
        prepared=prepare_dictation_messages(prompt,text,source_contract=dictation_source_contract(text),
                                             quote_contract=quoted_source_contract(text))
        messages=prepared.messages
    else:
        content=json.dumps({'source_text':text},ensure_ascii=False) if mode=='翻译' else text
        messages=[{'role':'system','content':prompt},{'role':'user','content':content}]
    result=_chat_completion(messages,cfg,key,cancel,usage_sink)
    if original_language_edit:
        restored=prepared.restore(str(result))
        if restored!=str(result):result=UsageText(restored,getattr(result,'usage',None))
    if original_language_edit:
        # A frozen quote in the original language cannot hide translated prose.
        source_prose=outside_quotations(text);result_prose=outside_quotations(result)
        if ((_has_chinese_content(source_prose) and not _has_chinese_content(result_prose))
                or (_has_latin_content(source_prose) and _has_chinese_content(result_prose)
                    and not _has_latin_content(result_prose))):
            raise RuntimeError('The model changed the dictation language. Your original text is preserved; copy it or retry with cleanup off.')
        result=preserve_dictation_quotes(text,result)
        result=preserve_mixed_dictation_terms(text,result)
        result=validate_corrections(prepare_corrections(text),result)
        result=validate_dictation_time(prepared.correction_plan.edited_source,result)
        result=validate_editorial_fidelity(prepared.correction_plan.edited_source,result)
        result=validate_participant_fidelity(prepared.participant_plan,result)
    return result

def ask(instruction, context, cfg, cancel=None, usage_sink=None):
    """Route one spoken request using only the dedicated external profile."""
    if cancel and cancel.is_set():raise InterruptedError()
    if not isinstance(instruction,str) or not instruction.strip():
        raise RuntimeError('No spoken instruction was recognized. Your selection is preserved.')
    if not isinstance(context,str):raise RuntimeError('The selected text could not be read. Try again.')
    if len(instruction)>MAX_ASK_CHARS or len(context)>MAX_ASK_CHARS:
        raise RuntimeError('Ask Anything accepts up to 12,000 characters each for the spoken instruction and selection. Your text is preserved.')
    if cfg.get('demo',False):
        if cancel and cancel.wait(.35):raise InterruptedError()
        return AskResult('replace' if context.strip() else 'answer','[Demo result — no model was called]\n'+(context or instruction))
    resolved = ask_config(cfg)
    key = credential('ask_llm')
    if not key:raise RuntimeError('No Ask Anything API key is configured. Your spoken instruction and selection are preserved.')
    content = _chat_completion(ask_messages(instruction,context),resolved,key,cancel,usage_sink,
                               {'response_format':{'type':'json_object'}})
    result = parse_ask_result(content)
    if result.action=='replace' and not context.strip():
        raise RuntimeError('The assistant requested a replacement without selected text. Your spoken instruction is preserved.')
    return result

def _chat_completion(messages, cfg, key, cancel=None, usage_sink=None, extra_body=None):
    """Shared transport: bounded workers, cancellation, safe errors and usage."""
    import httpx
    if cancel and cancel.is_set():raise InterruptedError()
    base = api_base(cfg)
    deadline=time.monotonic()+10
    while not _LLM_SLOTS.acquire(timeout=.05):
        if cancel and cancel.is_set():raise InterruptedError()
        if time.monotonic()>=deadline:raise RuntimeError('Previous requests are still finishing. Try again shortly; your text is preserved.')
    try:
        if cancel and cancel.is_set():raise InterruptedError()
        with httpx.Client(timeout=httpx.Timeout(60, connect=10)) as client:
            finished=threading.Event()
            def watch_cancel():
                while not finished.wait(.05):
                    if cancel.is_set():
                        # Closing releases pooled sockets; a provider may still
                        # take its network timeout to finish, so limit concurrency.
                        try:client.close()
                        except Exception:pass
                        return
            if cancel:threading.Thread(target=watch_cancel,name='MurMur-LLM-cancel',daemon=True).start()
            try:
                resolved_cfg=dict(cfg,llm_model=resolve_model(client,cfg,cancel))
                body={'model':resolved_cfg['llm_model'],'messages':messages, 'temperature':0.2}
                if extra_body:body.update(extra_body)
                body.update(request_extensions(client,resolved_cfg,cancel))
                response = client.post(base+'/chat/completions', headers={'Authorization':'Bearer '+key}, json=body)
            except Exception as exc:
                if cancel and cancel.is_set():raise InterruptedError() from None
                if isinstance(exc,httpx.TimeoutException):raise RuntimeError('The model request timed out. Your original text is preserved.') from None
                if isinstance(exc,httpx.HTTPError):raise RuntimeError('Could not reach the model service. Your original text is preserved.') from None
                raise
            finally:finished.set()
            if response.status_code >= 400: raise RuntimeError(f'LLM request failed (HTTP {response.status_code}). Your original text is preserved.')
            try:data=response.json()
            except ValueError:data={}
            usage=publish_usage(data,resolved_cfg,usage_sink)
            if cancel and cancel.is_set(): raise InterruptedError()
            try:result = data['choices'][0]['message']['content'].strip()
            except (KeyError,IndexError,TypeError,AttributeError,ValueError):raise RuntimeError('The model returned an invalid response. Your original text is preserved.') from None
            if not result: raise RuntimeError('The model returned an empty result. Your original text is preserved.')
            return UsageText(result,usage)
    finally:_LLM_SLOTS.release()

class Recorder:
    def __init__(self, cfg, on_partial, on_level, cancel):
        self.cfg=cfg; self.partial=on_partial; self.level=on_level; self.cancel=cancel
        self.frames=queue.Queue(maxsize=50); self.done=threading.Event()
        self.raw=''; self.error=''; self.audio=[]; self.started=0.; self.duration=0.
        self.stream=None; self.recognition=None; self.thread=None; self.closed=False
        self.pending='';self.recorded_frames=0
        self._lock=threading.RLock();self._start_finished=threading.Event()
        self._stop_finished=threading.Event();self._cleanup_started=False
        self._recognition_stopped=False;self._stopping=False;self._aborted=False
        self._start_claimed=False
        self._asr_slot_held=False
        self._recognition_stop_lock=threading.Lock()
        from .audio_capture import PCMCollector
        self.capture=PCMCollector(cfg,on_level,cancel,defer_delivery=True,on_error=self._capture_failed)
        self.capture.frames=self.frames
        if cfg.get('save_audio'):self.audio=self.capture._pcm

    @property
    def error(self):return self._error or (self.capture.error if hasattr(self,'capture') else '')
    @error.setter
    def error(self,value):self._error=value
    @property
    def duration(self):return self.capture.duration if hasattr(self,'capture') and not self.cfg.get('demo') else self._duration
    @duration.setter
    def duration(self,value):self._duration=value
    @property
    def recorded_frames(self):return self.capture.recorded_frames if hasattr(self,'capture') else self._recorded_frames
    @recorded_frames.setter
    def recorded_frames(self,value):self._recorded_frames=value

    def _capture_failed(self,message):
        with self._lock:
            if self.cancel.is_set():return
            if not self._error:self._error=message
            self.closed=True;self.raw+=self.pending;self.pending=''
        self.done.set()

    def start(self):
        with self._lock:
            if self._start_claimed:raise RuntimeError('The recorder has already been started.')
            self._start_claimed=True
        try:self._start()
        except BaseException:
            self.capture.abort();self._schedule_cleanup()
            raise
        finally:self._start_finished.set()

    def _start(self):
        if self.cancel.is_set():raise InterruptedError()
        if self.cfg['demo']:
            self.started=time.monotonic();return
        from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult
        owner=self
        class Callback(RecognitionCallback):
            def on_event(self,result):
                if owner.cancel.is_set():return
                sentence=result.get_sentence()
                if not isinstance(sentence,dict): return
                value=sentence.get('text','')
                if value:
                    with owner._lock:
                        if owner.cancel.is_set() or owner.error:return
                        if RecognitionResult.is_sentence_end(sentence): owner.raw += value; owner.pending=''
                        else: owner.pending=value
                        preview=owner.raw+owner.pending
                    if not owner.cancel.is_set():owner.partial(preview)
            def on_error(self,message):
                if not owner.cancel.is_set():owner.error='ASR service failed ('+str(getattr(message,'code','unknown error'))+').'
                owner.done.set()
            def on_complete(self):
                if not owner._stopping and not owner.cancel.is_set():owner.error='The ASR session ended unexpectedly. Your original text is preserved.'
                owner.done.set()
            def on_close(self):
                if not owner.done.is_set() and not owner._stopping and not owner.cancel.is_set():owner.error='The ASR connection closed unexpectedly. Your original text is preserved.'
                owner.done.set()
        self.pending=''
        key=credential('asr')
        if not key: raise RuntimeError('No Bailian ASR API key is configured. Save a key in Settings or enable demo mode.')
        self.capture.start();self.started=self.capture.started
        if self.cancel.is_set():raise InterruptedError()
        deadline=time.monotonic()+10
        while not _ASR_SLOTS.acquire(timeout=.05):
            if self.cancel.is_set():raise InterruptedError()
            if time.monotonic()>=deadline:raise RuntimeError('Previous ASR connections are still finishing. Try again shortly.')
        self._asr_slot_held=True
        if self.cancel.is_set():raise InterruptedError()
        params=dict(model=self.cfg['asr_model'], format='pcm', sample_rate=16000, callback=Callback(), heartbeat=True,api_key=key,base_address=self.cfg['asr_url'],request_timeout=10)
        if self.cfg['vocabulary_id']: params['vocabulary_id']=self.cfg['vocabulary_id']
        self.recognition=Recognition(**params)
        self.sdk_buffer=_install_asr_buffer(self.recognition)
        context={}
        if self.cfg['hotwords'] and self.cfg['asr_model'] in ('fun-asr-realtime','fun-asr-realtime-2025-11-07'):
            context={'raw_input':{'context':[{'role':'user','content':[{'type':'input_text','text':self.cfg['hotwords'][:400]}]}]}}
        self.recognition.start(**context)
        if self.cancel.is_set():raise InterruptedError()
        if self.error:raise RuntimeError(self.error)
        self.capture.check()
        self.capture.activate(self._send_frame)
        self.thread=self.capture._worker

    def _send_frame(self,data):
        if self.cancel.is_set():raise InterruptedError()
        try:
            if self.recognition._stream_data is not self.sdk_buffer:
                raise RuntimeError('ASR buffer changed unexpectedly.')
            self.recognition.send_audio_frame(data)
        except queue.Full:
            self._capture_failed('The ASR network queue overflowed. Recording stopped; your original text is preserved.')
            raise RuntimeError('The ASR network queue overflowed.') from None
        except Exception:
            if not self.cancel.is_set():self._capture_failed('Could not send audio to ASR. Check your connection.')
            raise RuntimeError('Could not send audio to ASR.') from None

    def stop(self):
        with self._lock:
            if self._stopping:
                stopping=True
            else:self._stopping=True;stopping=False
        if stopping:
            if not self._stop_finished.wait(20):raise RuntimeError('ASR completion timed out. Your original text is preserved.')
            if self.error:raise RuntimeError(self.error)
            if self.cancel.is_set():raise InterruptedError()
            return self.raw
        try:return self._stop()
        except InterruptedError:
            self.capture.abort();self._schedule_cleanup()
            raise
        except Exception as exc:
            if not self.error:
                self.error=str(exc) if isinstance(exc,RuntimeError) else 'Could not finish ASR recording. Your original text is preserved.'
            self.capture.abort();self._schedule_cleanup()
            raise RuntimeError(self.error) from None
        finally:self._stop_finished.set()

    def request_stop(self):
        if not self.cfg.get('demo'):self.capture.request_stop()

    def _stop(self):
        if self.cancel.is_set():raise InterruptedError()
        if not self.cfg['demo']:self.capture.request_stop()
        if not self._start_finished.wait(10):raise RuntimeError('ASR startup timed out.')
        self.duration=(max(0,time.monotonic()-self.started) if self.cfg['demo'] else self.recorded_frames/16000)
        if self.cfg['demo']:
            if self.cancel.wait(.25):raise InterruptedError()
            self.raw=DEMO_TEXT; self.partial(self.raw); return self.raw
        try:pcm=self.capture.stop()
        except RuntimeError:
            if self.error:raise RuntimeError(self.error) from None
            raise
        self.closed=True
        from .audio_quality import require_speech
        require_speech(pcm,self.cfg)  # Streaming PCM was sent unchanged.
        if self.cancel.is_set():raise InterruptedError()
        if self.error: raise RuntimeError(self.error)
        stopping=threading.Event()
        def finish():
            try:self._stop_recognition()
            except Exception:self.error='Could not finish the ASR request.'
            finally:stopping.set()
        threading.Thread(target=finish,daemon=True).start()
        if not stopping.wait(20):raise RuntimeError('ASR completion timed out. Your original text is preserved.')
        if self.cancel.is_set():raise InterruptedError()
        if self.error: raise RuntimeError(self.error)
        if not self.raw.strip(): raise RuntimeError('No speech was recognized. Nothing was inserted.')
        return self.raw

    def abort(self):
        # Nonblocking for the Qt thread. Cleanup waits until startup stops
        # publishing resources, so abort never races Recognition.start().
        self.cancel.set();self.capture.abort()
        with self._lock:
            self.closed=True;self._aborted=True
            self.raw+=self.pending;self.pending=''
            self.duration=(max(0,time.monotonic()-self.started) if self.cfg['demo'] and self.started else self.recorded_frames/16000)
            if not self._start_claimed:self._start_finished.set()
        self._schedule_cleanup()

    def _schedule_cleanup(self):
        with self._lock:
            if self._cleanup_started:return
            self._cleanup_started=True
        def cleanup():
            self._start_finished.wait()
            with self._lock:stream=self.stream;self.stream=None
            if stream:
                try:stream.abort();stream.close()
                except Exception:pass
            try:self._stop_recognition()
            except Exception:pass
        threading.Thread(target=cleanup,name='MurMur-audio-cleanup',daemon=True).start()

    def _stop_recognition(self):
        with self._recognition_stop_lock:
            if self._recognition_stopped:return
            self._recognition_stopped=True
            try:
                if self.recognition:self.recognition.stop()
            finally:
                # SDK stop can raise when its worker has already reported an
                # error. Hold the connection slot until that worker exits, so
                # repeated cancel/retry cannot accumulate network workers.
                worker=getattr(self.recognition,'_worker',None)
                if isinstance(worker,threading.Thread) and worker.is_alive():
                    def release_later():worker.join();self._release_asr_slot()
                    threading.Thread(target=release_later,name='MurMur-ASR-retire',daemon=True).start()
                else:self._release_asr_slot()

    def _release_asr_slot(self):
        with self._lock:
            if not self._asr_slot_held:return
            self._asr_slot_held=False
        _ASR_SLOTS.release()

    def save_audio(self,path):
        if not self.audio: return ''
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        with wave.open(str(path),'wb') as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(16000); f.writeframes(b''.join(self.audio))
        return str(path)

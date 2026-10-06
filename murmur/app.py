from .storage import profile_thread
import argparse
import copy
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass,field
from pathlib import Path
from PySide6.QtCore import QObject,Signal,QTimer,Qt,QEventLoop
from PySide6.QtWidgets import QApplication,QSystemTrayIcon,QMenu,QMessageBox,QDialog
from .storage import Store,credential,credential_lock,PRICE_KEYS
from .hotkeys import Hotkeys
from .providers import make_recorder as Recorder,transform,ask,AskResult
from .local_llm import auto_enabled
from .ui import Bubble,ResultBubble,Preview,STYLE,icon
from .dashboard import MainWindow
from .version import __version__
from . import windows
from .result_review import ReviewAssessment
from .console import event,configure,banner

@dataclass
class Session:
    mode:str
    cfg:dict
    target:object
    id:str=field(default_factory=lambda:uuid.uuid4().hex)
    cancel:threading.Event=field(default_factory=threading.Event)
    recorder:object=None
    raw:str=''
    phase:str='启动'
    focus_changed:bool=False
    stopped:float=0.
    duration:float=0.
    instruction:bool=False
    assistant:bool=False
    context:object=None
    input_epoch:int=0
    gesture:int=0
    hook_epoch:int=0
    hook_cancel_epoch:int=0
    editor_context:str='selection'
    steps:tuple=()
    completed_steps:int=0
    transcript_complete:bool=False

class Bridge(QObject):
    message=Signal(str,str,object)
    startup_status=Signal(str,str,object)
    model_status=Signal(str,bool)
    service_checked=Signal(str,str,object)
    usage_received=Signal(object)

class Controller(QObject):
    def __init__(self,app,store,listen=True):
        windows.prepare_text_context()
        super().__init__();self.app=app;self.store=store;self.session=None;self.pending=False;self.pending_generation=0;self.selection_target=None;self.selection_original='';self.selection_bookmark=None;self.clip_tx=None;self.capture_busy=False;self.capture_generation=0;self.capture_tx=None;self.input_epoch=0
        self.window=MainWindow(store);self.bubble=Bubble(store.config);self.result_bubble=ResultBubble(store.config);self.preview=Preview(self.window);self.result_context=None
        self.delivery=None
        self.result_bubble.edit_requested.connect(self.edit_result)
        self.bridge=Bridge();self.bridge.message.connect(self.receive)
        self.bridge.usage_received.connect(self.record_usage)
        self.model_cancel=threading.Event();self.model_busy=False;self.quitting=False;self.service_tests={}
        self.startup_busy=False;self.startup_error='';self.startup_id='';self.startup_cancel=threading.Event()
        self.warm_microphone=None
        self.startup_timer=QTimer(self);self.startup_timer.setInterval(150);self.startup_timer.timeout.connect(self.startup_tick)
        self.bridge.startup_status.connect(self.startup_status)
        self.bridge.model_status.connect(self.model_status)
        self.bridge.service_checked.connect(self.service_checked)
        self.window.service_test.connect(self.test_service)
        self.window.install_offline.connect(self.install_offline)
        self.window.record.connect(self.toggle);self.window.translate.connect(lambda:self.toggle('翻译'));self.window.ask.connect(self.start_ask);self.window.preview.connect(self.open_preview);self.window.save_settings.connect(self.save_settings)
        self.window.cancel.connect(self.cancel)
        self.bubble.toggle.connect(self.toggle);self.bubble.ask.connect(self.start_ask);self.bubble.cancel.connect(self.cancel);self.bubble.open_main.connect(self.show_main)
        self.preview.submit.connect(self.edit);self.preview.replace.connect(self.replace);self.preview.voice.connect(lambda:self.toggle('指令'));self.preview.cancel.connect(self.cancel)
        self.keys=Hotkeys(store.config);self.keys.gesture.connect(self.hotkey);self.keys.diagnostic.connect(self.window.key_status.setText);self.keys.physical_input.connect(self.physical_input)
        if listen:
            try:self.keys.start()
            except Exception:
                event('hotkeys','Global input monitoring unavailable; results remain in Preview',level='WARNING')
                try:self.keys.stop()
                except Exception:pass
                self.window.key_status.setText('Global input monitoring is unavailable. Results stay in Preview; restart MurMur to retry.')
        self.tray=QSystemTrayIcon(icon(),self);menu=QMenu();menu.addAction('Open MurMur',self.show_main);menu.addAction('Start / stop dictation',self.toggle);menu.addAction('Cancel',self.cancel);menu.addSeparator();menu.addAction('Quit MurMur',lambda checked=False:self.quit());self.tray.setContextMenu(menu);self.tray.activated.connect(lambda reason:self.show_main() if reason==QSystemTrayIcon.DoubleClick else None);self.tray.show()
        self.monitor=QTimer(self);self.monitor.timeout.connect(self.check_focus);self.monitor.start(75)
        self.bubble.position();self.bubble.state('待机',self.shortcut_hint(),store.config['demo'])
        self.sync_controls()
        event('hotkeys','Global monitoring %s','enabled' if listen and self.keys.monitoring else 'disabled',level='DEBUG')
        try:event('usage','Cumulative local LLM tokens: %s',self.store.usage_totals()['local_tokens'])
        except (OSError,AttributeError):pass
    def shortcut_hint(self):
        names={'right_alt':'Right Alt','f8':'F8','f9':'F9','disabled':'Capsule'}
        hint=names.get(self.store.config['dictation_key'],'Right Alt')+' · '+('press to start / stop' if self.store.config['trigger']=='toggle' else 'hold to speak')
        ask_key=self.store.config.get('ask_key','right_alt+space')
        if ask_key!='disabled':hint+=' · Ask: '+('Right Alt + Space' if ask_key=='right_alt+space' else 'Ctrl + Shift + A')
        return hint
    def startup_blocked(self):
        return self.startup_busy or bool(self.startup_error)
    def preload_speech(self):
        """Prepare the selected local recognizer and optional persistent microphone."""
        if self.quitting or self.startup_busy:return
        cfg=copy.deepcopy(self.store.config)
        event('speech','Preparing speech input | backend=%s | engine=%s | acceleration=%s',cfg.get('asr_backend'),cfg.get('offline_engine'),cfg.get('offline_acceleration'))
        self.window._runtime_asr_ready=False
        self.window.config_dots['asr'].set_state('pending','Preparing selected speech input…')
        self.startup_error=''
        self.result_bubble.hide()
        old_microphone=self.warm_microphone;self.warm_microphone=None
        if cfg.get('demo') or (cfg.get('asr_backend')!='offline' and not cfg.get('audio_warm_enabled',True)):
            if old_microphone:old_microphone.request_close()
            event('speech','Ready to record | %s','demo mode' if cfg.get('demo') else 'microphone opens on demand')
            self.window.home_status.clear();return
        self.startup_busy=True;self.startup_id=uuid.uuid4().hex;ident=self.startup_id
        self.startup_cancel=threading.Event();cancel=self.startup_cancel
        self.startup_started=time.monotonic();self.startup_fraction=5
        self.startup_stage=''
        self.window.setEnabled(False);self.preview.setEnabled(False);self.result_bubble.hide()
        self.window.home_status.clear()
        self.bubble.set_session_kind('');self.bubble.loading_progress(5,'Checking model files')
        self.startup_timer.start()
        def work():
            microphone=None
            try:
                if old_microphone:old_microphone.close()
                if cfg.get('asr_backend')=='offline':
                    from .offline import model_paths,load_recognizer
                    model_paths(cfg)
                    self.bridge.startup_status.emit(ident,'loading',None)
                    load_recognizer(cfg,cancel)
                if cfg.get('audio_warm_enabled',True):
                    from .warm_microphone import WarmMicrophone
                    self.bridge.startup_status.emit(ident,'microphone',None)
                    microphone=WarmMicrophone(cfg);microphone.start(cancel)
                    if cancel.is_set():microphone.close();return
                    self.warm_microphone=microphone
                if not cancel.is_set():self.bridge.startup_status.emit(ident,'ready',None)
            except InterruptedError:
                if microphone:microphone.close()
            except Exception as exc:
                if microphone:microphone.close()
                if not cancel.is_set():self.bridge.startup_status.emit(ident,'error',str(exc))
            finally:
                if cancel.is_set() and microphone:
                    microphone.close()
                    if self.warm_microphone is microphone:self.warm_microphone=None
        profile_thread(target=work,name='MurMur-startup-ASR',daemon=True).start()
    def startup_tick(self):
        if not self.startup_busy:return
        import math
        elapsed=max(0,time.monotonic()-self.startup_started)
        self.startup_fraction=max(self.startup_fraction,min(95,int(15+80*(1-math.exp(-elapsed/18)))))
        detail='Preparing microphone standby' if getattr(self,'startup_stage','')=='microphone' else 'Loading selected speech model · estimated progress'
        self.bubble.loading_progress(self.startup_fraction,detail)
    def startup_status(self,ident,stage,payload):
        if self.quitting or ident!=self.startup_id or not self.startup_busy:return
        event('startup','Speech initialization stage: %s',stage,level='DEBUG')
        if stage=='microphone':
            self.startup_stage=stage;self.startup_fraction=max(90,self.startup_fraction)
            self.bubble.loading_progress(self.startup_fraction,'Preparing microphone standby');return
        if stage=='loading':
            self.startup_fraction=max(15,self.startup_fraction)
            self.bubble.loading_progress(self.startup_fraction,'Loading selected speech model · estimated progress');return
        if stage not in ('ready','error'):return
        self.startup_timer.stop()
        if stage=='ready':
            event('speech','Speech input ready | initialization %.2fs',time.monotonic()-self.startup_started)
            if self.store.config.get('asr_backend')=='offline':self.window.set_speech_readiness(True)
            self.bubble.loading_progress(100,'Speech model ready')
            QTimer.singleShot(400,lambda:self.finish_startup(ident))
        else:
            event('speech','Speech initialization failed; details are shown in the application',level='ERROR')
            self.window.set_speech_readiness(False)
            self.startup_error=str(payload);self.finish_startup(ident)
            self.window.settings_status.setText('Speech setup failed. Save corrected settings to retry.')
            self.result_bubble.show_error(self.startup_error,status='Speech input · Setup required',source=self.bubble)
    def finish_startup(self,ident):
        if self.quitting or ident!=self.startup_id:return
        self.startup_busy=False;self.window.setEnabled(True);self.preview.setEnabled(True)
        self.sync_controls()
        if self.startup_error:
            self.window.set_session_state('loading')
            self.window.home_status.setText('Speech input unavailable · open Settings to fix it')
        else:self.window.home_status.clear()
        self.bubble.state('待机',self.shortcut_hint(),self.store.config['demo'])
    def sync_controls(self):
        if self.startup_blocked():
            self.window.set_session_state('loading');self.preview.set_session_state('整理',None);return
        phase=self.session.phase if self.session else None
        mode=self.session.mode if self.session else None
        self.bubble.set_session_kind('Ask Anything' if self.session and self.session.assistant else 'Translation' if mode=='翻译' else '')
        self.window.set_session_state(phase,mode)
        self.preview.set_session_state(phase,mode)
    @staticmethod
    def processing_step(mode):
        return {'听写':'Polish','翻译':'Translate','润色':'Refine','总结':'Summarize','扩写':'Expand','自定义':'Edit','随便问':'Respond'}.get(mode,'Edit')
    def configure_progress(self,s,voice=True):
        if not voice:s.steps=(self.processing_step(s.mode),)
        elif s.instruction or (s.mode=='听写' and not s.cfg['polish']):s.steps=('Transcribe',)
        else:s.steps=('Transcribe','Respond' if s.assistant else self.processing_step(s.mode))
        s.completed_steps=0
    def update_progress(self,s,complete=False):
        if self.session is not s or s.cancel.is_set() or self.quitting:return
        if not s.steps:self.configure_progress(s)
        if complete:s.completed_steps=len(s.steps)
        step=s.steps[min(s.completed_steps,len(s.steps)-1)]
        self.bubble.set_progress(step,s.completed_steps,len(s.steps))
    def show_main(self):self.window.show();self.window.raise_();self.window.activateWindow()
    def record_usage(self,usage):
        if self.quitting:return
        try:
            recorded=self.store.record_usage(usage);self.window.refresh_token_insights()
            if recorded and usage.get('local') is True:
                import json
                counts=lambda name:'unknown' if usage.get(name) is None else str(usage[name])
                model=json.dumps(str(usage.get('model','')),ensure_ascii=True)
                total=self.store.usage_totals()['local_tokens']
                try:event('usage',f'Local LLM {model} | input={counts("input_tokens")} output={counts("output_tokens")} total={counts("total_tokens")} | cumulative local tokens={total}')
                except (OSError,AttributeError):pass
        except Exception:
            event('usage','Usage could not be saved',level='WARNING')
            self.window.settings_status.setText('Usage could not be saved. Your text is preserved.')
    def edit_result(self,text):
        if self.startup_blocked():return
        if self.session:return
        raw=self.result_context[0] if self.result_context else text
        assistant=bool(self.result_context and len(self.result_context)>2)
        if assistant and self.result_context[2]:raw='Voice request:\n'+raw+'\n\nSelected source:\n'+self.result_context[2]
        self.result_bubble.hide();self.preview.show_text(raw,text,'Edit your result, then copy the revised text.',False,assistant=assistant,result_edit=True)
    @staticmethod
    def service_snapshot(kind,cfg,secrets):
        import hashlib,json
        keys=('asr_backend','asr_model','asr_url','vocabulary_id','offline_engine','offline_model_dir','offline_language','offline_threads','offline_acceleration','ali_nls_url','asr_http_url','asr_http_model','asr_http_language','asr_http_timeout') if kind=='asr' else ('llm_url','llm_model','ollama','ollama_auto',*PRICE_KEYS)
        if kind=='ask':keys=('ask_llm_url','ask_llm_model')
        names=('asr','ali_appkey','ali_token','asr_openai_key','asr_groq_key','asr_http_key') if kind=='asr' else ('ask_llm',) if kind=='ask' else ('llm',)
        # Only a digest is retained for stale-result checks. Keys remain in the
        # worker's in-memory input and never enter diagnostics or storage.
        payload=[{key:cfg.get(key) for key in keys},{name:secrets.get(name,'') for name in names}]
        return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=True).encode()).hexdigest()
    def test_service(self,kind,cfg,secrets):
        if self.startup_busy:return
        if self.quitting or kind not in ('asr','llm','ask') or kind in self.service_tests:return
        if self.session:
            self.window.set_service_test_state(kind,False,'Finish the current recording first.','',False);return
        ident=uuid.uuid4().hex;cancel=threading.Event();cfg=copy.deepcopy(cfg);secrets=dict(secrets)
        self.service_tests[kind]=(ident,cancel,self.service_snapshot(kind,cfg,secrets))
        self.window.set_service_test_state(kind,True)
        def work():
            try:
                from .service_checks import check_service
                result=check_service(kind,cfg,secrets,cancel,usage_sink=self.bridge.usage_received.emit)
            except InterruptedError:
                result={'success':False,'summary':'Cancelled','detail':'Connection check cancelled.'}
            except Exception:
                result={'success':False,'summary':'Connection check failed.','detail':'Try again. No microphone audio was recorded.'}
            self.bridge.service_checked.emit(kind,ident,result)
        profile_thread(target=work,name='MurMur-service-check-'+kind,daemon=True).start()
    def service_checked(self,kind,ident,result):
        active=self.service_tests.get(kind)
        if self.quitting or not active or active[0]!=ident:return
        self.service_tests.pop(kind)
        cfg,secrets=self.window.service_test_values()
        if self.service_snapshot(kind,cfg,secrets)!=active[2]:
            self.window.set_service_test_state(kind,False,'Settings changed. Test again.','The check used earlier values; this configuration has not been verified.',None);return
        self.window.set_service_model_metadata(kind,result)
        event('services','%s connection check: %s',kind,'passed' if result['success'] else 'failed',level='INFO' if result['success'] else 'WARNING')
        self.window.set_service_test_state(kind,False,result['summary'],result.get('detail',''),bool(result['success']))
    def model_status(self,text,finished):
        if self.quitting:return
        if finished:
            self.model_busy=False
            self.window.set_offline_download_state(False)
        self.window.offline_status.setText(text)
    def install_offline(self):
        if self.startup_busy:return
        if self.model_busy or self.quitting:return
        engine=self.window.fields['offline_engine'].currentData()
        acceleration=self.window.fields['offline_acceleration'].currentData()
        folder=self.window.fields['offline_model_dir'].text().strip()
        if not folder:self.window.offline_status.setText('Choose a model folder first.');return
        self.model_busy=True;self.model_cancel.clear();self.window.set_offline_download_state(True)
        def work():
            try:
                from .models import install_model
                if acceleration=='cpu':
                    install_model(engine,folder,lambda text:self.bridge.model_status.emit(text,False),self.model_cancel)
                else:
                    install_model(engine,folder,lambda text:self.bridge.model_status.emit(text,False),self.model_cancel,acceleration=acceleration)
                self.bridge.model_status.emit('Model files downloaded and verified. Save changes to use this folder.',True)
            except InterruptedError:self.bridge.model_status.emit('Download cancelled.',True)
            except Exception:self.bridge.model_status.emit('Download failed. Check your connection and try again.',True)
        profile_thread(target=work,name='MurMur-model-download',daemon=True).start()
    def check_focus(self):
        if self.session and self.session.target and (not self.keys.monitoring or not windows.valid(self.session.target)):self.session.focus_changed=True
        if self.session and self.session.phase=='录音' and self.session.recorder:
            s=self.session;elapsed=max(0,time.monotonic()-s.recorder.started)
            self.bubble.state('录音',f'{int(elapsed)//60:02d}:{int(elapsed)%60:02d} · '+('Demo recording' if s.cfg['demo'] else 'Listening'),s.cfg['demo'])
            if s.recorder.error:self.receive(s.id,'error',s.recorder.error)
    def hotkey(self,event,gesture=0):
        if self.startup_blocked():return
        if event=='pending':
            self.pending=True;self.pending_generation+=1;generation=self.pending_generation
            self.pending_gesture=gesture
            self.pending_allowed=self.store.config['dictation_key']!='disabled' and (not gesture or self.store.config['dictation_key']=='right_alt')
            # Wait for release before stopping an existing session: Space may
            # still turn this Right Alt press into an Ask gesture.
            if not self.session and self.pending_allowed:QTimer.singleShot(130,lambda:self.begin_pending(generation))
        elif event=='release':
            if self.pending:
                self.pending=False;self.pending_generation+=1
                if self.session and self.session.assistant:self.stop()
                elif self.pending_allowed and self.store.config['trigger']=='toggle':self.toggle()
            elif self.store.config['trigger']=='hold' and self.session and not self.session.assistant and self.session.phase in ('启动','录音'):self.stop()
        elif event=='ask':
            self.pending=False;self.pending_generation+=1
            self.start_ask(gesture)
        elif event=='ask_release':return
        elif event=='translation':
            self.pending=False
            if self.session and self.session.mode=='听写':self.cancel()
            self.toggle('翻译')
        elif event=='selection':
            self.pending=False;self.cancel();generation=self.capture_generation;QTimer.singleShot(180,lambda:self.capture_selection() if generation==self.capture_generation else None)
        elif event in ('cancel','altgr'):self.pending=False;self.cancel()
    def begin_pending(self,generation=None):
        if self.pending and (generation is None or generation==self.pending_generation):
            self.pending=False
            if getattr(self,'pending_allowed',False):
                self.toggle()
                if self.session:self.session.gesture=getattr(self,'pending_gesture',0)
    def start_ask(self,gesture=0):
        if self.startup_blocked():return
        if self.capture_busy:return
        s=self.session
        if s and s.assistant:
            if s.phase in ('启动','录音'):self.stop()
            return
        if s and (s.mode!='听写' or s.phase not in ('启动','录音')):return
        if 'ask' in self.service_tests or 'asr' in self.service_tests:
            self.window.home_status.setText('Finish the speech or Ask Anything connection check before recording.');return
        cfg=copy.deepcopy(self.store.config)
        if not cfg['demo']:
            try:
                from .assistant import ask_config
                ask_config(cfg)
                try:key_present=bool(credential('ask_llm'))
                except Exception:raise RuntimeError('Ask Anything credentials could not be read. Check Settings → Services.') from None
                if not key_present:raise RuntimeError('Set a separate Ask Anything API key in Settings → Services, then save.')
            except Exception as exc:
                if s:self.cancel()
                self.result_context=('', '', '', 'answer')
                self.result_bubble.show_error(str(exc),status='Ask Anything · Setup required',source=self.bubble)
                return
        if s:
            if gesture and s.gesture==gesture:
                guard=self.keys.input_guard
                s.assistant=True;s.mode='随便问';s.context=windows.text_context(s.target);s.input_epoch=self.input_epoch
                s.hook_epoch,s.hook_cancel_epoch=guard
                s.focus_changed=s.focus_changed or guard!=self.keys.input_guard
                self.configure_progress(s)
                self.sync_controls();return
            self.cancel()
        self.toggle('随便问')
    def toggle(self,mode='听写'):
        if self.startup_blocked():return
        if self.capture_busy:return
        if self.session:
            if self.session.phase in ('启动','录音'):self.stop()
            return
        if 'asr' in self.service_tests:
            self.window.home_status.setText('Finish the speech recognition check before recording.')
            self.bubble.state('待机','Speech check running…',self.store.config['demo']);return
        guard=self.keys.input_guard
        self.clear_delivery()
        t=windows.target();t=None if windows.own_target(t) else t
        self.result_bubble.hide()
        assistant=mode=='随便问'
        context=windows.text_context(t) if assistant else None
        s=Session(mode,copy.deepcopy(self.store.config),t,instruction=mode=='指令',assistant=assistant,context=context,input_epoch=self.input_epoch);self.session=s
        event('session','Starting %s | demo=%s',mode,s.cfg.get('demo',False))
        s.cfg['_data_dir']=str(self.store.root)
        if self.warm_microphone is not None and not s.cfg.get('demo'):
            s.cfg['_warm_microphone']=self.warm_microphone
        s.hook_epoch,s.hook_cancel_epoch=guard
        self.configure_progress(s)
        if assistant:s.focus_changed=guard!=self.keys.input_guard
        self.sync_controls()
        self.bubble.state('启动','Connecting…' if not s.cfg['demo'] else 'Starting demo recording',s.cfg['demo'])
        def work():
            try:
                rec=Recorder(s.cfg,lambda text:self.bridge.message.emit(s.id,'partial',text),lambda level:self.bridge.message.emit(s.id,'level',level),s.cancel);s.recorder=rec
                if s.phase=='等待停止':
                    request_stop=getattr(rec,'request_stop',None)
                    if request_stop:request_stop()
                rec.start()
                if s.cancel.is_set():rec.abort();return
                self.bridge.message.emit(s.id,'started',None)
            except Exception as e:
                if s.recorder:s.recorder.abort()
                self.bridge.message.emit(s.id,'error',str(e))
        profile_thread(target=work,daemon=True).start()
    def stop(self):
        s=self.session
        if not s or s.phase not in ('启动','录音'):return
        event('session','Recording stop requested | phase=%s',s.phase,level='DEBUG')
        if s.phase=='启动':
            s.phase='等待停止'
            request_stop=getattr(s.recorder,'request_stop',None)
            if request_stop:request_stop()
            self.bubble.state('等待停止','Finishing startup',s.cfg['demo']);self.sync_controls();return
        s.phase='识别';s.stopped=time.monotonic();self.bubble.state('识别','Finishing transcription',s.cfg['demo'])
        self.update_progress(s)
        self.sync_controls()
        def work():
            try:
                raw=s.recorder.stop();s.duration=s.recorder.duration;s.raw=raw
                if s.cancel.is_set():return
                if not isinstance(raw,str) or not raw.strip():raise RuntimeError('No speech was recognized. Try recording again.')
                self.bridge.message.emit(s.id,'recognized',raw)
                if s.assistant:
                    self.bridge.message.emit(s.id,'phase','整理')
                    final=ask(raw,s.context.text if s.context else '',s.cfg,cancel=s.cancel,usage_sink=self.bridge.usage_received.emit)
                elif s.instruction:final=raw
                else:
                    if s.cfg['polish'] or s.mode!='听写':self.bridge.message.emit(s.id,'phase','整理')
                    final=transform(raw,s.mode,s.cfg,cancel=s.cancel,usage_sink=self.bridge.usage_received.emit)
                self.bridge.message.emit(s.id,'result',final)
            except InterruptedError:pass
            except Exception as e:self.bridge.message.emit(s.id,'error',str(e))
        profile_thread(target=work,daemon=True).start()
    def receive(self,ident,event,payload):
        s=self.session
        if not s or s.id!=ident or (s.cancel.is_set() and event!='error'):return
        if event not in ('partial','level'):
            from .console import event as console_event
            console_event('session','Stage: %s',event,level='ERROR' if event=='error' else 'INFO')
        if s.assistant and self.keys.cancel_generation!=s.hook_cancel_epoch:
            self.cancel();return
        if event=='started':
            if s.phase not in ('启动','等待停止'):return
            wait=s.phase=='等待停止';s.phase='录音'
            if wait:self.stop()
            else:
                self.bubble.state('录音','Right Alt to finish Ask Anything' if s.assistant else 'Release to finish' if s.cfg['trigger']=='hold' else 'Click again to finish',s.cfg['demo']);self.sync_controls()
        elif event=='partial':
            # A recorder callback already queued at stop can arrive after the
            # complete transcript. Preserve that final text for history/recovery.
            if not s.transcript_complete and isinstance(payload,str) and payload.strip():s.raw=payload
        elif event=='level' and s.phase in ('启动','录音','等待停止'):
            if s.phase=='启动' and not s.cfg['demo'] and not self.bubble.wave.active:
                self.bubble.state('录音','Microphone active · preparing speech service',False)
            self.bubble.wave.feed_level(payload)
        elif event=='recognized':
            if s.transcript_complete or not isinstance(payload,str) or not payload.strip():return
            s.transcript_complete=True
            s.raw=payload
            if isinstance(payload,str) and payload.strip():
                if not s.steps:self.configure_progress(s)
                s.completed_steps=max(s.completed_steps,min(1,len(s.steps)-1))
                self.update_progress(s)
        elif event=='phase':
            s.phase=payload;self.sync_controls()
            self.bubble.state(payload,self.processing_step(s.mode),s.cfg['demo']);self.update_progress(s)
        elif event in ('result','error'):self.finish(s,payload,event=='error')
    def _save_history(self,*args,**kwargs):
        import sqlite3
        try:
            self.store.add(*args,**kwargs)
            return True
        except (sqlite3.Error,OSError):
            db=getattr(self.store,'db',None)
            if db is not None:
                try:db.rollback()
                except (sqlite3.Error,OSError):pass
            self.window.settings_status.setText('History could not be saved. Your text is still available.')
            return False
    def finish(self,s,payload,error=False):
        if s.assistant:
            self.finish_ask(s,payload,error);return
        if not error and (not isinstance(payload,str) or not payload.strip()):
            payload='The model returned an empty or invalid result. Your original text is preserved.';error=True
        event('session','%s | mode=%s | recording=%.2fs','Failed' if error else 'Completed',s.mode,s.duration,level='ERROR' if error else 'INFO')
        if not error:self.update_progress(s,complete=True)
        if s.recorder:
            if error:s.recorder.abort()
            s.duration=s.recorder.duration
        # Before final recognition, abort freezes the latest partial sentence.
        # Afterwards, the complete transcript remains the authoritative original.
        raw=s.raw if s.transcript_complete else (s.recorder.raw if error and s.recorder else '') or s.raw or (s.recorder.raw if s.recorder else '')
        final=raw if error else payload
        latency=max(0,time.monotonic()-(s.stopped or time.monotonic()))
        audio=''
        if s.recorder and s.cfg['save_audio']:
            try:audio=s.recorder.save_audio(self.store.root/'audio'/f'{s.id}.wav')
            except Exception:payload=str(payload)+'; audio could not be saved'
        history_saved=self._save_history(s.id,s.mode,raw,final,s.duration,latency,s.cfg['demo'],payload if error else '',audio)
        history_warning='' if history_saved else ' · History could not be saved'
        editor_flags={'assistant':s.editor_context=='assistant','result_edit':s.editor_context=='result' or s.mode in ('听写','翻译')}
        self.session=None
        if history_saved:self.window.refresh()
        self.sync_controls()
        if s.instruction and not error:
            self.preview.command.setText(final);self.preview.show()
            if not history_saved:self.preview.notice.setText('History could not be saved. Your instruction is ready to submit.')
            self.bubble.state('完成','Instruction ready to submit'+history_warning,s.cfg['demo']);return
        if error:
            if s.recorder:s.recorder.abort()
            message='Processing failed: '+str(payload)+history_warning
            # A background failure must not activate the editor over the
            # original input target. Recovered text is copied only on request.
            self.preview.show_text(raw,final,message,False,show=False,**editor_flags)
            if s.mode in ('听写','翻译') or not self.preview.isVisible():
                self.result_context=(raw,raw)
                self.result_bubble.show_error(str(payload)+history_warning,raw,demo=s.cfg['demo'],status='Processing failed',source=self.bubble)
            self.bubble.state('失败',('Original text preserved' if raw.strip() else 'No transcript captured')+history_warning,s.cfg['demo']);return
        dictation=s.mode in ('听写','翻译')
        if dictation and s.cfg.get('smart_delivery',True):
            self.finish_smart_dictation(s,raw,final,history_saved)
            return
        copied=False
        if dictation and not s.cfg['demo'] and final.strip():
            try:
                self.app.clipboard().setText(str(final))
                copied=self.app.clipboard().text()==str(final)
            except Exception:pass
        if s.mode in ('听写','翻译') and not s.cfg['demo'] and self.keys.monitoring and not s.focus_changed and windows.valid(s.target):
            try:
                self.paste(final,s.target)
                self.result_context=(raw,str(final));self.preview.show_text(raw,str(final),'Paste sent. Review or copy your result.'+history_warning,False,show=False,result_edit=True)
                self.result_bubble.show_result(str(final),status=('Copied · Paste sent' if copied else 'Paste sent')+history_warning,source=self.bubble)
                self.bubble.state('完成','Paste sent · saved in History' if history_saved else 'Paste sent'+history_warning,False);return
            except Exception as e:notice=str(e)
        elif s.cfg['demo']:notice='Demo result · preview only'
        elif s.mode in ('听写','翻译'):
            notice='Input monitoring is unavailable. Copy your result from Preview.' if not self.keys.monitoring else 'The target changed or could not be confirmed. Your result is preserved.'
        else:notice='Preview ready. Replacement requires checking the original selection.'
        notice+=history_warning
        replacement=bool(s.editor_context=='selection' and self.selection_target and self.selection_bookmark and not s.cfg['demo'] and s.mode not in ('听写','翻译'))
        if dictation:
            self.result_context=(raw,str(final))
            self.preview.show_text(raw,str(final),notice,False,show=False,result_edit=True)
            self.result_bubble.show_result(str(final),demo=s.cfg['demo'],status=('Copied' if copied else 'Result ready · Copy to use')+history_warning,source=self.bubble)
        else:self.preview.show_text(raw,final,notice,replacement,**editor_flags)
        self.bubble.state('完成','Result ready'+history_warning,s.cfg['demo'])

    def finish_smart_dictation(self,s,raw,final,history_saved):
        self.clear_delivery()
        warning='' if history_saved else ' · History could not be saved'
        self.result_context=(raw,str(final))
        review=getattr(final,'review',None)
        needs_review=(review.needs_review or not review.assessed) if isinstance(review,ReviewAssessment) else bool(s.mode=='翻译' or s.cfg['polish'])
        if s.cfg['demo']:notice='Demo result · Copy to use'
        elif not self.keys.monitoring:notice='Input monitoring is unavailable · Copy to use'
        elif s.focus_changed or not windows.valid(s.target):notice='The target changed or could not be confirmed · Copy to use'
        elif needs_review:
            spans=', '.join(review.uncertain_spans) if isinstance(review,ReviewAssessment) else ''
            notice='Review wording'+(': '+spans if spans else ' · Check before inserting')
        else:
            epoch=(s.input_epoch,(s.hook_epoch,s.hook_cancel_epoch))
            guard=lambda:not self.quitting and self.session is None and epoch==(self.input_epoch,self.keys.input_guard)
            try:
                receipt=self.paste(str(final),s.target,guard=guard,verify=True)
                if not receipt:raise RuntimeError('Input could not be confirmed · Copy to use')
                self.preview.show_text(raw,str(final),'Checking insertion'+warning,False,show=False,result_edit=True)
                self.result_bubble.hide()
                delivery=(s.id,s.target,receipt,raw,str(final),history_saved)
                self.delivery=delivery
                QTimer.singleShot(150,lambda:self.confirm_delivery(delivery))
                self.bubble.state('完成','Checking insertion'+warning,False)
                return
            except Exception as exc:notice=str(exc)
        self.show_copy_result(raw,str(final),notice+warning,s.cfg['demo'])

    def show_copy_result(self,raw,text,notice,demo=False):
        self.result_context=(raw,text)
        self.preview.show_text(raw,text,notice,False,show=False,result_edit=True)
        self.result_bubble.show_result(text,demo=demo,status=notice,source=self.bubble)
        self.bubble.state('完成','Result ready · Review or copy',demo)

    def confirm_delivery(self,delivery,attempt=0):
        if self.delivery is not delivery or self.quitting or self.session is not None:return
        _,target,receipt,raw,text,history_saved=delivery
        if windows.paste_verified(target,receipt):
            self.delivery=None
            if history_saved:
                self.result_bubble.hide()
                self.bubble.state('完成','Inserted · saved in History',False)
            else:self.show_copy_result(raw,text,'Inserted · History could not be saved')
            return
        if attempt<2 and windows.valid(target):
            QTimer.singleShot(200 if attempt==0 else 400,lambda:self.confirm_delivery(delivery,attempt+1))
            return
        self.clear_delivery()
        warning='' if history_saved else ' · History could not be saved'
        self.show_copy_result(raw,text,'Insertion could not be confirmed · Copy to use'+warning)

    def clear_delivery(self):
        if self.delivery is not None:
            _,target,receipt,*_=self.delivery
            self.delivery=None
            windows.forget_paste(target,receipt)
    def finish_ask(self,s,payload,error=False):
        event('session','Ask Anything %s','failed' if error else 'processing result',level='ERROR' if error else 'INFO')
        if s.recorder:
            if error:s.recorder.abort()
            s.duration=s.recorder.duration
        raw=s.raw if s.transcript_complete else (s.recorder.raw if error and s.recorder else '') or s.raw
        context=s.context.text if s.context else ''
        if not error and (not isinstance(payload,AskResult) or payload.action not in ('replace','insert','answer') or not isinstance(payload.text,str) or not payload.text.strip()):
            payload='The assistant returned an invalid action. Your spoken request is preserved.';error=True
        if not error:self.update_progress(s,complete=True)
        action='answer' if error else payload.action
        final=raw if error else payload.text
        mode='随便问' if error else {'replace':'语音编辑','insert':'起草','answer':'问答'}[action]
        latency=max(0,time.monotonic()-(s.stopped or time.monotonic()))
        audio=''
        if s.recorder and s.cfg['save_audio']:
            try:audio=s.recorder.save_audio(self.store.root/'audio'/f'{s.id}.wav')
            except Exception:pass
        history_saved=self._save_history(s.id,mode,raw,final,s.duration,latency,s.cfg['demo'],str(payload) if error else '',audio,context=context)
        # Retain the session until the final target check and paste complete.
        notice='Answer ready'
        if error:notice='Request failed · spoken request preserved'
        elif s.cfg['demo']:notice='Copy to use'
        elif action!='answer':
            expected='selection' if action=='replace' else 'caret'
            eligible=bool(s.context and s.context.state==expected and self.ask_write_guard(s))
            if eligible:
                try:
                    self.paste(final,s.target,context=s.context,guard=lambda:self.ask_write_guard(s))
                    notice='Replacement paste sent' if action=='replace' else 'Draft paste sent'
                except Exception as exc:notice=str(exc)
            else:notice='Target or selection could not be confirmed · Copy to use'
        if not history_saved:notice+=' · History could not be saved'
        self.session=None
        if history_saved:self.window.refresh()
        self.sync_controls()
        self.result_context=(raw,final,context,action)
        display=final or (str(payload) if error else '')
        summary='Ask Anything · Request failed' if error else 'Ask Anything · Preview only' if action!='answer' and notice not in ('Replacement paste sent','Draft paste sent') else 'Ask Anything · '+notice
        if not history_saved:summary='Ask Anything · History not saved'
        if error:
            self.result_bubble.show_error(str(payload)+(' · History could not be saved' if not history_saved else ''),raw,demo=s.cfg['demo'],status='Ask Anything · '+notice,status_summary=summary,source=self.bubble)
        else:
            self.result_bubble.show_result(display,demo=s.cfg['demo'],status='Ask Anything · '+notice,status_summary=summary,source=self.bubble)
        self.bubble.state('失败' if error else '完成',str(payload) if error else notice,s.cfg['demo'])
    def ask_write_guard(self,s):
        return bool(self.session is s and self.keys.monitoring and not s.focus_changed and s.input_epoch==self.input_epoch and not s.cancel.is_set() and self.keys.input_guard==(s.hook_epoch,s.hook_cancel_epoch))
    def paste(self,text,t,selection=None,context=None,guard=None,verify=False):
        if self.clip_tx:raise RuntimeError('Clipboard operation in progress. Try again shortly.')
        if guard and not guard():raise RuntimeError('Input changed. Copy the result instead.')
        if not text.strip() or not windows.valid(t):raise RuntimeError('The target changed. Your result is preserved.')
        if selection and not windows.selection_matches(t,selection):raise RuntimeError('The original selection changed. Copy the result instead.')
        if context and not windows.context_matches(t,context):raise RuntimeError('The original selection or cursor changed. Copy the result instead.')
        receipt=windows.prepare_paste(t,text) if verify else None
        if verify and not receipt:raise RuntimeError('This input cannot confirm insertion · Copy to use')
        if verify:
            try:
                if guard and not guard():raise RuntimeError('Input changed. Copy the result instead.')
                if not windows.paste_ready(t,receipt):raise RuntimeError('The cursor or input changed · Copy to use')
                if windows.insert_native_edit(t,text,guard=guard,receipt=receipt):return receipt
            except Exception:
                windows.forget_paste(t,receipt);raise
        tx=windows.ClipboardTransaction();tx.write(text)
        try:
            if not windows.valid(t):raise RuntimeError('The target changed.')
            if selection and not windows.selection_matches(t,selection):raise RuntimeError('The original selection changed. Copy the result instead.')
            if context and not windows.context_matches(t,context):raise RuntimeError('The original selection or cursor changed. Copy the result instead.')
            if guard and not guard():raise RuntimeError('Input changed. Copy the result instead.')
            if verify and not windows.paste_ready(t,receipt):raise RuntimeError('The cursor or input changed · Copy to use')
            windows.chord('V')
        except Exception:
            if receipt:windows.forget_paste(t,receipt)
            self.restore_clipboard(tx);raise
        self.clip_tx=tx
        QTimer.singleShot(650,lambda:self.restore_clipboard(tx))
        return receipt
    def restore_clipboard(self,tx,expected=None,attempt=0):
        try:tx.restore(expected)
        except windows.ClipboardBusy:
            if not self.quitting and attempt<3:
                if self.clip_tx is None:self.clip_tx=tx
                QTimer.singleShot(120,lambda:self.restore_clipboard(tx,expected,attempt+1));return
            self.clipboard_restore_failed()
        except Exception:
            self.clipboard_restore_failed()
        if self.clip_tx is tx:self.clip_tx=None
    def clipboard_restore_failed(self):
        message='Clipboard restoration failed. Your result remains available to copy.'
        self.window.home_status.setText(message)
        # The delayed restore belongs to an earlier paste. It must not hide or
        # reset a newer session's live waveform, processing step, or percentage.
        if self.session is None:self.bubble.state('失败',message,self.store.config['demo'])
    def physical_input(self,kind):
        self.input_epoch+=1
        if self.session:self.session.focus_changed=True

    def cancel(self):
        if self.startup_busy and not self.quitting:return
        self.clear_delivery()
        self.pending=False;self.pending_generation+=1;self.capture_generation+=1;self.capture_busy=False
        self.result_bubble.hide()
        if self.capture_tx:self.restore_clipboard(self.capture_tx);self.capture_tx=None
        s=self.session;history_saved=True;raw=''
        if s:
            event('session','Cancelled')
            s.cancel.set()
            if s.recorder:s.recorder.abort();s.duration=s.recorder.duration
            raw=s.raw if s.transcript_complete else (s.recorder.raw if s.recorder else '') or s.raw
            if raw:history_saved=self._save_history(s.id,s.mode,raw,raw,s.duration,0,s.cfg['demo'],'Cancelled by user',context=s.context.text if s.assistant and s.context else '')
        self.session=None
        if s and raw and history_saved:self.window.refresh()
        self.sync_controls()
        if not history_saved:
            message='Cancelled. History could not be saved; copy your text to keep it.'
            assistant=bool(s and s.assistant)
            context=s.context.text if assistant and s.context else ''
            self.result_context=(raw,raw,context,'answer') if assistant else (raw,raw)
            self.preview.show_text(raw,raw,message,False,show=False,assistant=assistant,result_edit=True)
            self.result_bubble.show_error(message,raw,demo=s.cfg['demo'],status='Cancelled · History not saved',source=self.bubble)
        self.bubble.state('待机',('Cancelled' if history_saved else 'Cancelled · History could not be saved') if s else self.shortcut_hint(),self.store.config['demo'])
    def open_preview(self):
        if self.startup_blocked():return
        self.selection_target=None;self.selection_original='';self.selection_bookmark=None;self.preview.show_text('','','Enter text or press Alt+Space to capture a selection.',False)
    def capture_selection(self,replace_text=None):
        if self.startup_blocked():return
        if self.capture_busy:return
        if self.clip_tx:
            self.preview.notice.setText('Clipboard operation in progress. Try again shortly.');self.preview.show();return
        t=self.selection_target if replace_text is not None else windows.target()
        if windows.own_target(t):self.open_preview();self.preview.notice.setText('No external selection could be confirmed. Paste your text here.');return
        if replace_text is not None and not windows.activate(t):self.preview.notice.setText('Could not restore the original target. Copy the result instead.');return
        bookmark=windows.selection_bookmark(t) if replace_text is None else self.selection_bookmark
        if replace_text is not None and (not bookmark or not windows.selection_matches(t,bookmark)):
            self.preview.notice.setText('The original selection position could not be confirmed. Copy the result instead.');self.preview.show();return
        try:
            tx=windows.ClipboardTransaction();tx.write('');windows.chord('C')
        except Exception as e:
            if 'tx' in locals():self.restore_clipboard(tx)
            self.preview.notice.setText(str(e));self.preview.show();return
        self.capture_generation+=1;generation=self.capture_generation;epoch=self.input_epoch
        self.capture_busy=True;self.capture_tx=tx
        import win32clipboard
        def release(expected=None):
            self.restore_clipboard(tx,expected)
            if self.capture_tx is tx:self.capture_tx=None;self.capture_busy=False
        def read(attempt=0):
            if generation!=self.capture_generation:release();return
            current=win32clipboard.GetClipboardSequenceNumber()
            if epoch!=self.input_epoch or not windows.window_valid(t):
                release();self.preview.show();self.preview.notice.setText('The target or selection changed during copy. Try again.');return
            if current==tx.sequence and attempt<10:QTimer.singleShot(50,lambda:read(attempt+1));return
            try:copied=tx.copied(t)
            except windows.ClipboardBusy:
                if attempt<10:QTimer.singleShot(50,lambda:read(attempt+1));return
                release();self.preview.notice.setText('The clipboard is busy. Your selection was not changed; try again.');self.preview.show();return
            except Exception:
                release();self.preview.notice.setText('The clipboard could not be read safely. Try again.');self.preview.show();return
            text=copied[1] if copied else ''
            position_confirmed=bool(bookmark and windows.selection_matches(t,bookmark))
            # Only restore a copied value proven to belong to the captured target.
            # An unrelated clipboard update always remains untouched.
            release(copied[0] if copied else None)
            if replace_text is not None:
                if text and text==self.selection_original and position_confirmed and windows.valid(t):
                    try:self.paste(replace_text,t,bookmark);self.preview.notice.setText('Replacement paste sent.')
                    except Exception as e:self.preview.notice.setText(str(e));self.preview.show()
                else:self.preview.notice.setText('The original selection could not be confirmed. Copy the result instead.');self.preview.show()
            else:
                self.selection_target=t if text else None;self.selection_original=text;self.selection_bookmark=bookmark if position_confirmed else None
                notice=('Selection captured. Choose an action to preview.' if position_confirmed else 'Selection captured. Copy only: its original position could not be confirmed.') if text else 'No text selection detected. Paste or enter text.'
                self.preview.show_text(text,'',notice,bool(text) and not self.store.config['demo'] and position_confirmed and bool(t.uia_id and t.editable))
        QTimer.singleShot(80,read)
    def replace(self,text):
        if self.startup_blocked():return
        if not self.store.config['demo'] and text.strip():self.capture_selection(text)
    def edit(self,raw,mode,instruction):
        if self.startup_blocked():return
        if self.session or not raw.strip():self.preview.notice.setText('Enter text and wait for the current operation to finish.');return
        if mode=='自定义' and not instruction.strip():self.preview.notice.setText('Enter an editing instruction.');return
        s=Session(mode,copy.deepcopy(self.store.config),None,raw=raw,phase='整理',stopped=time.monotonic(),editor_context=self.preview.editor_context);self.session=s;self.sync_controls();self.bubble.state('整理','Preparing preview',s.cfg['demo'])
        s.cfg['_data_dir']=str(self.store.root)
        self.configure_progress(s,voice=False);self.update_progress(s)
        def work():
            try:self.bridge.message.emit(s.id,'result',transform(raw,mode,s.cfg,instruction,s.cancel,usage_sink=self.bridge.usage_received.emit))
            except InterruptedError:pass
            except Exception as e:self.bridge.message.emit(s.id,'error',str(e))
        profile_thread(target=work,daemon=True).start()
    def save_settings(self,values,secrets):
        if self.startup_busy:return
        if self.session:QMessageBox.warning(self.window,'MurMur','Finish the current session before saving settings.');return
        if self.service_tests:
            self.window.settings_status.setText('Wait for the connection check to finish before saving.');return
        microphone_changed=any(values.get(key)!=self.store.config.get(key) for key in ('microphone','audio_warm_enabled','audio_preroll_ms','demo'))
        speech_changed=any(values.get(key)!=self.store.config.get(key) for key in ('asr_backend','offline_engine','offline_model_dir','offline_language','offline_threads','offline_acceleration'))
        from urllib.parse import urlparse
        try:
            import math
            for key in PRICE_KEYS:
                price=values.get(key)
                if price is None or price=='':values[key]=None;continue
                if isinstance(price,bool):raise ValueError('Token prices must be non-negative USD per million tokens.')
                price=float(price)
                if not math.isfinite(price) or not 0<=price<=1000000:raise ValueError('Token prices must be non-negative USD per million tokens.')
                values[key]=price
            if values['translation_key']==values['selection_key']!='disabled':raise ValueError('Translation and selection shortcuts must be different.')
            backend=values.get('asr_backend','offline')
            if backend in ('openai','groq','http_asr'):
                from .cloud_asr import request_settings
                request_settings(values)
            elif backend!='offline':
                endpoint=values.get('ali_nls_url','') if backend=='ali_nls' else values['asr_url']
                if urlparse(endpoint).scheme!='wss':raise ValueError('ASR URL must use wss://.')
            if urlparse(values['llm_url']).scheme not in ('http','https'):raise ValueError('LLM URL must use http:// or https://.')
            from .assistant import ask_config
            ask_config(values)
            if backend=='bailian' and not values['asr_model']:raise ValueError('Speech model cannot be empty.')
            if not values['llm_model'] and not auto_enabled(values):raise ValueError('LLM model cannot be empty.')
            with credential_lock:
                for name,key in secrets.items():
                    if key:
                        credential(name,key)
                        if name=='ali_token':credential('ali_token_expiry','')
            if values['startup']!=self.store.config['startup']:windows.startup(values['startup'])
            self.store.config.update(values);self.store.save();self.store.prune();self.keys.machine.cfg=self.store.config;self.bubble.cfg=self.store.config;self.bubble.position();self.result_bubble.cfg=self.store.config;self.result_bubble.position();self.window.refresh()
            if speech_changed:self.window._runtime_asr_ready=False
            self.window.check_saved_services()
            for field in ('asr_key','llm_key','ask_llm_key','ali_appkey','ali_token','asr_http_key'):
                widget=getattr(self.window,field,None)
                if widget is not None:
                    previous=widget.blockSignals(True)
                    try:widget.clear()
                    finally:widget.blockSignals(previous)
            if hasattr(self.window,'_http_asr_keys'):
                self.window._http_asr_keys={key:'' for key in self.window._http_asr_keys}
            self.bubble.state('待机','Changes saved',values['demo']);self.window.settings_status.setText('Changes saved')
            event('settings','Configuration saved | speech changed=%s | microphone changed=%s',speech_changed,microphone_changed)
            warm=self.warm_microphone
            microphone_unhealthy=warm is not None and (warm.error or warm.closed.is_set() or not getattr(warm.stream,'active',True))
            if self.startup_error or microphone_changed or speech_changed or microphone_unhealthy:self.preload_speech();self.sync_controls()
        except Exception as e:QMessageBox.warning(self.window,'Could not save settings',str(e))
    def quit(self,quit_app=True):
        event('app','Shutting down')
        self.clear_delivery()
        self.quitting=True;self.model_cancel.set()
        self.startup_cancel.set();self.startup_timer.stop();self.startup_id=''
        if self.warm_microphone:self.warm_microphone.request_close();self.warm_microphone=None
        for _,cancel,_ in self.service_tests.values():cancel.set()
        self.service_tests.clear();self.cancel();self.keys.stop()
        if self.clip_tx:self.restore_clipboard(self.clip_tx)
        self.monitor.stop();self.window.resource_timer.stop()
        try:self.bridge.usage_received.disconnect(self.record_usage)
        except (RuntimeError,TypeError):pass
        self.tray.hide();self.bubble.hide();self.result_bubble.hide()
        if quit_app:self.app.quit()

def main():
    import multiprocessing
    multiprocessing.freeze_support()
    from .storage import OFFLINE_MODEL_DIR_NAMES
    parser=argparse.ArgumentParser(description='MurMur voice assistant');parser.add_argument('--tray',action='store_true');parser.add_argument('--no-hotkeys',action='store_true');parser.add_argument('--data-dir');parser.add_argument('--screenshots');parser.add_argument('--transcribe-wav');parser.add_argument('--output-file');parser.add_argument('--offline-model-dir');parser.add_argument('--offline-engine',choices=tuple(OFFLINE_MODEL_DIR_NAMES));parser.add_argument('--offline-acceleration',choices=('cpu','gpu'))
    parser.add_argument('--debug',action='store_true',help='Show detailed lifecycle diagnostics (no text content)')
    parser.add_argument('--log-level',choices=('DEBUG','INFO','WARNING','ERROR'),default='INFO',type=str.upper,help='Console verbosity (default: INFO)')
    parser.add_argument('--color',choices=('auto','always','never'),default='auto',help='Console color; auto detects a terminal and respects NO_COLOR')
    args=parser.parse_args();configure('DEBUG' if args.debug else args.log_level,args.color)
    banner()
    event('app','MurMur %s | %s',__version__,'WAV transcription' if args.transcribe_wav else 'desktop')
    event('app','Diagnostics enabled',level='DEBUG')
    if args.transcribe_wav:
        if not args.output_file:parser.error('--transcribe-wav requires --output-file')
        import wave
        from .offline import transcribe_pcm
        from .paths import data_dir
        from .profiles import ProfileRegistry
        from .storage import set_credential_scope
        registry=ProfileRegistry(args.data_dir or data_dir());record=registry.get(registry.current)
        if record['password'] is not None:
            if not sys.stdin or not sys.stdin.isatty():raise RuntimeError('This local account is locked. Run from an interactive terminal to enter its password.')
            import getpass
            if not registry.authenticate(record['id'],getpass.getpass('Local account password: ')):raise RuntimeError('Incorrect local account password.')
        set_credential_scope(record['id']);cli_store=Store(registry.folder(record['id']));cfg=cli_store.config.copy()
        selected_engine=args.offline_engine or cfg.get('offline_engine','sensevoice')
        selected_acceleration=args.offline_acceleration or cfg.get('offline_acceleration','cpu')
        if selected_engine=='paraformer':selected_acceleration='cpu'
        changed=(selected_engine,selected_acceleration)!=(cfg.get('offline_engine','sensevoice'),cfg.get('offline_acceleration','cpu'))
        if changed and not args.offline_model_dir:
            from .storage import default_offline_model_dir
            cfg['offline_model_dir']=str(default_offline_model_dir(engine=selected_engine,acceleration=selected_acceleration))
        cfg.update(offline_engine=selected_engine,offline_acceleration=selected_acceleration)
        if args.offline_model_dir:cfg['offline_model_dir']=args.offline_model_dir
        cli_store.db.close()
        with wave.open(args.transcribe_wav,'rb') as audio:
            if audio.getnchannels()!=1 or audio.getframerate()!=16000 or audio.getsampwidth()!=2:raise ValueError('Use a mono 16 kHz, 16-bit PCM WAV file.')
            pcm=audio.readframes(audio.getnframes())
        event('speech','Transcribing WAV | engine=%s | acceleration=%s | audio=%.2fs',selected_engine,selected_acceleration,len(pcm)/32000)
        started=time.monotonic();result=transcribe_pcm(pcm,cfg)
        Path(args.output_file).write_text(result,'utf-8');event('speech','Transcription saved | elapsed=%.2fs',time.monotonic()-started);return 0
    app=QApplication(sys.argv[:1]);app.setStyle('Fusion');app.setApplicationName('MurMur');app.setApplicationVersion(__version__);app.setQuitOnLastWindowClosed(False);app.setStyleSheet(STYLE)
    from PySide6.QtGui import QPalette,QColor
    palette=QPalette()
    for role,color in [(QPalette.Window,'#202022'),(QPalette.WindowText,'#ececf0'),(QPalette.Base,'#29292d'),(QPalette.Text,'#ececf0'),(QPalette.Button,'#333337'),(QPalette.ButtonText,'#ececf0'),(QPalette.Highlight,'#aaa0e1'),(QPalette.HighlightedText,'#202022')]:palette.setColor(role,QColor(color))
    app.setPalette(palette)
    from PySide6.QtNetwork import QLocalServer,QLocalSocket
    lock=None
    if not args.data_dir:
        sock=QLocalSocket();sock.connectToServer('MurMur-desktop-v1')
        if sock.waitForConnected(300):
            event('app','Existing instance found; opening its window')
            sock.write(b'show');sock.flush();sock.waitForBytesWritten(300);return
        lock=QLocalServer();QLocalServer.removeServer('MurMur-desktop-v1');lock.listen('MurMur-desktop-v1')
    account_manager=None
    from .paths import data_dir
    from .profiles import ProfileRegistry
    from .account_ui import AccountDialog,public_profile
    from .storage import set_credential_scope
    from .account_manager import AccountManager
    registry=ProfileRegistry(args.data_dir or data_dir());record=registry.get(registry.current)
    if record['password'] is not None:
        dialog=AccountDialog(registry,registry.current,startup=True)
        if dialog.exec()!=QDialog.Accepted:return 0
        record=registry.get(dialog.selected)
    set_credential_scope(record['id']);store=Store(registry.folder(record['id']));store.profile=public_profile(record)
    controller=Controller(app,store,not args.no_hotkeys)
    account_manager=AccountManager(app,registry,controller,not args.no_hotkeys)
    if not args.screenshots:
        controller.preload_speech()
        QTimer.singleShot(0,controller.window.enable_saved_service_checks)
    if lock:
        def show():
            conn=lock.nextPendingConnection();conn.close();(account_manager.controller if account_manager else controller).show_main()
        lock.newConnection.connect(show)
    if not args.tray:controller.show_main()
    if args.screenshots:
        path=Path(args.screenshots);path.mkdir(parents=True,exist_ok=True)
        def shots():
            if store.rows() and all(r['demo'] for r in store.rows()):controller.window.stats_source.setCurrentIndex(1)
            for i,name in enumerate(('overview','history','dictionary','settings')):
                controller.window.navigate(i)
                # The normal navigation fade needs time to finish before an
                # exported screenshot can represent the settled interface.
                settle=QEventLoop();QTimer.singleShot(180,settle.quit);settle.exec()
                app.processEvents();controller.window.grab().save(str(path/f'{name}.png'))
            for i in range(controller.window.settings_tabs.count()):
                controller.window.settings_tabs.setCurrentIndex(i);app.processEvents();controller.window.grab().save(str(path/f'settings-{i}.png'))
            controller.preview.show_text('These are the original words, ready for refinement.','These are the refined words, ready to use.','Demo preview · no API was called',False);app.processEvents();controller.preview.grab().save(str(path/'preview.png'))
            for state in ('待机','录音','识别','整理','完成','失败'):
                controller.bubble.state(state,'Demo state',True);app.processEvents();controller.bubble.grab().save(str(path/f'bubble-{state}.png'))
            controller.quit()
        QTimer.singleShot(800,shots)
    return app.exec()

if __name__=='__main__':main()

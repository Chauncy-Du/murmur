import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from murmur import app as module,storage,windows
from murmur.app import Controller

class DeferredWorker:
    jobs=[]
    def __init__(self,target,**kwargs):self.target=target
    def start(self):self.jobs.append(self.target)

@pytest.fixture
def controller(tmp_path,monkeypatch):
    DeferredWorker.jobs=[]
    monkeypatch.setattr(module.threading,'Thread',DeferredWorker)
    monkeypatch.setattr(storage,'credential',lambda *args:'')
    monkeypatch.setattr(windows,'prepare_text_context',lambda:None)
    app=QApplication.instance() or QApplication([])
    store=storage.Store(tmp_path);store.config.update(demo=False,asr_backend='offline',audio_warm_enabled=False)
    c=Controller(app,store,False)
    yield c
    c.quitting=True;c.startup_cancel.set();c.startup_timer.stop();c.monitor.stop()
    for w in (c.window,c.bubble,c.preview,c.result_bubble,c.tray):w.hide()
    store.db.close()

def test_loading_owns_every_input_entry_and_cancel_cannot_hide_it(controller):
    c=controller;c.preload_speech();ident=c.startup_id
    assert c.startup_busy and not c.window.isEnabled() and c.bubble.isVisible()
    assert not c.bubble.close.isEnabled() and not c.bubble.mic.isEnabled()
    for event in ('pending','release','translation','selection','ask','cancel','altgr'):
        c.hotkey(event)
    c.toggle();c.start_ask();c.capture_selection();c.edit('text','润色','');c.open_preview();c.cancel()
    assert c.session is None and not c.pending and not c.capture_busy
    assert c.bubble.isVisible() and c.startup_id==ident
    assert len(DeferredWorker.jobs)==1

def test_real_completion_reaches_100_before_unlock_and_hides(controller):
    c=controller;c.preload_speech();ident=c.startup_id
    c.startup_status(ident,'loading',None)
    assert c.bubble.progress.percentage==15
    c.startup_started-=10000;c.startup_tick()
    assert c.bubble.progress.percentage<=95
    assert 'Estimated progress' in c.bubble.toolTip()
    c.startup_status(ident,'ready',None)
    assert c.bubble.progress.percentage==100 and c.startup_busy
    QTest.qWait(450)
    assert not c.startup_busy and c.window.isEnabled() and not c.bubble.isVisible()
    assert c.window.record_button.isEnabled()

def test_failure_keeps_actions_blocked_but_settings_accessible(controller):
    c=controller;c.preload_speech();c.startup_status(c.startup_id,'error','Missing local weights')
    assert not c.startup_busy and c.startup_blocked() and c.window.isEnabled()
    assert not c.window.record_button.isEnabled() and c.result_bubble.preview.toPlainText()=='Missing local weights'
    c.toggle();c.start_ask();assert c.session is None
    c.preload_speech();assert c.startup_busy and not c.startup_error

@pytest.mark.parametrize('backend,demo',[('openai',False),('ali_nls',False),('offline',True)])
def test_cloud_and_demo_do_not_load_native_models(controller,backend,demo):
    c=controller;c.store.config.update(asr_backend=backend,demo=demo);c.preload_speech()
    assert not c.startup_busy and not DeferredWorker.jobs

def test_worker_uses_selected_snapshot_and_stale_quit_callbacks_ignored(controller,monkeypatch):
    from murmur import offline
    c=controller;seen=[]
    monkeypatch.setattr(offline,'model_paths',lambda cfg:seen.append(cfg['offline_engine']))
    monkeypatch.setattr(offline,'load_recognizer',lambda cfg,cancel:seen.append(cfg['offline_engine']))
    c.preload_speech();ident=c.startup_id;original=c.store.config['offline_engine']
    c.store.config['offline_engine']='qwen_asr'
    DeferredWorker.jobs[0]()
    assert seen==[original,original]
    c.startup_status('stale','error','ignored');assert not c.startup_error
    c.quitting=True;c.startup_status(ident,'error','ignored');assert not c.startup_error

def test_online_startup_waits_for_warm_microphone_and_reuses_it(controller,monkeypatch):
    from murmur import warm_microphone
    events=[]
    class ReadyMicrophone:
        def __init__(self,cfg):events.append(('config',cfg['audio_preroll_ms']))
        def start(self,cancel):events.append('received first frame')
        def close(self):events.append('closed')
    monkeypatch.setattr(warm_microphone,'WarmMicrophone',ReadyMicrophone)
    c=controller;c.store.config.update(asr_backend='ali_nls',audio_warm_enabled=True)
    c.preload_speech();assert c.startup_busy and c.warm_microphone is None
    DeferredWorker.jobs[0]()
    assert events==[('config',500),'received first frame']
    assert isinstance(c.warm_microphone,ReadyMicrophone)
    assert c.bubble.progress.percentage==100 and c.startup_busy
    QTest.qWait(450);assert not c.startup_busy

"""Voice assistant routing and automatic writing without external side effects."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QTabWidget
from murmur import app as app_module, storage, windows
from murmur.app import Controller, Session
from murmur.providers import AskResult


@pytest.fixture
def controller(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'credential',lambda *args:'')
    app=QApplication.instance() or QApplication([])
    c=Controller(app,storage.Store(tmp_path),False)
    c.store.config['demo']=True
    yield c
    c.cancel();c.monitor.stop();c.tray.hide();c.bubble.hide();c.result_bubble.hide();c.preview.hide();c.window.hide()


def session(c,state='selection',demo=False):
    t=windows.Target(10,11,12,(1,),12,state!='readonly')
    context=windows.TextContext('selection' if state=='readonly' else state,'Public selected source' if state in ('selection','readonly') else '', 'token' if state!='unknown' else None)
    s=Session('随便问',dict(c.store.config,demo=demo),t,raw='Public spoken request',assistant=True,context=context,input_epoch=c.input_epoch)
    c.session=s
    return s


def monitoring(c,monkeypatch):
    monkeypatch.setattr(type(c.keys),'monitoring',property(lambda keys:True))


@pytest.mark.parametrize('action,state,mode',[('replace','selection','语音编辑'),('insert','caret','起草'),('answer','selection','问答')])
def test_routes_results_and_preserves_request_source(controller,monkeypatch,action,state,mode):
    c=controller;monitoring(c,monkeypatch);s=session(c,state);sent=[]
    monkeypatch.setattr(c,'paste',lambda text,target,**kw:sent.append((text,kw['context'],kw['guard']())))
    c.receive(s.id,'result',AskResult(action,'Public output'))
    assert len(sent)==(action!='answer')
    if sent:assert sent[0][2] is True
    assert c.session is None and c.result_bubble.isVisible() and not c.preview.isVisible()
    row=c.store.rows()[0]
    assert row['mode']==mode and row['raw']==s.raw and row['context']==s.context.text
    assert row['final']=='Public output' and len(c.store.rows())==1


@pytest.mark.parametrize('cause',['input','hook_input','focus','unknown','wrong_action','demo','monitoring','cancel_hook'])
def test_changed_or_unverifiable_targets_never_write(controller,monkeypatch,cause):
    c=controller;monitoring(c,monkeypatch);s=session(c)
    if cause=='input':c.input_epoch+=1
    elif cause=='hook_input':c.keys.physical_generation+=1
    elif cause=='focus':s.focus_changed=True
    elif cause=='unknown':s.context=windows.TextContext()
    elif cause=='wrong_action':s.context=windows.TextContext('caret','','token')
    elif cause=='demo':s.cfg['demo']=True
    elif cause=='monitoring':monkeypatch.setattr(type(c.keys),'monitoring',property(lambda keys:False))
    elif cause=='cancel_hook':c.keys.cancel_generation+=1
    monkeypatch.setattr(c,'paste',lambda *a,**kw:pytest.fail('Unconfirmed target received text'))
    c.receive(s.id,'result',AskResult('replace','Preserved result'))
    if cause=='cancel_hook':assert not c.result_bubble.isVisible()
    else:assert c.result_bubble.text=='Preserved result' and c.result_bubble.isVisible()


def test_readonly_context_answer_does_not_require_writable_target(controller,monkeypatch):
    c=controller;s=session(c,'readonly')
    monkeypatch.setattr(c,'paste',lambda *a,**kw:pytest.fail('Readonly source modified'))
    c.receive(s.id,'result',AskResult('answer','Explanation'))
    assert c.result_bubble.text=='Explanation'
    c.result_bubble.edit_button.click()
    assert c.preview.isVisible() and c.preview.title_label.text()=='Ask Anything result'
    assert s.raw in c.preview.raw.toPlainText() and s.context.text in c.preview.raw.toPlainText()


@pytest.mark.parametrize('payload',[AskResult('invalid','text'),AskResult('replace',''),'plain string',None])
def test_invalid_model_result_preserves_voice_without_paste(controller,monkeypatch,payload):
    c=controller;s=session(c)
    monkeypatch.setattr(c,'paste',lambda *a,**kw:pytest.fail('Invalid action pasted'))
    c.receive(s.id,'result',payload)
    assert c.result_bubble.text==s.raw and c.store.rows()[0]['error']
    assert not c.preview.isVisible()


def test_errors_keep_latest_recorder_text_and_do_not_activate_editor(controller):
    c=controller;s=session(c)
    class Recorder:
        duration=1;raw='Newest frozen instruction'
        def abort(self):pass
    s.recorder=Recorder()
    c.receive(s.id,'error','HTTP 429')
    assert c.result_bubble.text==s.recorder.raw and not c.preview.isVisible()
    assert c.store.rows()[0]['error']=='HTTP 429'


def test_cancel_keeps_latest_recorder_text_and_ignores_late_answer(controller):
    c=controller;s=session(c);s.raw=''
    class Recorder:
        raw='Final canceled voice instruction';duration=1
        def abort(self):pass
    s.recorder=Recorder();c.cancel();c.receive(s.id,'result',AskResult('answer','Too late'))
    assert not c.result_bubble.isVisible()
    row=c.store.rows()[0]
    assert row['raw']==s.recorder.raw and row['context']==s.context.text


@pytest.mark.parametrize('dictation_key',['f9','disabled'])
def test_right_alt_only_finishes_ask_with_alternate_or_disabled_dictation(controller,monkeypatch,dictation_key):
    c=controller;c.store.config['dictation_key']=dictation_key;calls=[];callbacks=[]
    monkeypatch.setattr(c,'toggle',lambda *a:calls.append('dictation'))
    monkeypatch.setattr(QTimer,'singleShot',lambda delay,callback:callbacks.append(callback))
    c.hotkey('pending',1);c.hotkey('release',1)
    for callback in callbacks:callback()
    assert not calls
    s=session(c);s.phase='录音'
    monkeypatch.setattr(c,'stop',lambda:calls.append('stop_ask'))
    c.hotkey('pending',2);c.hotkey('release',2)
    assert calls==['stop_ask']


@pytest.mark.parametrize('trigger',['toggle','hold'])
def test_ask_initial_release_is_ignored_and_next_right_alt_finishes(controller,monkeypatch,trigger):
    c=controller;c.store.config['trigger']=trigger;s=session(c);s.phase='录音';calls=[]
    monkeypatch.setattr(c,'stop',lambda:calls.append('stop'))
    c.hotkey('ask_release',1)
    assert not calls
    c.hotkey('pending',2);c.hotkey('release',2)
    assert calls==['stop']


def test_late_space_promotes_same_recorder_and_invalidates_delay(controller,monkeypatch):
    c=controller;s=Session('听写',dict(c.store.config),None,gesture=7,phase='录音');c.session=s
    monkeypatch.setattr(windows,'text_context',lambda target:windows.TextContext('selection','Source','token'))
    monkeypatch.setattr(c,'toggle',lambda *args:pytest.fail('Duplicate recording'))
    c.pending=True;c.pending_generation=1;c.hotkey('ask',7);c.begin_pending(1)
    assert c.session is s and s.assistant and s.context.text=='Source' and not c.pending
    assert s.steps==('Transcribe','Respond') and s.completed_steps==0


def test_promotion_checks_separate_key_and_aborts_pending_dictation(controller,monkeypatch):
    c=controller;c.store.config['demo']=False;s=Session('听写',dict(c.store.config),None,gesture=5);c.session=s
    monkeypatch.setattr(app_module,'credential',lambda *args:'')
    c.hotkey('ask',5)
    assert s.cancel.is_set() and c.session is None
    assert 'Setup required' in c.result_bubble.status.text()


def test_input_arrives_during_uia_check_before_paste(controller,monkeypatch):
    c=controller;monitoring(c,monkeypatch);s=session(c);checks=[];restored=[];keys=[]
    monkeypatch.setattr(windows,'valid',lambda target:True)
    def matches(target,context):
        checks.append(1)
        if len(checks)==2:c.keys.physical_generation+=1
        return True
    class Transaction:
        def write(self,text):pass
        def restore(self,*args):restored.append(True)
    monkeypatch.setattr(windows,'context_matches',matches)
    monkeypatch.setattr(windows,'ClipboardTransaction',Transaction)
    monkeypatch.setattr(windows,'chord',keys.append)
    c.receive(s.id,'result',AskResult('replace','New text'))
    assert not keys and restored==[True]
    assert c.result_bubble.text=='New text' and 'Input changed' in c.result_bubble.status.toolTip()
    assert c.result_bubble.status.text()=='Ask Anything · Preview only'


def test_ask_worker_routes_asr_directly_without_dictation_transform(controller,monkeypatch):
    c=controller;s=session(c,'selection',demo=True);s.phase='录音';seen=[]
    class Recorder:
        raw='Explain this source';duration=1
        def stop(self):return self.raw
        def abort(self):pass
    s.recorder=Recorder()
    monkeypatch.setattr(app_module,'transform',lambda *a,**kw:pytest.fail('Ask passed through dictation'))
    monkeypatch.setattr(app_module,'ask',lambda instruction,context,cfg,**kw:(seen.append((instruction,context)) or AskResult('answer','Answer')))
    c.stop()
    for _ in range(100):
        if c.session is None:break
        QTest.qWait(10)
    assert c.session is None and seen==[('Explain this source',s.context.text)]
    assert c.result_bubble.text=='Answer'


def test_ask_settings_history_and_detail_are_separate(controller,monkeypatch):
    c=controller;c.window.ask_llm_key.setText('mock-ask-key')
    cfg,secrets=c.window.service_test_values()
    assert secrets['ask_llm']=='mock-ask-key' and secrets['llm']==''
    assert cfg['ask_key']=='right_alt+space' and 'ask_key' in c.window.quick_keycaps
    c.store.add('q','问答','Question','Answer',1,0,False,context='Selected source')
    c.store.add('d','听写','Dictation','Dictation',1,0,False)
    c.window.navigate(1)
    c.window.history_mode.setCurrentIndex(c.window.history_mode.findData('ask'))
    assert [row['mode'] for row in c.window.current_rows]==['问答']
    tabs=[]
    monkeypatch.setattr(QDialog,'exec',lambda dialog:tabs.extend(tab.tabText(i) for tab in dialog.findChildren(QTabWidget) for i in range(tab.count())))
    c.window.show_record(c.window.current_rows[0])
    assert tabs==['Final output','Spoken request','Selected source']


def test_ask_check_snapshot_ignores_local_settings_and_tracks_ask_key(controller):
    c=controller;cfg,secrets=c.window.service_test_values()
    snapshot=c.service_snapshot('ask',cfg,secrets)
    assert snapshot==c.service_snapshot('ask',dict(cfg,llm_model='other local model'),secrets)
    assert snapshot!=c.service_snapshot('ask',cfg,dict(secrets,ask_llm='changed'))
    assert snapshot!=c.service_snapshot('ask',dict(cfg,ask_llm_model='changed'),secrets)

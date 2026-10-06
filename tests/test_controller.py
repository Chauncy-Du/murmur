import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtWidgets import QApplication
from murmur.app import Controller,Session
from murmur.storage import Store

@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])

@pytest.fixture
def controller(app,tmp_path):
    c=Controller(app,Store(tmp_path),False)
    yield c
    c.monitor.stop();c.bubble.hide();c.result_bubble.hide();c.preview.hide();c.tray.hide();c.window.hide()

def test_late_result_ignored(controller):
    c=controller;s=Session('听写',c.store.config,None);c.session=s;c.cancel();c.receive(s.id,'result','不应写入');assert not c.store.rows()

def test_controller_syncs_waiting_stop_and_failure_controls(controller):
    c=controller;s=Session('听写',c.store.config,None,raw='Original');c.session=s;c.sync_controls()
    assert c.window.record_button.text()=='Stop recording'
    assert c.preview.raw.isReadOnly()
    c.stop()
    assert s.phase=='等待停止'
    assert not c.window.record_button.isEnabled()
    c.receive(s.id,'error','Connection failed')
    assert c.session is None and c.window.record_button.isEnabled()
    assert not c.preview.raw.isReadOnly()
    assert c.preview.result.toPlainText()=='Original'
    assert c.preview.copy_button.isEnabled()

def test_controller_cancellation_restores_editability(controller):
    c=controller;s=Session('润色',c.store.config,None,raw='Original',phase='整理');c.session=s;c.sync_controls()
    assert not c.preview.go.isEnabled() and c.preview.result.isReadOnly()
    assert not c.window.translation_button.isEnabled()
    c.cancel()
    assert c.preview.go.isEnabled() and not c.preview.result.isReadOnly()
    assert c.window.translation_button.isEnabled()

def test_local_escape_cancels_without_hooks_and_ignores_late_result(controller):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    c=controller;s=Session('润色',c.store.config,None,raw='Original',phase='整理')
    c.session=s;c.sync_controls();c.preview.show_text('Original','Previous result')
    assert not c.keys.monitoring
    QTest.keyClick(c.preview,Qt.Key_Escape)
    assert c.session is None and s.cancel.is_set()
    assert c.preview.isVisible() and not c.preview.raw.isReadOnly()
    assert len(c.store.rows())==1 and c.store.rows()[0]['error']=='Cancelled by user'
    c.hotkey('cancel')
    c.receive(s.id,'result','Late overwrite')
    assert len(c.store.rows())==1
    assert c.preview.result.toPlainText()=='Previous result'

def test_main_window_escape_cancels_without_hooks(controller):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    c=controller;s=Session('听写',c.store.config,None,raw='Original',phase='录音')
    c.session=s;c.sync_controls();c.window.show();c.window.activateWindow();c.app.processEvents()
    QTest.keyClick(c.window,Qt.Key_Escape)
    assert c.session is None and s.cancel.is_set()
    assert c.window.isVisible() and c.window.record_button.isEnabled()

def test_audio_levels_follow_only_current_recording_session(controller,monkeypatch):
    c=controller;levels=[]
    monkeypatch.setattr(c.bubble.wave,'feed_level',levels.append)
    s=Session('听写',c.store.config,None,phase='录音');c.session=s
    c.receive(s.id,'level',0.2)
    c.receive('stale-session','level',1.0)
    c.receive(s.id,'phase','整理')
    c.receive(s.id,'level',0.9)
    c.cancel();c.receive(s.id,'level',0.7)
    assert levels==[0.2]

def test_manual_nls_token_override_clears_managed_expiry(controller,monkeypatch):
    from murmur import app as app_module,storage
    c=controller;vault={'ali_token_expiry':'2000000000'};writes=[]
    def fake_credential(name,value=None):
        if value is not None: vault[name]=value;writes.append((name,value))
        return vault.get(name,'')
    monkeypatch.setattr(app_module,'credential',fake_credential)
    monkeypatch.setattr(storage,'credential',fake_credential)
    c.save_settings(dict(c.store.config),{'ali_token':'fixture-manual-token'})
    assert writes==[('ali_token','fixture-manual-token'),('ali_token_expiry','')]
    assert 'fixture-manual-token' not in c.store.path.read_text('utf-8')

def test_failure_preserves_raw(controller):
    c=controller;s=Session('听写',c.store.config,None,raw='已识别原文');c.session=s;c.receive(s.id,'error','网络失败');assert c.store.rows()[0]['raw']=='已识别原文';assert c.preview.result.toPlainText()=='已识别原文'

def test_demo_never_pastes(controller,monkeypatch):
    c=controller;s=Session('听写',c.store.config,None,raw='原文');c.session=s
    monkeypatch.setattr(c,'paste',lambda *args:pytest.fail('demo pasted'))
    c.receive(s.id,'result','结果');assert c.preview.result.toPlainText()=='结果';assert not c.preview.replace_button.isEnabled()

def test_stale_session_does_not_overwrite(controller):
    c=controller;s=Session('听写',c.store.config,None);c.session=s;c.receive('different','result','迟到结果');assert c.session==s;assert not c.store.rows()

def test_startup_cleanup_cancellation_does_not_hide_error(controller):
    c=controller;s=Session('听写',c.store.config,None);c.session=s;s.cancel.set()
    c.receive(s.id,'error','No API key is configured.')
    assert c.session is None
    assert c.store.rows()[0]['error']=='No API key is configured.'
    assert 'No API key' in c.preview.notice.text()

def test_escape_invalidates_pending_selection(controller):
    c=controller;before=c.capture_generation;c.cancel()
    assert c.capture_generation>before
    assert not c.capture_busy

def test_physical_input_prevents_automatic_paste(controller,monkeypatch):
    c=controller;cfg=dict(c.store.config,demo=False)
    s=Session('听写',cfg,object(),raw='original');c.session=s
    c.physical_input('keyboard')
    monkeypatch.setattr(c,'paste',lambda *args:pytest.fail('Changed selection pasted'))
    c.receive(s.id,'result','result')
    assert c.preview.result.toPlainText()=='result'


def test_disabled_input_monitor_prevents_same_target_paste(controller,monkeypatch):
    from murmur import windows
    c=controller;cfg=dict(c.store.config,demo=False)
    s=Session('听写',cfg,object(),raw='original');c.session=s
    monkeypatch.setattr(windows,'valid',lambda target:True)
    monkeypatch.setattr(c,'paste',lambda *args:pytest.fail('Unmonitored target pasted'))
    c.receive(s.id,'result','result')
    assert c.preview.result.toPlainText()=='result'
    assert not c.keys.monitoring
    assert 'Input monitoring is unavailable' in c.preview.notice.text()


def test_input_monitor_startup_failure_preserves_preview_operation(app,tmp_path,monkeypatch):
    from murmur.hotkeys import Hotkeys
    monkeypatch.setattr(Hotkeys,'start',lambda self:(_ for _ in ()).throw(RuntimeError('Hook failed')))
    c=Controller(app,Store(tmp_path),True)
    try:
        assert 'unavailable' in c.window.key_status.text()
        assert not c.keys.monitoring
        s=Session('听写',dict(c.store.config,demo=False),None,raw='original');c.session=s
        c.receive(s.id,'result','result')
        assert c.preview.result.toPlainText()=='result'
    finally:
        c.monitor.stop();c.bubble.hide();c.result_bubble.hide();c.preview.hide();c.tray.hide();c.window.hide()


def test_same_text_at_different_selection_blocks_replacement(controller,monkeypatch):
    from murmur import windows
    c=controller;c.store.config['demo']=False
    c.selection_target=object();c.selection_original='repeated text';c.selection_bookmark='original range'
    monkeypatch.setattr(windows,'own_target',lambda target:False)
    monkeypatch.setattr(windows,'activate',lambda target:True)
    monkeypatch.setattr(windows,'selection_matches',lambda target,bookmark:False)
    monkeypatch.setattr(windows,'ClipboardTransaction',lambda:pytest.fail('Changed selection touched clipboard'))
    c.replace('replacement')
    assert 'position could not be confirmed' in c.preview.notice.text()
    assert not c.capture_busy


def test_copy_only_capture_stays_copy_only_after_text_processing(controller):
    c=controller;c.selection_target=object();c.selection_original='original';c.selection_bookmark=None
    s=Session('润色',dict(c.store.config,demo=False),None,raw='original');c.session=s
    c.receive(s.id,'result','refined')
    assert c.preview.result.toPlainText()=='refined'
    assert not c.preview.replace_button.isEnabled()


def test_failure_preserves_partial_frozen_during_abort(controller):
    class Recorder:
        raw='';duration=1
        def abort(self):self.raw='complete sentence and latest partial'
    c=controller;s=Session('听写',c.store.config,None,raw='complete sentence');s.recorder=Recorder();c.session=s
    c.receive(s.id,'error','Microphone disconnected')
    assert c.store.rows()[0]['raw']=='complete sentence and latest partial'
    assert c.preview.result.toPlainText()=='complete sentence and latest partial'


def test_busy_clipboard_restore_is_bounded_and_does_not_lock_ui(controller,monkeypatch):
    from murmur import windows
    from murmur.app import QTimer
    c=controller;callbacks=[];calls=[]
    monkeypatch.setattr(QTimer,'singleShot',lambda delay,callback:callbacks.append(callback))
    class BusyTransaction:
        def restore(self,expected):
            calls.append(expected);raise windows.ClipboardBusy('Clipboard busy')
    tx=BusyTransaction();c.clip_tx=tx;c.restore_clipboard(tx)
    while callbacks:callbacks.pop(0)()
    assert len(calls)==4 and c.clip_tx is None
    assert 'Failed' in c.bubble.status.text()


def test_quit_does_not_wait_for_busy_clipboard(controller,monkeypatch):
    from murmur import windows
    from murmur.app import QTimer
    c=controller;c.quitting=True;calls=[]
    monkeypatch.setattr(QTimer,'singleShot',lambda *args:pytest.fail('Quit scheduled a retry'))
    class BusyTransaction:
        def restore(self,expected):
            calls.append(expected);raise windows.ClipboardBusy('Clipboard busy')
    tx=BusyTransaction();c.clip_tx=tx;c.restore_clipboard(tx)
    assert calls==[None] and c.clip_tx is None


def test_selection_uses_sequence_from_atomic_copied_snapshot(controller,monkeypatch):
    from murmur import windows
    from murmur.app import QTimer
    import win32clipboard
    c=controller;t=windows.Target(10,11,12,(42,1),12,True);restored=[]
    class Transaction:
        sequence=42
        def write(self,text):assert text==''
        def copied(self,expected):assert expected==t;return (201,'Captured text')
        def restore(self,expected):restored.append(expected);return True
    monkeypatch.setattr(windows,'ClipboardTransaction',Transaction)
    monkeypatch.setattr(windows,'target',lambda:t)
    monkeypatch.setattr(windows,'own_target',lambda target:False)
    monkeypatch.setattr(windows,'window_valid',lambda target:True)
    monkeypatch.setattr(windows,'selection_bookmark',lambda target:'range')
    monkeypatch.setattr(windows,'selection_matches',lambda *args:True)
    monkeypatch.setattr(windows,'chord',lambda key:None)
    # The earlier polling value is intentionally different from the locked
    # text/owner snapshot. Restoration must use only the latter's sequence.
    monkeypatch.setattr(win32clipboard,'GetClipboardSequenceNumber',lambda:999)
    monkeypatch.setattr(QTimer,'singleShot',lambda delay,callback:callback())
    c.capture_selection()
    assert restored==[201] and c.preview.raw.toPlainText()=='Captured text'
    assert not c.capture_busy


class MemoryClipboard:
    def __init__(self):self.value='Existing clipboard';self.writes=[]
    def setText(self,text):self.value=text;self.writes.append(text)
    def text(self):return self.value


def test_real_result_without_target_waits_for_explicit_copy_and_edit(controller,monkeypatch):
    c=controller;clip=MemoryClipboard();monkeypatch.setattr(c.app,'clipboard',lambda:clip)
    s=Session('听写',dict(c.store.config,demo=False),None,raw='Original');c.session=s
    c.receive(s.id,'result','Final result')
    assert clip.writes==[]
    assert c.result_bubble.isVisible() and not c.preview.isVisible() and not c.bubble.isVisible()
    assert c.result_bubble.text=='Final result'
    c.result_bubble.edit_button.click()
    assert not c.result_bubble.isVisible() and c.preview.isVisible()
    assert c.preview.raw.toPlainText()=='Original' and c.preview.result.toPlainText()=='Final result'


def test_demo_and_cancelled_results_do_not_automatically_copy(controller,monkeypatch):
    c=controller;clip=MemoryClipboard();monkeypatch.setattr(c.app,'clipboard',lambda:clip)
    s=Session('听写',dict(c.store.config,demo=True),None,raw='Original');c.session=s
    c.receive(s.id,'result','Demo result')
    assert c.result_bubble.isVisible() and c.result_bubble.demo and not clip.writes
    monkeypatch.setattr(QApplication,'clipboard',staticmethod(lambda:clip))
    c.result_bubble.copy_button.click()
    assert clip.writes==['Demo result']
    s=Session('听写',dict(c.store.config,demo=False),None);c.session=s;c.cancel()
    c.receive(s.id,'result','Cancelled result')
    assert clip.writes==['Demo result']


def test_failed_and_selection_results_do_not_automatically_copy(controller,monkeypatch):
    c=controller;clip=MemoryClipboard();monkeypatch.setattr(c.app,'clipboard',lambda:clip)
    s=Session('听写',dict(c.store.config,demo=False),None,raw='Partial');c.session=s
    c.receive(s.id,'error','Processing failed')
    assert not clip.writes and c.preview.result.toPlainText()=='Partial'
    s=Session('润色',dict(c.store.config,demo=False),None,raw='Original');c.session=s
    c.receive(s.id,'result','Revised selection')
    assert not clip.writes and c.preview.isVisible()


def test_short_right_alt_tap_toggles_once_and_ignores_expired_delay(controller,monkeypatch):
    from murmur.app import QTimer
    c=controller;c.store.config['trigger']='toggle';calls=[];delays=[]
    monkeypatch.setattr(c,'toggle',lambda:calls.append('toggle'))
    monkeypatch.setattr(QTimer,'singleShot',lambda ms,callback:delays.append(callback))
    for _ in range(2):
        c.hotkey('pending');c.hotkey('release')
    for callback in delays:callback()
    assert calls==['toggle','toggle'] and not c.pending


def test_long_toggle_press_does_not_toggle_again_on_release(controller,monkeypatch):
    c=controller;c.store.config['trigger']='toggle';calls=[]
    monkeypatch.setattr(c,'toggle',lambda:calls.append('toggle'))
    c.hotkey('pending');c.begin_pending(c.pending_generation);c.hotkey('release')
    assert calls==['toggle']


def test_usage_signal_records_only_metadata_once_on_ui_thread(controller):
    c=controller
    data=dict(request_id='fixture-request',local=False,total_tokens=23,cost_usd=.00004,prompt='private fixture')
    c.bridge.usage_received.emit(data);c.bridge.usage_received.emit(data)
    totals=c.store.usage_totals()
    assert totals['external_tokens']==23 and totals['requests']==1
    assert totals['external_cost_usd']==pytest.approx(.00004)
    assert 'private fixture' not in repr([dict(r) for r in c.store.db.execute('SELECT * FROM model_usage')])



def test_local_usage_console_and_home_show_actual_counts_without_content(controller,capsys):
    c=controller;capsys.readouterr()
    usage=dict(request_id='local-console',local=True,model='fixture-model',input_tokens=10,output_tokens=3,total_tokens=13,cost_usd=0,prompt='PRIVATE_CONTENT')
    c.record_usage(usage);c.record_usage(usage)
    output=capsys.readouterr().out
    assert output.count('[MurMur] Local LLM')==1
    assert 'input=10 output=3 total=13' in output and 'cumulative local tokens=13' in output
    assert 'PRIVATE_CONTENT' not in output
    assert c.window.home_local_tokens.text()=='13'
    assert c.window.home_local_tokens.accessibleName()=='Local: 13 tokens'


def test_second_alt_keeps_capsule_through_transcription_refinement_and_result(controller,monkeypatch):
    """Exercise the actual worker/signal route across both processing stages."""
    import threading,time
    from PySide6.QtTest import QTest
    from murmur import app as app_module
    transcribed=threading.Event();refined=threading.Event()
    class Recorder:
        raw='Public sample';duration=1
        def stop(self):
            assert transcribed.wait(3)
            return self.raw
        def abort(self):transcribed.set();refined.set()
    def transform(raw,*args,**kwargs):
        assert refined.wait(3)
        return 'Public result'
    monkeypatch.setattr(app_module,'transform',transform)
    c=controller;clip=MemoryClipboard();monkeypatch.setattr(c.app,'clipboard',lambda:clip)
    cfg=dict(c.store.config,demo=False,trigger='toggle',polish=True)
    c.store.config['trigger']='toggle'
    s=Session('听写',cfg,None,phase='录音',recorder=Recorder());c.session=s
    c.bubble.state('录音');c.sync_controls()
    def wait_for(predicate):
        until=time.monotonic()+2
        while not predicate() and time.monotonic()<until:
            QTest.qWait(10)
            # Release the GIL so the actual recorder/refiner worker can emit
            # its Qt signal even under concurrent native runtime tests.
            time.sleep(.001)
        assert predicate()
    try:
        c.hotkey('pending');c.hotkey('release')
        assert s.phase=='识别' and c.bubble.isVisible()
        assert c.bubble.progress.running and not c.bubble.wave.active
        assert not c.bubble.mic.isVisible() and not c.window.record_button.isEnabled()
        transcribed.set();wait_for(lambda:s.phase=='整理')
        assert c.bubble.isVisible() and c.bubble.progress.running
        assert c.bubble.status.text()=='Organize' and s.raw=='Public sample'
        assert c.bubble.progress.completed_steps==1 and c.bubble.progress.total_steps==2
        refined.set();wait_for(lambda:c.session is None)
        assert not c.bubble.isVisible() and c.result_bubble.isVisible()
        assert c.result_bubble._morph is not None and clip.writes==[]
        c.cancel();QTest.qWait(280)
        assert not c.result_bubble.isVisible() and c.result_bubble._morph is None
    finally:transcribed.set();refined.set()


def test_stop_during_startup_has_no_recording_flash_or_late_result(controller,monkeypatch):
    import threading
    from PySide6.QtTest import QTest
    from murmur import app as app_module
    released=threading.Event();exited=threading.Event();states=[]
    class Recorder:
        raw='';duration=0
        def stop(self):
            released.wait(3);exited.set();return 'Late public result'
        def abort(self):released.set()
    monkeypatch.setattr(app_module,'transform',lambda *args,**kwargs:pytest.fail('Cancelled recording was processed'))
    c=controller;original=c.bubble.state
    monkeypatch.setattr(c.bubble,'state',lambda state,*args:(states.append(state),original(state,*args)))
    s=Session('听写',dict(c.store.config,polish=True),None,recorder=Recorder());c.session=s
    c.bubble.state('启动');c.stop()
    assert s.phase=='等待停止' and c.bubble.isVisible() and c.bubble.progress.running
    c.receive(s.id,'started',None)
    assert s.phase=='识别' and c.bubble.isVisible() and '录音' not in states
    c.cancel();assert exited.wait(1)
    QTest.qWait(70);c.receive(s.id,'result','Late public result')
    assert c.session is None and not c.bubble.isVisible() and not c.result_bubble.isVisible()
    assert not c.store.rows()

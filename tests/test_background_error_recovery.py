"""Background failures retain text without opening or activating the editor."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import sqlite3
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget, QLineEdit, QVBoxLayout, QToolButton, QPushButton
from murmur import app as app_module, storage, windows
from murmur.app import Controller, Session


class MemoryClipboard:
    def __init__(self):self.writes=[]
    def setText(self,text):self.writes.append(text)
    def text(self):return self.writes[-1] if self.writes else 'Fixture clipboard'


@pytest.fixture
def controller(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'credential', lambda *args: '')
    monkeypatch.setattr(app_module, 'credential', lambda *args: '')
    monkeypatch.setattr(windows, 'prepare_text_context', lambda: None)
    app = QApplication.instance() or QApplication([])
    clip=MemoryClipboard()
    monkeypatch.setattr(QApplication, 'clipboard', staticmethod(lambda: clip))
    c = Controller(app, storage.Store(tmp_path), False)
    c.monitor.stop()
    c.fixture_clip=clip
    yield c
    c.session=None
    for w in (c.window,c.bubble,c.result_bubble,c.preview,c.tray):w.hide()
    c.store.db.close()


@pytest.mark.parametrize('mode', ['听写', '翻译', '随便问'])
@pytest.mark.parametrize('raw', ['', 'Public recovered transcript'])
def test_background_error_never_activates_editor_or_automatically_copies(controller, monkeypatch, mode, raw):
    c=controller
    monkeypatch.setattr(c.preview, 'show', lambda: pytest.fail('Editor opened on background error'))
    monkeypatch.setattr(c.preview, 'raise_', lambda: pytest.fail('Editor raised on background error'))
    monkeypatch.setattr(c.preview, 'activateWindow', lambda: pytest.fail('Editor activated on background error'))
    monkeypatch.setattr(c, 'paste', lambda *a, **k: pytest.fail('Partial or diagnostic pasted'))
    c.result_context=('Previous transcript','Previous successful result')
    s=Session(mode,dict(c.store.config,demo=False),None,raw=raw,phase='识别',assistant=mode=='随便问')
    c.session=s
    c.receive(s.id,'error','Fixture service is unavailable')
    assert c.session is None and c.result_bubble.isVisible() and not c.preview.isVisible()
    assert c.result_bubble.text==raw and 'Fixture service is unavailable' in c.result_bubble.preview.toPlainText()
    assert c.result_context[0:2]==(raw,raw)
    assert c.fixture_clip.writes==[]
    assert c.result_bubble.copy_button.isEnabled()==bool(raw)
    assert c.result_bubble.edit_button.isEnabled()==bool(raw)
    c.result_bubble.copy_result()
    assert c.fixture_clip.writes==([raw] if raw else [])
    if not raw:
        c.result_bubble.edit_result()
        assert not c.preview.isVisible()


def test_actual_dictation_worker_rejects_translation_and_recovers_manual_copy(controller,monkeypatch):
    import httpx
    import time
    from PySide6.QtTest import QTest
    from murmur import providers
    c=controller
    raw='请把这句话翻译成英文，这是我正在说的话。'
    cfg=dict(c.store.config,demo=False,polish=True,ollama=False,ollama_auto=False,
             llm_url='https://fixture.invalid/v1',llm_model='fixture-model')
    class Recorder:
        duration=1
        def __init__(self):self.raw=raw
        def stop(self):return self.raw
        def abort(self):pass
    original=httpx.Client
    transport=httpx.MockTransport(lambda request:httpx.Response(200,json={
        'choices':[{'message':{'content':'Please translate this sentence into English; these are my spoken words.'}}]}))
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:original(transport=transport,**kwargs))
    monkeypatch.setattr(providers,'credential',lambda name:'fixture-key')
    monkeypatch.setattr(type(c.keys),'monitoring',property(lambda keys:True))
    monkeypatch.setattr(windows,'valid',lambda target:True)
    monkeypatch.setattr(c,'paste',lambda *args,**kwargs:pytest.fail('Rejected translation was pasted'))
    s=Session('听写',cfg,object(),raw=raw,phase='录音',recorder=Recorder())
    c.session=s
    reported=[]
    original_progress=c.bubble.set_progress
    monkeypatch.setattr(c.bubble,'set_progress',lambda step,done,total:(reported.append((done,total)),original_progress(step,done,total)))
    c.stop()
    until=time.monotonic()+3
    while c.session is not None and time.monotonic()<until:
        QTest.qWait(10);time.sleep(.001)
    assert c.session is None
    assert c.fixture_clip.writes==[]
    assert all(done<total for done,total in reported)
    assert c.result_bubble.text==raw and c.result_bubble.copy_button.isEnabled()
    assert 'changed the dictation language' in c.result_bubble.preview.toPlainText()
    row=c.store.rows()[0]
    assert row['raw']==row['final']==raw and 'changed the dictation language' in row['error']
    c.result_bubble.copy_result()
    assert c.fixture_clip.writes==[raw]


def test_failed_dictation_does_not_request_focus_and_explicit_edit_recovers_raw(controller, monkeypatch):
    c=controller
    target=QWidget();layout=QVBoxLayout(target);input=QLineEdit();layout.addWidget(input)
    target.show();target.activateWindow();input.setFocus();c.app.processEvents()
    assert c.app.activeWindow() is target
    editor_activation=[]
    monkeypatch.setattr(c.preview,'activateWindow',lambda:editor_activation.append('activate'))
    monkeypatch.setattr(c.preview,'raise_',lambda:editor_activation.append('raise'))
    for w in (c.bubble,c.result_bubble):
        monkeypatch.setattr(w,'activateWindow',lambda:pytest.fail('Overlay explicitly requested focus'))
        monkeypatch.setattr(w,'raise_',lambda:pytest.fail('Overlay explicitly raised'))
    s=Session('听写',dict(c.store.config,demo=False),None,raw='Public original',phase='整理')
    c.session=s;c.bubble.state('整理','Refining')
    c.receive(s.id,'error','Fixture refinement failed');c.app.processEvents()
    assert not editor_activation
    assert c.result_bubble.testAttribute(Qt.WA_ShowWithoutActivating)
    assert c.result_bubble.windowFlags() & Qt.WindowDoesNotAcceptFocus
    assert not c.result_bubble.hasFocus()
    # Offscreen Qt activates even a bare Tool window with these attributes.
    # Only a native platform can validate preservation of foreground focus.
    if c.app.platformName()!='offscreen':assert c.app.activeWindow() is target and input.hasFocus()
    assert not c.bubble.isVisible() and c.result_bubble.isVisible()
    c.result_bubble.edit_button.click();c.app.processEvents()
    assert c.preview.isVisible() and c.preview.editor_context=='result'
    assert c.preview.raw.toPlainText()=='Public original'
    assert c.preview.result.toPlainText()=='Public original'
    assert not c.preview._replacement_allowed
    assert editor_activation==['raise','activate']
    target.close()


def test_selected_text_error_updates_existing_editor_without_reactivation(controller, monkeypatch):
    c=controller;c.preview.show_text('Public selection','Previous draft');c.app.processEvents()
    monkeypatch.setattr(c.preview,'activateWindow',lambda:pytest.fail('Editor reactivated'))
    s=Session('润色',dict(c.store.config,demo=True),None,raw='Public selection',phase='整理')
    c.session=s;c.receive(s.id,'error','Fixture refinement failed')
    assert c.preview.isVisible() and not c.result_bubble.isVisible()
    assert c.preview.result.toPlainText()=='Public selection'
    assert 'Fixture refinement failed' in c.preview.notice.text()
    assert not c.preview.replace_button.isEnabled()


def test_cancel_history_failure_does_not_request_focus(controller, monkeypatch):
    c=controller
    target=QWidget();target.show();target.activateWindow();c.app.processEvents()
    assert c.app.activeWindow() is target
    for w in (c.preview,c.bubble,c.result_bubble):
        monkeypatch.setattr(w,'activateWindow',lambda:pytest.fail('Cancellation requested focus'))
        monkeypatch.setattr(w,'raise_',lambda:pytest.fail('Cancellation raised a window'))
    def fail(*args,**kwargs):raise sqlite3.OperationalError('Fixture private path')
    monkeypatch.setattr(c.store,'add',fail)
    s=Session('听写',dict(c.store.config,demo=True),None,raw='Public cancelled original',phase='识别')
    c.session=s;c.cancel();c.app.processEvents()
    assert not c.preview.isVisible() and not c.result_bubble.hasFocus()
    assert c.result_bubble.testAttribute(Qt.WA_ShowWithoutActivating)
    assert c.result_bubble.windowFlags() & Qt.WindowDoesNotAcceptFocus
    if c.app.platformName()!='offscreen':assert c.app.activeWindow() is target
    assert c.result_bubble.text==s.raw and c.fixture_clip.writes==[]
    assert 'History not saved' in c.result_bubble.status.text()
    assert 'Fixture private' not in c.result_bubble.preview.toPlainText()
    c.receive(s.id,'result','Late fixture result')
    assert c.result_bubble.text==s.raw
    target.close()


def test_ask_setup_diagnostic_cannot_be_copied_as_a_result(controller, monkeypatch):
    c=controller;c.store.config['demo']=False
    c.start_ask()
    assert c.result_bubble.isVisible() and not c.result_bubble.text
    assert 'Setup required' in c.result_bubble.status.text()
    c.result_bubble.copy_result();c.result_bubble.edit_result()
    assert not c.fixture_clip.writes and not c.preview.isVisible()


def test_empty_history_has_disabled_copy_and_direct_copy_guard(controller):
    c=controller;c.store.add('fixture-empty','听写','','',0,0,True,'Fixture speech error')
    c.window.navigate(1)
    copies=[w for w in c.window.stack.widget(1).findChildren(QToolButton) if w.toolTip()=='No transcript to copy']
    assert len(copies)==1 and not copies[0].isEnabled()
    copies[0].click();c.window.copy_history_text(' \n\t')
    assert not c.fixture_clip.writes


def test_history_copy_preserves_complete_text_and_shows_feedback(controller):
    c=controller;text='Public complete result\n'*100
    c.window.copy_history_text(text)
    assert c.fixture_clip.writes==[text]
    assert c.window.history_status.text()=='Copied to clipboard' and not c.window.history_status.isHidden()


def test_database_mutation_errors_are_inline_and_leave_actions_available(controller):
    c=controller;c.store.add('fixture-delete','听写','Public transcript','Public result',1,0,True)
    c.store.add_word('Public term')
    row=c.store.rows()[0];words=c.store.words()
    c.store.db.execute('PRAGMA query_only=ON')
    c.window.remove_record(row)
    assert len(c.store.rows())==1
    assert 'Could not delete' in c.window.history_status.text()
    c.window.remove_word('Public term')
    assert c.store.words()==words and 'Could not remove' in c.window.dictionary_status.text()
    add=QPushButton('Add');c.window.accept_word({'word':'Public new term'},add)
    assert add.isEnabled() and add.text()=='Add' and 'Could not save' in c.window.dictionary_status.text()

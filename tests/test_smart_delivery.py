import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtWidgets import QApplication

from murmur import app as app_module,storage,windows
from murmur.app import Controller,Session
from murmur.result_review import ReviewedText,ReviewAssessment


@pytest.fixture
def controller(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'credential',lambda *args:'')
    monkeypatch.setattr(app_module,'credential',lambda *args:'')
    monkeypatch.setattr(windows,'prepare_text_context',lambda:None)
    monkeypatch.setattr(windows,'valid',lambda target:target is not None)
    monkeypatch.setattr(windows,'forget_paste',lambda *args:None)
    application=QApplication.instance() or QApplication([])
    c=Controller(application,storage.Store(tmp_path),False);c.monitor.stop()
    monkeypatch.setattr(type(c.keys),'monitoring',property(lambda keys:True))
    c.callbacks=[];c.copied=[]
    monkeypatch.setattr(app_module.QTimer,'singleShot',lambda delay,callback:c.callbacks.append(callback))
    class Clipboard:
        def setText(self,text):c.copied.append(text)
        def text(self):return c.copied[-1] if c.copied else ''
    monkeypatch.setattr(QApplication,'clipboard',staticmethod(lambda:Clipboard()))
    yield c
    c.delivery=None;c.session=None
    for widget in (c.window,c.bubble,c.result_bubble,c.preview,c.tray):widget.hide()
    c.store.db.close()


def finish(c,result=None,**cfg):
    session=Session('听写',dict(c.store.config,demo=False,**cfg),object(),raw='Original transcript')
    c.session=session
    c.receive(session.id,'result',result if result is not None else ReviewedText('Complete written text.',review=ReviewAssessment(False,(),True)))
    return session


def test_confirmed_clear_result_is_inserted_without_result_bubble_or_automatic_copy(controller,monkeypatch):
    c=controller;calls=[]
    monkeypatch.setattr(c,'paste',lambda *args,**kwargs:(calls.append((args,kwargs)) or 'receipt'))
    monkeypatch.setattr(windows,'paste_verified',lambda *args:True)
    finish(c)
    assert len(calls)==1 and calls[0][1]['verify'] and c.delivery is not None
    assert not c.result_bubble.isVisible() and not c.preview.isVisible() and not c.copied
    c.callbacks.pop(0)()
    assert c.delivery is None and not c.result_bubble.isVisible() and not c.bubble.isVisible()
    assert c.store.rows()[0]['raw']=='Original transcript' and c.store.rows()[0]['final']=='Complete written text.'


@pytest.mark.parametrize('review',[ReviewAssessment(True,('Qelora',),True),ReviewAssessment(False,(),False)])
def test_uncertainty_or_unassessed_prose_requires_manual_review(controller,monkeypatch,review):
    c=controller
    monkeypatch.setattr(c,'paste',lambda *args,**kwargs:pytest.fail('Uncertain content inserted'))
    finish(c,ReviewedText('Keep Qelora.',review=review))
    assert c.result_bubble.isVisible() and 'Review wording' in c.result_bubble.status.text()
    assert not c.copied
    c.result_bubble.edit_result()
    assert c.preview.isVisible() and not c.result_bubble.isVisible()
    c.preview.result.setPlainText('Edited complete text.')
    c.preview.copy_result()
    assert c.copied==['Edited complete text.'] and not c.preview.isVisible()


def test_rejected_or_unconfirmed_paste_shows_full_copy_fallback(controller,monkeypatch):
    c=controller
    monkeypatch.setattr(c,'paste',lambda *args,**kwargs:'receipt')
    monkeypatch.setattr(windows,'paste_verified',lambda *args:False)
    finish(c)
    assert not c.result_bubble.isVisible()
    for _ in range(3):c.callbacks.pop(0)()
    assert c.delivery is None and c.result_bubble.isVisible() and not c.copied
    assert 'could not be confirmed' in c.result_bubble.status.text()
    c.result_bubble.copy_result()
    assert c.copied==['Complete written text.'] and not c.result_bubble.isVisible()


def test_no_editable_target_or_immediate_paste_error_shows_copy_fallback(controller,monkeypatch):
    c=controller
    monkeypatch.setattr(c,'paste',lambda *args,**kwargs:(_ for _ in ()).throw(RuntimeError('Clipboard busy')))
    finish(c)
    assert c.result_bubble.isVisible() and 'Clipboard busy' in c.result_bubble.status.text()
    assert not c.copied
    monkeypatch.setattr(windows,'valid',lambda target:False)
    finish(c)
    assert c.result_bubble.isVisible() and 'target' in c.result_bubble.status.text()


def test_disabled_cleanup_can_insert_without_an_llm_assessment(controller,monkeypatch):
    c=controller;calls=[]
    monkeypatch.setattr(c,'paste',lambda *args,**kwargs:(calls.append(True) or 'receipt'))
    finish(c,'Raw ASR text.',polish=False)
    assert calls==[True] and c.delivery is not None and not c.result_bubble.isVisible()


@pytest.mark.parametrize('change',['input_epoch','raw_hook'])
def test_input_since_recording_blocks_delivery_even_before_queued_focus_signal(controller,monkeypatch,change):
    c=controller
    # The raw hook can advance before its Qt signal marks the session changed.
    session=Session('听写',dict(c.store.config,demo=False),object(),raw='Original transcript')
    c.session=session
    if change=='input_epoch':c.input_epoch=1
    else:monkeypatch.setattr(type(c.keys),'input_guard',property(lambda keys:(1,0)))
    monkeypatch.setattr(windows,'prepare_paste',lambda *args:pytest.fail('Stale session reached field'))
    c.receive(session.id,'result',ReviewedText('Complete written text.',review=ReviewAssessment(False,(),True)))
    assert c.result_bubble.isVisible() and c.delivery is None
    assert 'Input changed' in c.result_bubble.status.text()


def test_old_confirmation_cannot_hide_or_show_over_a_new_recording(controller,monkeypatch):
    c=controller
    monkeypatch.setattr(c,'paste',lambda *args,**kwargs:'receipt')
    finish(c);old=c.callbacks.pop(0)
    c.clear_delivery()
    new=Session('听写',c.store.config,None,phase='录音');c.session=new;c.bubble.state('录音')
    old()
    assert c.session is new and c.bubble.isVisible() and not c.result_bubble.isVisible()


def test_history_failure_is_reported_even_when_insertion_confirmed(controller,monkeypatch):
    c=controller
    monkeypatch.setattr(c,'_save_history',lambda *args,**kwargs:False)
    monkeypatch.setattr(c,'paste',lambda *args,**kwargs:'receipt')
    monkeypatch.setattr(windows,'paste_verified',lambda *args:True)
    finish(c);c.callbacks.pop(0)()
    assert c.result_bubble.isVisible() and 'History could not be saved' in c.result_bubble.status.text()


def test_copy_failure_keeps_result_available(controller,monkeypatch):
    c=controller
    finish(c,ReviewedText('Keep Qelora.',review=ReviewAssessment(True,('Qelora',),True)))
    class Busy:
        def setText(self,text):raise RuntimeError('Busy')
    monkeypatch.setattr(QApplication,'clipboard',staticmethod(lambda:Busy()))
    c.result_bubble.copy_result()
    assert c.result_bubble.isVisible() and c.result_bubble.text=='Keep Qelora.'
    assert 'Copy failed' in c.result_bubble.status.text()


def test_delivery_setting_is_enabled_by_default_and_can_be_disabled(controller):
    c=controller
    assert c.store.config['smart_delivery'] is True
    assert c.window.fields['smart_delivery'].isChecked() is True
    assert storage.validated_config({'smart_delivery':False})['smart_delivery'] is False


def test_native_confirmed_insertion_does_not_access_even_a_rich_clipboard(controller,monkeypatch):
    c=controller
    monkeypatch.setattr(windows,'prepare_paste',lambda *args:'receipt')
    monkeypatch.setattr(windows,'paste_ready',lambda *args:True)
    calls=[]
    monkeypatch.setattr(windows,'insert_native_edit',lambda *args,**kwargs:(calls.append(args) or True))
    monkeypatch.setattr(windows,'ClipboardTransaction',lambda:pytest.fail('Native insertion touched clipboard'))
    target=object()
    assert c.paste('Full text.',target,verify=True)=='receipt'
    assert calls==[(target,'Full text.')] and c.clip_tx is None


def test_changed_caret_blocks_native_insertion_and_clipboard_paste(controller,monkeypatch):
    c=controller
    monkeypatch.setattr(windows,'prepare_paste',lambda *args:'receipt')
    monkeypatch.setattr(windows,'paste_ready',lambda *args:False)
    monkeypatch.setattr(windows,'insert_native_edit',lambda *args:pytest.fail('Changed caret inserted'))
    monkeypatch.setattr(windows,'ClipboardTransaction',lambda:pytest.fail('Changed caret touched clipboard'))
    with pytest.raises(RuntimeError,match='cursor or input changed'):c.paste('Full text.',object(),verify=True)

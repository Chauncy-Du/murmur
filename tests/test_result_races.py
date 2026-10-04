"""Late recorder and clipboard callbacks use isolated, synthetic sessions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from murmur import app as app_module, storage, windows
from murmur.app import Controller, Session
from murmur.providers import AskResult


class NoWorker:
    def __init__(self, *args, **kwargs): pass
    def start(self): pass


@pytest.fixture
def controller(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'credential', lambda *args: '')
    monkeypatch.setattr(app_module, 'credential', lambda *args: '')
    monkeypatch.setattr(storage, 'DEFAULT_OFFLINE_MODELS_ROOT', tmp_path / 'models')
    monkeypatch.setattr(windows, 'prepare_text_context', lambda: None)
    monkeypatch.setattr(windows, 'target', lambda: None)
    monkeypatch.setattr(windows, 'own_target', lambda target: False)
    monkeypatch.setattr(windows, 'text_context', lambda target: windows.TextContext())
    monkeypatch.setattr(app_module.threading, 'Thread', NoWorker)
    import sounddevice
    monkeypatch.setattr(sounddevice, 'query_devices', lambda: [])
    app = QApplication.instance() or QApplication([])
    copied = []
    class Clipboard:
        def setText(self, text): copied.append(text)
        def text(self): return copied[-1] if copied else ''
    monkeypatch.setattr(QApplication, 'clipboard', staticmethod(lambda: Clipboard()))
    c = Controller(app, storage.Store(tmp_path / 'data'), False)
    c.monitor.stop()
    c.fixture_copied = copied
    yield c
    c.session = None
    for widget in (c.window, c.bubble, c.result_bubble, c.preview, c.tray): widget.hide()
    c.store.db.close()


@pytest.mark.parametrize('assistant', [False, True])
@pytest.mark.parametrize('outcome', ['success', 'error', 'cancel'])
def test_late_partial_cannot_shorten_final_transcript_or_recovery(controller, assistant, outcome):
    c = controller
    s = Session('随便问' if assistant else '听写', dict(c.store.config, demo=True), None,
                assistant=assistant, phase='识别')
    c.session = s
    complete = 'Public complete original transcript, including its final sentence.'
    c.receive(s.id, 'partial', 'Public complete original')
    c.receive(s.id, 'recognized', complete)
    c.receive(s.id, 'phase', '整理')
    before = (s.completed_steps, c.bubble.progress.percentage, c.bubble.status.text())
    c.receive(s.id, 'partial', 'Public complete')
    assert s.raw == complete
    assert (s.completed_steps, c.bubble.progress.percentage, c.bubble.status.text()) == before
    class FinalizedRecorder:
        duration = 1
        raw = 'An older recorder partial'
        def abort(self): self.raw = 'A shorter partial frozen at abort'
    s.recorder = FinalizedRecorder()
    if outcome == 'cancel':
        c.cancel()
    elif outcome == 'error':
        c.receive(s.id, 'error', 'Synthetic refinement failed')
        assert c.result_bubble.text == complete
    else:
        result = AskResult('answer', 'Public final answer') if assistant else 'Public final result'
        c.receive(s.id, 'result', result)
    assert c.session is None
    row = c.store.rows()[0]
    assert row['raw'] == complete
    if outcome != 'success': assert row['final'] == complete
    c.receive(s.id, 'partial', 'An even later partial')
    assert c.store.rows()[0]['raw'] == complete
    assert c.fixture_copied == []


@pytest.mark.parametrize('phase', ['启动', '录音', '整理'])
@pytest.mark.parametrize('failure', [OSError, windows.ClipboardBusy])
def test_old_clipboard_restore_failure_cannot_hide_next_session(controller, phase, failure):
    c = controller
    s = Session('听写', dict(c.store.config, demo=True), None, phase=phase)
    c.session = s
    c.configure_progress(s)
    c.sync_controls()
    c.bubble.state(phase, 'Public current session', True)
    if phase == '整理':
        s.completed_steps = 1
        c.update_progress(s)
    before = (c.bubble._state_name, c.bubble.status.text(), c.bubble.progress.percentage,
              c.bubble.wave.active, c.window.record_button.text())
    class OldTransaction:
        def restore(self, expected): raise failure('Synthetic previous-session failure')
    old = OldTransaction()
    c.clip_tx = old
    c.restore_clipboard(old, attempt=3)
    assert c.session is s
    assert c.bubble.isVisible()
    assert (c.bubble._state_name, c.bubble.status.text(), c.bubble.progress.percentage,
            c.bubble.wave.active, c.window.record_button.text()) == before
    assert c.clip_tx is None
    assert 'Clipboard restoration failed' in c.window.home_status.text()
    assert not c.preview.isVisible() and c.fixture_copied == []


def test_cancel_then_next_recording_ignores_old_result_and_morph_completion(controller):
    c = controller
    old = Session('听写', dict(c.store.config, demo=True), None, raw='Public earlier transcript', phase='整理')
    c.session = old
    c.receive(old.id, 'error', 'Synthetic earlier request failed')
    animation = c.result_bubble._morph
    assert animation is not None
    animation.pause()
    animation.setCurrentTime(100)
    c.result_bubble.dismiss_button.click()
    c.toggle()
    new = c.session
    c.receive(new.id, 'started', None)
    c.receive(old.id, 'partial', 'Late old partial')
    c.receive(old.id, 'result', 'Late old result')
    QTest.qWait(280)
    assert c.session is new and new.phase == '录音'
    assert c.bubble.isVisible() and c.bubble.wave.active
    assert not c.result_bubble.isVisible() and c.result_bubble._morph is None
    assert len(c.store.rows()) == 1

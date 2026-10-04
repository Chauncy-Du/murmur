"""Honest completed-step reporting with only synthetic text and isolated stores."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import copy
import pytest
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
    monkeypatch.setattr(windows, 'prepare_text_context', lambda: None)
    monkeypatch.setattr(windows, 'target', lambda: None)
    monkeypatch.setattr(windows, 'own_target', lambda target: False)
    monkeypatch.setattr(windows, 'text_context', lambda target: windows.TextContext())
    monkeypatch.setattr(app_module.threading, 'Thread', NoWorker)
    app = QApplication.instance() or QApplication([])
    store = storage.Store(tmp_path)
    store.config['demo'] = True
    c = Controller(app, store, False)
    progress = []
    original = c.bubble.set_progress

    def report(step, completed, total):
        progress.append((step, completed, total))
        original(step, completed, total)

    monkeypatch.setattr(c.bubble, 'set_progress', report)
    c.progress_reports = progress
    yield c
    c.session = None
    c.monitor.stop()
    for widget in (c.tray, c.bubble, c.result_bubble, c.preview, c.window): widget.hide()
    store.db.close()


@pytest.mark.parametrize('mode,polish,steps', [
    ('听写', True, ('Transcribe', 'Polish')),
    ('听写', False, ('Transcribe',)),
    ('翻译', False, ('Transcribe', 'Translate')),
    ('指令', True, ('Transcribe',)),
    ('随便问', True, ('Transcribe', 'Respond')),
])
def test_voice_steps_advance_only_after_actual_recognition_and_valid_result(controller, mode, polish, steps):
    c = controller
    c.store.config['polish'] = polish
    c.toggle(mode)
    s = c.session
    assert s.steps == steps and not c.progress_reports
    c.stop()
    assert s.phase == '等待停止' and not c.progress_reports
    c.receive(s.id, 'started', None)
    assert c.progress_reports == [(steps[0], 0, len(steps))]
    c.receive(s.id, 'partial', 'Partial fixture')
    assert len(c.progress_reports) == 1
    c.receive(s.id, 'recognized', 'Complete fixture')
    assert c.progress_reports[-1] == (steps[-1], min(1, len(steps)-1), len(steps))
    if len(steps) > 1:
        c.receive(s.id, 'phase', '整理')
        assert c.bubble.status.text().startswith('<span')  # Demo remains marked.
        assert steps[-1] in c.bubble.status.text() and 'Thinking' not in c.bubble.status.text()
    result = AskResult('answer', 'Valid fixture answer') if s.assistant else 'Valid fixture text'
    c.receive(s.id, 'result', result)
    assert c.session is None
    assert c.progress_reports[-1] == (steps[-1], len(steps), len(steps))
    if mode == '指令': assert c.preview.command.text() == result


@pytest.mark.parametrize('mode,step', [('润色','Refine'), ('翻译','Translate'), ('总结','Summarize'), ('扩写','Expand'), ('自定义','Edit')])
def test_selection_actions_have_one_actual_processing_step(controller, mode, step):
    c = controller
    c.edit('Selected fixture', mode, 'Edit the fixture')
    s = c.session
    assert s.steps == (step,)
    assert c.progress_reports == [(step, 0, 1)]
    c.receive(s.id, 'result', 'Edited fixture')
    assert c.progress_reports == [(step, 0, 1), (step, 1, 1)]


@pytest.mark.parametrize('assistant', [False, True])
@pytest.mark.parametrize('event', ['error', 'cancel', 'invalid'])
def test_failure_cancel_and_late_callbacks_never_complete_progress(controller, assistant, event):
    c = controller
    c.toggle('随便问' if assistant else '听写')
    s = c.session
    c.receive(s.id, 'started', None)
    c.stop()
    c.receive(s.id, 'recognized', 'Preserved fixture')
    if event == 'cancel': c.cancel()
    elif event == 'error': c.receive(s.id, 'error', 'Fixture request failed')
    else: c.receive(s.id, 'result', AskResult('invalid','Fixture') if assistant else '')
    before = list(c.progress_reports)
    c.receive(s.id, 'recognized', 'Late fixture')
    c.receive(s.id, 'phase', '整理')
    c.receive(s.id, 'result', AskResult('answer','Late fixture') if assistant else 'Late fixture')
    assert c.progress_reports == before
    assert all(done < total for _, done, total in before)
    assert c.store.rows()[0]['raw'] == 'Preserved fixture'


def test_success_completes_before_automatic_clipboard_copy(controller, monkeypatch):
    c = controller
    cfg = dict(c.store.config, demo=False)
    s = Session('听写', cfg, None, raw='Public original', phase='整理')
    c.session = s
    writes = []

    class Clipboard:
        def setText(self, text):
            assert c.progress_reports[-1] == ('Polish', 2, 2)
            writes.append(text)
        def text(self): return writes[-1]

    monkeypatch.setattr(c.app, 'clipboard', lambda: Clipboard())
    c.receive(s.id, 'result', 'Public result')
    assert writes == ['Public result']


def test_canceled_session_with_late_error_does_not_show_complete(controller):
    c = controller
    s = Session('听写', copy.deepcopy(c.store.config), None, raw='Preserved fixture')
    c.session = s
    s.cancel.set()
    c.receive(s.id, 'error', 'Startup fixture failed')
    assert not c.progress_reports and c.session is None


def test_old_started_callback_cannot_rewind_processing(controller):
    c = controller
    c.toggle()
    s = c.session
    c.receive(s.id, 'started', None)
    c.stop()
    c.receive(s.id, 'recognized', 'Fixture')
    c.receive(s.id, 'phase', '整理')
    before = list(c.progress_reports)
    c.receive(s.id, 'started', None)
    assert s.phase == '整理' and c.progress_reports == before

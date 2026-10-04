"""Results stay distinct from selections across real controller transitions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication, QPushButton, QToolButton
from murmur import app as app_module, storage, windows
from murmur.app import Controller, Session
from murmur.providers import AskResult


@pytest.fixture
def controller(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'credential', lambda *args: '')
    monkeypatch.setattr(app_module, 'credential', lambda *args: '')
    monkeypatch.setattr(windows, 'prepare_text_context', lambda: None)
    app = QApplication.instance() or QApplication([])
    c = Controller(app, storage.Store(tmp_path), False)
    c.monitor.stop()
    yield c
    c.session = None
    for widget in (c.window, c.bubble, c.result_bubble, c.preview, c.tray):
        widget.hide()
    c.store.db.close()


@pytest.mark.parametrize('assistant', [False, True])
def test_result_editor_keeps_context_after_generation_and_never_reuses_old_selection(controller, monkeypatch, assistant):
    c = controller
    c.result_context = ('Public request', 'Public result', 'Public source', 'answer') if assistant else ('Public original', 'Public result')
    c.selection_target = object()
    c.selection_bookmark = object()
    c.edit_result('Public result')
    assert c.preview.editor_context == ('assistant' if assistant else 'result')
    assert c.preview.replace_button.isHidden()
    # Keep the actual controller dispatch but defer its worker for this fixture.
    monkeypatch.setattr(app_module.threading, 'Thread', lambda **kw: type('DeferredWorker', (), {'start': lambda self: None})())
    c.edit(c.preview.raw.toPlainText(), '润色', '')
    s = c.session
    assert s.editor_context == c.preview.editor_context
    c.receive(s.id, 'result', 'Public regenerated result')
    assert c.session is None
    assert c.preview.title_label.text() == ('Ask Anything result' if assistant else 'Edit result')
    assert c.preview.result.toPlainText() == 'Public regenerated result'
    assert c.preview.replace_button.isHidden() and not c.preview._replacement_allowed
    c.open_preview()
    assert c.preview.editor_context == 'selection'
    assert not c.preview.replace_button.isHidden()


def test_unconfirmed_ask_target_keeps_short_status_and_full_reason(controller):
    c = controller
    s = Session('随便问', dict(c.store.config, demo=False), None,
                assistant=True, raw='Public request', phase='整理')
    c.session = s
    c.receive(s.id, 'result', AskResult('insert', 'Public draft'))
    assert c.session is None
    assert c.result_bubble.status.text() == 'Ask Anything · Preview only'
    assert 'Target or selection could not be confirmed' in c.result_bubble.status.toolTip()
    assert c.result_bubble.preview.toPlainText() == 'Public draft'


def test_history_long_entry_and_menu_open_the_same_complete_session(controller, monkeypatch):
    c = controller
    text = 'Public long transcript. ' * 50
    c.store.add('long-entry', '听写', text, text, 5, .1, False)
    c.window.navigate(1)
    links = c.window.stack.widget(1).findChildren(QPushButton, 'history_full_text')
    assert len(links) == 1 and links[0].text() == 'View full text'
    opened = []
    monkeypatch.setattr(c.window, 'show_record', opened.append)
    links[0].click()
    menu = next(w.menu() for w in c.window.stack.widget(1).findChildren(QToolButton) if w.toolTip() == 'Session options')
    assert menu.actions()[0].text() == 'Open session'
    menu.actions()[0].trigger()
    assert len(opened) == 2
    assert all(row['session'] == 'long-entry' and row['final'] == text for row in opened)

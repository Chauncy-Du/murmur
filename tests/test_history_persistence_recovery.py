"""A failed history write must not strand a completed or cancelled session."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import sqlite3
from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QApplication
from murmur import app as app_module, storage, windows
from murmur.app import Controller, Session
from murmur.providers import AskResult


@pytest.fixture
def controller(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'credential', lambda *args: '')
    monkeypatch.setattr(app_module, 'credential', lambda *args: '')
    monkeypatch.setattr(windows, 'prepare_text_context', lambda: None)
    import sounddevice
    monkeypatch.setattr(sounddevice, 'query_devices', lambda: [])
    app = QApplication.instance() or QApplication([])
    c = Controller(app, storage.Store(tmp_path), False)
    c.monitor.stop()
    yield c
    c.session = None
    for window in (c.window, c.bubble, c.result_bubble, c.preview, c.tray):
        window.hide()
    c.store.db.close()


def fail_writes(c, monkeypatch, exception=OSError):
    def fail(*args, **kwargs):
        raise exception('Fixture sensitive filesystem path')
    monkeypatch.setattr(c.store, 'add', fail)
    # A write-failed database must not need another successful read to show
    # the result. This also models a database that was closed or is locked.
    monkeypatch.setattr(c.window, 'refresh', lambda: pytest.fail('Failed database was refreshed'))


@pytest.mark.parametrize('exception', [OSError, sqlite3.OperationalError])
@pytest.mark.parametrize('mode', ['听写', '润色'])
def test_completed_result_survives_history_write_failure(controller, monkeypatch, exception, mode):
    c = controller
    s = Session(mode, dict(c.store.config, demo=True), None, raw='Fixture original', phase='整理')
    c.session = s; c.sync_controls()
    fail_writes(c, monkeypatch, exception)
    monkeypatch.setattr(c, 'paste', lambda *args, **kw: pytest.fail('Demo result was pasted'))
    c.receive(s.id, 'result', 'Fixture completed result')
    assert c.session is None and c.window.record_button.isEnabled()
    assert not c.preview.result.isReadOnly()
    assert c.preview.result.toPlainText() == 'Fixture completed result'
    assert 'History could not be saved' in c.preview.notice.text()
    assert 'Fixture sensitive' not in c.window.settings_status.text()
    if mode == '听写':
        assert c.result_bubble.isVisible() and 'History could not be saved' in c.result_bubble.status.toolTip()
    else:
        assert c.preview.isVisible()


def test_processing_error_and_history_error_keep_latest_partial_without_insertion(controller, monkeypatch):
    c = controller
    recorder = SimpleNamespace(duration=2, raw='Latest partial original', abort=lambda: None)
    s = Session('听写', dict(c.store.config, demo=False), None, recorder=recorder, raw='Earlier partial')
    c.session = s; c.sync_controls()
    fail_writes(c, monkeypatch)
    monkeypatch.setattr(c, 'paste', lambda *args, **kw: pytest.fail('Failed partial was pasted'))
    c.receive(s.id, 'error', 'Speech service unavailable')
    assert c.session is None and c.window.record_button.isEnabled()
    assert not c.preview.isVisible() and c.preview.result.toPlainText() == recorder.raw
    assert c.result_bubble.isVisible() and c.result_bubble.text == recorder.raw
    assert 'Speech service unavailable' in c.preview.notice.text()
    assert 'History could not be saved' in c.preview.notice.text()


def test_instruction_result_survives_history_failure(controller, monkeypatch):
    c = controller
    s = Session('语音指令', dict(c.store.config, demo=True), None, raw='Fixture instruction', instruction=True)
    c.session = s; c.sync_controls(); fail_writes(c, monkeypatch)
    c.receive(s.id, 'result', 'Fixture instruction result')
    assert c.session is None and c.preview.isVisible()
    assert c.preview.command.text() == 'Fixture instruction result'
    assert c.preview.go.isEnabled()
    assert 'History could not be saved' in c.preview.notice.text()


@pytest.mark.parametrize('error', [False, True])
def test_ask_result_or_error_survives_history_failure(controller, monkeypatch, error):
    c = controller
    s = Session('随便问', dict(c.store.config, demo=True), None, raw='Fixture question', assistant=True,
                context=windows.TextContext('selection', 'Fixture selected source'))
    c.session = s; c.sync_controls(); fail_writes(c, monkeypatch, sqlite3.OperationalError)
    monkeypatch.setattr(c, 'paste', lambda *args, **kw: pytest.fail('Demo or error was pasted'))
    c.receive(s.id, 'error' if error else 'result', 'Assistant unavailable' if error else AskResult('answer', 'Fixture answer'))
    assert c.session is None and c.window.record_button.isEnabled()
    assert c.result_bubble.text == ('Fixture question' if error else 'Fixture answer')
    assert c.result_bubble.isVisible()
    assert 'History could not be saved' in c.result_bubble.status.toolTip()
    assert c.result_context[:3] == ('Fixture question', c.result_bubble.text, 'Fixture selected source')


def test_cancel_history_failure_recovers_controls_and_preserves_raw_without_late_overwrite(controller, monkeypatch):
    c = controller
    s = Session('听写', dict(c.store.config, demo=True), None, raw='Fixture cancelled original', phase='识别')
    c.session = s; c.sync_controls(); fail_writes(c, monkeypatch)
    c.cancel()
    assert c.session is None and s.cancel.is_set() and c.window.record_button.isEnabled()
    assert not c.preview.isVisible() and c.preview.result.toPlainText() == s.raw
    assert c.result_bubble.isVisible() and c.result_bubble.text == s.raw
    assert 'History could not be saved' in c.preview.notice.text()
    c.receive(s.id, 'result', 'Late overwrite')
    c.cancel()  # Repeated global/local cancellation is still harmless.
    assert c.preview.result.toPlainText() == s.raw


def test_failed_transaction_is_rolled_back_before_another_session(controller, monkeypatch):
    c = controller
    real_add = c.store.add
    original_words = c.store.words()
    def failed_transaction(*args, **kwargs):
        c.store.db.execute("INSERT INTO dictionary VALUES('fixture-uncommitted','手动','2026-01-01')")
        raise sqlite3.OperationalError('Fixture failed transaction')
    monkeypatch.setattr(c.store, 'add', failed_transaction)
    assert c._save_history('id', '听写', 'raw', 'final', 0, 0, True) is False
    assert c.store.words() == original_words
    monkeypatch.setattr(c.store, 'add', real_add)
    assert c._save_history('next-id', '听写', 'raw', 'final', 0, 0, True)
    assert len(c.store.rows()) == 1


def test_actual_sqlite_closed_database_does_not_hide_completed_result(controller):
    c = controller
    s = Session('听写', dict(c.store.config, demo=True), None, raw='Fixture original', phase='整理')
    c.session = s; c.sync_controls()
    c.store.db.close()  # Exercise an actual sqlite3.Error, not only a mock.
    c.receive(s.id, 'result', 'Fixture completed result')
    assert c.session is None and c.window.record_button.isEnabled()
    assert c.result_bubble.isVisible() and c.result_bubble.text == 'Fixture completed result'
    assert 'History could not be saved' in c.window.settings_status.text()
    c.cancel()
    assert c.session is None

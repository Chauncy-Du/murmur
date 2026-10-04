"""Keep recognizer output separate from edited text using synthetic sessions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QTabWidget
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
    for widget in (c.window, c.bubble, c.result_bubble, c.preview, c.tray):
        widget.hide()
    c.store.db.close()


@pytest.mark.parametrize('mode', ['听写', '翻译', '随便问'])
@pytest.mark.parametrize('fails', [False, True])
def test_voice_pipeline_keeps_exact_asr_before_processing(controller, monkeypatch, mode, fails):
    c = controller
    original = '嗯，这个 synthetic sample，就是先比较 A，不，是比较 B。\n还需要检查误差。'
    final = 'Compare sample B, then check the uncertainty.'
    context = windows.TextContext('selection', 'Synthetic selected reference.') if mode == '随便问' else None
    seen = []

    class Recorder:
        raw = original
        duration = 2
        def stop(self): return self.raw
        def abort(self): pass

    def process(raw, *args, **kwargs):
        seen.append(raw)
        if fails:
            raise RuntimeError('Synthetic model failure')
        return AskResult('answer', final) if mode == '随便问' else final

    monkeypatch.setattr(app_module, 'ask' if mode == '随便问' else 'transform', process)
    s = Session(mode, dict(c.store.config, demo=True, polish=True), None,
                recorder=Recorder(), raw='Earlier synthetic partial', phase='录音',
                assistant=mode == '随便问', context=context)
    c.session = s
    c.stop()
    for _ in range(100):
        if c.session is None:
            break
        QTest.qWait(10)

    assert c.session is None and seen == [original]
    row = c.store.rows()[0]
    assert row['raw'] == original
    assert row['final'] == (original if fails else final)
    assert row['context'] == (context.text if context else '')
    assert bool(row['error']) is fails

    # Retries and later edits cannot replace a previously saved recognizer result.
    c.store.add(s.id, mode, 'Changed synthetic original', 'Changed synthetic result', 0, 0, True)
    assert len(c.store.rows()) == 1 and c.store.rows()[0] == row


def test_followup_edit_keeps_original_session_pair(controller, monkeypatch):
    c = controller
    original = '嗯，先比较 synthetic A，再看误差。'
    first_result = '先比较 synthetic A，再检查误差。'
    s = Session('听写', dict(c.store.config, demo=True), None, raw=original, phase='整理')
    c.session = s
    c.receive(s.id, 'result', first_result)
    first = c.store.rows()[0]
    c.edit_result(first_result)
    c.preview.raw.setPlainText('An intentional synthetic revision.')
    monkeypatch.setattr(app_module, 'transform', lambda *args, **kwargs: 'A polished synthetic revision.')
    c.edit(c.preview.raw.toPlainText(), '润色', '')
    for _ in range(100):
        if c.session is None:
            break
        QTest.qWait(10)
    assert c.session is None
    rows = c.store.rows()
    assert len(rows) == 2
    assert next(row for row in rows if row['session'] == s.id) == first
    assert first['raw'] == original and first['final'] == first_result


@pytest.mark.parametrize('mode', ['听写', '翻译', '问答'])
def test_short_changed_history_offers_both_complete_versions(controller, monkeypatch, mode):
    c = controller
    original = '嗯，这个 synthetic input，请比较 B。'
    final = 'Compare synthetic sample B.'
    c.store.add('changed', mode, original, final, 2, .1, False, context='Synthetic selected source.' if mode == '问答' else '')
    c.window.navigate(1)
    links = c.window.stack.widget(1).findChildren(QPushButton, 'history_compare')
    assert len(links) == 1 and links[0].text() == 'Compare original and result'
    captured = []

    def inspect(dialog):
        tabs = dialog.findChild(QTabWidget)
        captured.extend((tabs.tabText(i), tabs.widget(i).toPlainText()) for i in range(tabs.count()))

    monkeypatch.setattr(QDialog, 'exec', inspect)
    links[0].click()
    assert captured[:2] == [('Final output', final), ('Spoken request' if mode == '问答' else 'Original transcript', original)]
    if mode == '问答':
        assert captured[2] == ('Selected source', 'Synthetic selected source.')


def test_unchanged_or_failed_empty_session_does_not_offer_comparison(controller):
    c = controller
    c.store.add('unchanged', '听写', 'Synthetic unchanged text.', 'Synthetic unchanged text.', 1, 0, False)
    c.store.add('empty', '听写', '', '', 0, 0, False, error='Synthetic recognition failure')
    c.window.navigate(1)
    assert not c.window.stack.widget(1).findChildren(QPushButton, 'history_compare')

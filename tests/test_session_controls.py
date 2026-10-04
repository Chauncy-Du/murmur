"""Recording controls stay truthful and prevent edits during active work."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from murmur.dashboard import MainWindow
from murmur.storage import Store
from murmur.ui import Preview


def test_home_and_history_record_controls_follow_session(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Store(tmp_path))
    window.navigate(1)
    window.set_session_state('启动', '听写')
    assert window.record_button.text() == 'Stop recording'
    assert window.history_record_button.text() == 'Stop recording'
    assert window.record_button.isEnabled()
    assert not window.translation_button.isEnabled()
    assert not window.edit_selection_button.isEnabled()
    # Rebuilding the empty state during an active session preserves its state.
    window.refresh()
    assert window.history_record_button.text() == 'Stop recording'
    window.set_session_state('识别', '听写')
    assert window.record_button.text() == 'Processing…'
    assert not window.record_button.isEnabled()
    assert not window.history_record_button.isEnabled()
    window.set_session_state('result', None)
    assert window.record_button.text() == 'Record to preview'
    assert window.record_button.isEnabled() and window.translation_button.isEnabled()
    window.set_session_state('录音', '翻译')
    assert window.translation_button.text() == 'Stop recording'
    assert window.translation_button.isEnabled()
    assert not window.record_button.isEnabled()
    window.set_session_state('整理', '翻译')
    assert window.translation_button.text() == 'Processing…'
    assert not window.translation_button.isEnabled()
    window.set_session_state('cancel')
    assert window.translation_button.text() == 'Translate'
    assert window.history_record_button.isEnabled()
    window.hide()


def test_preview_freezes_edits_and_actions_until_session_finishes():
    app = QApplication.instance() or QApplication([])
    preview = Preview()
    preview.show_text('Source', 'Previous result', replace=True)
    app.clipboard().setText('Existing clipboard')
    applied = []
    preview.replace.connect(applied.append)
    preview.set_session_state('整理', '润色')
    assert preview.raw.isReadOnly() and preview.result.isReadOnly()
    assert not preview.command.isEnabled() and not preview.mode.isEnabled()
    assert not preview.go.isEnabled() and not preview.voice_button.isEnabled()
    assert not preview.copy_button.isEnabled() and not preview.replace_button.isEnabled()
    preview.copy_result()
    preview.apply_result()
    assert app.clipboard().text() == 'Existing clipboard' and applied == []
    # Programmatic worker results may update the display while edits are frozen.
    preview.result.setPlainText('New result')
    assert not preview.copy_button.isEnabled()
    preview.set_session_state('error')
    assert not preview.raw.isReadOnly() and not preview.result.isReadOnly()
    assert preview.command.isEnabled() and preview.go.isEnabled()
    assert preview.copy_button.isEnabled() and preview.replace_button.isEnabled()
    preview.set_session_state('录音', '指令')
    assert preview.voice_button.isEnabled()
    assert preview.voice_button.toolTip() == 'Stop recording'
    assert not preview.command.isEnabled()
    preview.set_session_state('识别', '指令')
    assert not preview.voice_button.isEnabled()
    preview.set_session_state(None)
    assert preview.voice_button.isEnabled() and preview.command.isEnabled()
    preview.hide()


def test_mainwindow_escape_cancels_busy_session_from_child_focus(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Store(tmp_path))
    sent = []
    window.cancel.connect(lambda: sent.append(True))
    window.show()
    window.navigate(1)
    window.activateWindow()
    window.search.setFocus()
    window.set_session_state('整理', '听写')
    app.processEvents()
    QTest.keyClick(window.search, Qt.Key_Escape)
    app.processEvents()
    assert sent == [True]
    assert window.isVisible()
    window.set_session_state(None)
    QTest.keyClick(window.search, Qt.Key_Escape)
    app.processEvents()
    assert sent == [True]
    window.hide()


def test_preview_escape_cancels_once_without_parent_or_hiding(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Store(tmp_path))
    preview = Preview(window)
    parent_sent, preview_sent = [], []
    window.cancel.connect(lambda: parent_sent.append(True))
    preview.cancel.connect(lambda: preview_sent.append(True))
    window.set_session_state('整理', '润色')
    window.show()
    preview.show_text('Source', 'Previous result', replace=True)
    preview.set_session_state('整理', '润色')
    preview.activateWindow()
    preview.result.setFocus()
    app.processEvents()
    QTest.keyClick(preview.result, Qt.Key_Escape)
    app.processEvents()
    assert preview_sent == [True]
    assert parent_sent == []
    assert preview.isVisible()
    preview.set_session_state(None)
    QTest.keyClick(preview.result, Qt.Key_Escape)
    app.processEvents()
    assert not preview.isVisible()
    assert preview_sent == [True]
    assert parent_sent == []
    window.hide()

"""Preview actions must never clear the clipboard with an empty result."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication
from murmur.ui import Preview


def test_empty_results_preserve_clipboard_and_do_not_apply():
    app = QApplication.instance() or QApplication([])
    preview = Preview()
    sent = []
    preview.replace.connect(sent.append)
    app.clipboard().setText('Existing clipboard content')
    preview.show_text('Original selection', '', replace=True)
    assert not preview.copy_button.isEnabled()
    assert not preview.replace_button.isEnabled()
    preview.copy_result()
    preview.apply_result()
    preview.result.setPlainText(' \n\t ')
    assert not preview.copy_button.isEnabled()
    assert not preview.replace_button.isEnabled()
    # The handlers themselves guard empty text, even if activation is stale.
    preview.copy_button.setEnabled(True)
    preview.copy_button.click()
    assert app.clipboard().text() == 'Existing clipboard content'
    assert sent == []
    preview.hide()


def test_manual_edits_update_actions_and_keep_target_requirement():
    app = QApplication.instance() or QApplication([])
    preview = Preview()
    sent = []
    preview.replace.connect(sent.append)
    preview.show_text('Original selection', 'Generated output', replace=True)
    assert preview.copy_button.isEnabled()
    assert preview.replace_button.isEnabled()
    preview.result.clear()
    assert not preview.copy_button.isEnabled()
    assert not preview.replace_button.isEnabled()
    preview.result.setPlainText('Manually revised output')
    assert preview.copy_button.isEnabled()
    assert preview.replace_button.isEnabled()
    preview.replace_button.click()
    assert sent == ['Manually revised output']
    preview.show_text('Another source', 'Preview only', replace=False)
    assert preview.copy_button.isEnabled()
    assert not preview.replace_button.isEnabled()
    preview.apply_result()
    assert sent == ['Manually revised output']
    preview.copy_button.click()
    assert app.clipboard().text() == 'Preview only'
    preview.hide()

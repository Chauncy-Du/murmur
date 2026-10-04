"""Result editing and short status copy remain distinct from selection edits."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtWidgets import QApplication, QPushButton
from PySide6.QtCore import QRect, Qt
from PySide6.QtTest import QTest
from murmur.ui import Preview, ResultBubble


@pytest.fixture
def preview():
    app = QApplication.instance() or QApplication([])
    widget = Preview()
    yield widget
    widget.hide()


def test_result_edit_hides_and_blocks_selection_replacement(preview):
    replaced = []
    preview.replace.connect(replaced.append)
    preview.show_text('Synthetic original', 'Synthetic result', replace=True, show=False, result_edit=True)
    assert preview.title_label.text() == 'Edit result'
    assert preview.windowTitle() == 'MurMur · Edit result'
    assert preview.original_label.text() == 'Original transcript'
    assert preview.raw.toPlainText() == 'Synthetic original'
    assert preview.result.toPlainText() == 'Synthetic result'
    assert preview.replace_button.isHidden()
    assert not preview._replacement_allowed
    assert preview.copy_button.isEnabled()
    preview.apply_result()
    assert not replaced
    preview.result.setPlainText('A manual revision')
    assert preview.copy_button.isEnabled() and not preview.replace_button.isEnabled()
    preview.set_session_state('整理', '润色')
    assert not preview.copy_button.isEnabled()
    preview.set_session_state('idle')
    assert preview.copy_button.isEnabled() and preview.replace_button.isHidden()


def test_assistant_editor_preserves_title_and_source_without_apply(preview):
    preview.show_text('Synthetic request and source', 'Synthetic answer', replace=True, show=False, assistant=True, result_edit=True)
    assert preview.title_label.text() == 'Ask Anything result'
    assert preview.windowTitle() == 'MurMur · Ask Anything'
    assert preview.original_label.text() == 'Spoken request and source'
    assert preview.replace_button.isHidden() and not preview._replacement_allowed


def test_selection_context_restores_visible_gated_apply(preview):
    preview.show_text('Original', 'Result', replace=True, show=False, result_edit=True)
    preview.show_text('Selected source', '', replace=True, show=False)
    assert preview.title_label.text() == 'Edit selection'
    assert preview.original_label.text() == 'Original'
    assert not preview.replace_button.isHidden()
    assert not preview.replace_button.isEnabled()
    preview.result.setPlainText('Revised selection')
    assert preview.replace_button.isEnabled()
    preview.show_text('Selected source', 'Preview only', replace=False, show=False)
    assert not preview.replace_button.isHidden() and not preview.replace_button.isEnabled()


def test_short_visible_status_retains_full_tooltip_and_copy_resets_both(monkeypatch):
    app = QApplication.instance() or QApplication([])
    copied = []
    class Clipboard:
        def setText(self, text): copied.append(text)
    monkeypatch.setattr(QApplication, 'clipboard', lambda: Clipboard())
    widget = ResultBubble({})
    try:
        full_status = 'Ask Anything · Target or selection could not be confirmed · Copy to use'
        widget.show_result('Synthetic full output', demo=True, status=full_status, status_summary='Ask Anything · Preview only')
        assert widget.status.text() == 'Demo · Ask Anything · Preview only'
        assert widget.status.toolTip() == 'Demo · ' + full_status
        assert widget.width() == 360 and widget.height() <= 180
        widget.copy_result()
        assert copied == ['Synthetic full output']
        assert widget.status.text() == widget.status.toolTip() == 'Demo · Copied to clipboard'
        widget.show_result('Another result', status='Result ready')
        assert widget.status.text() == widget.status.toolTip() == 'Result ready'
    finally:
        widget.hide()


def test_cancel_button_dismisses_idle_but_preserves_busy_preview(preview):
    cancelled = []
    preview.cancel.connect(lambda: cancelled.append(True))
    cancel = next(b for b in preview.findChildren(QPushButton) if b.text() == 'Cancel')
    preview.show_text('Synthetic source', 'Synthetic result', result_edit=True)
    cancel.click()
    assert not preview.isVisible() and not cancelled
    preview.show_text('Synthetic source', 'Synthetic result', result_edit=True)
    preview.set_session_state('整理', '润色')
    cancel.click()
    assert preview.isVisible() and cancelled == [True]
    preview.set_session_state('idle')
    cancel.click()
    assert not preview.isVisible() and cancelled == [True]


def test_error_preserves_raw_for_explicit_copy_and_edit_only(monkeypatch):
    app = QApplication.instance() or QApplication([])
    copied, edited = [], []
    class Clipboard:
        def setText(self, text): copied.append(text)
    monkeypatch.setattr(QApplication, 'clipboard', lambda: Clipboard())
    widget = ResultBubble({})
    widget.edit_requested.connect(edited.append)
    try:
        raw = 'A recovered original transcript. ' * 30
        message = 'Synthetic connection timeout. <b>Literal diagnostics.</b>'
        widget.show_error(message, raw, status='Transcription failed')
        QApplication.processEvents()
        assert widget.isVisible() and widget.width() == 360 and widget.height() <= 180
        assert widget.text == raw and copied == [] and edited == []
        assert message in widget.preview.toPlainText()
        assert raw in widget.preview.toPlainText()
        assert message in widget.status.toolTip()
        assert widget.preview.verticalScrollBar().maximum() > 0
        widget.copy_button.click()
        widget.edit_button.click()
        assert copied == [raw] and edited == [raw]
    finally:
        widget.hide()


def test_zero_transcript_diagnostic_cannot_be_copied_or_edited_and_morph_cancels(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QApplication, 'clipboard', lambda: pytest.fail('Diagnostic accessed the clipboard'))
    widget = ResultBubble({})
    edited = []
    widget.edit_requested.connect(edited.append)
    monkeypatch.setattr(widget, 'activateWindow', lambda: pytest.fail('Error activated itself'))
    try:
        widget.show_error('Synthetic microphone unavailable.', source=QRect(250, 550, 168, 36))
        assert widget.isVisible() and widget._morph is not None
        assert widget.text == '' and widget.preview.toPlainText() == 'Synthetic microphone unavailable.'
        assert widget.copy_button.isHidden() and not widget.copy_button.isEnabled()
        assert widget.edit_button.isHidden() and not widget.edit_button.isEnabled()
        widget.copy_result()
        widget.edit_result()
        assert edited == []
        assert widget.testAttribute(Qt.WA_ShowWithoutActivating)
        assert widget.windowFlags() & Qt.WindowDoesNotAcceptFocus
        widget.hide()
        QTest.qWait(300)
        assert not widget.isVisible() and widget._morph is None
    finally:
        widget.hide()


def test_success_restores_controls_and_default_style_after_error():
    app = QApplication.instance() or QApplication([])
    widget = ResultBubble({})
    try:
        widget.show_error('Synthetic failure.')
        widget.show_result('A complete result.', status='Result ready')
        assert not widget.copy_button.isHidden() and widget.copy_button.isEnabled()
        assert not widget.edit_button.isHidden() and widget.edit_button.isEnabled()
        assert widget.status.text() == widget.status.toolTip() == 'Result ready'
        assert '#b9aecb' in widget.status.styleSheet()
        widget.show_result('')
        widget.morph_from(QRect(250, 550, 168, 36))
        assert not widget.isVisible() and widget._morph is None
    finally:
        widget.hide()

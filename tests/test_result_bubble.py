"""Compact results preserve full content without activating the target window."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import Qt, QRect
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QLineEdit, QVBoxLayout
from murmur import storage
from murmur.dashboard import MainWindow
from murmur.ui import Bubble, Preview, ResultBubble, STYLE


@pytest.fixture
def result_bubble():
    app = QApplication.instance() or QApplication([])
    bubble = ResultBubble({'bubble_enter_motion':'none','bubble_exit_motion':'none'})
    yield bubble
    bubble.hide()


def test_long_result_is_bounded_but_copy_and_edit_preserve_full_text(result_bubble, monkeypatch):
    copied, edited = [], []
    class Clipboard:
        def setText(self, text): copied.append(text)
        def text(self): return copied[-1] if copied else ''
    monkeypatch.setattr(QApplication, 'clipboard', lambda: Clipboard())
    text = '<b>Literal result</b>\n' + 'A longer result stays available. ' * 200
    result_bubble.edit_requested.connect(edited.append)
    result_bubble.show_result(text, demo=True)
    QApplication.processEvents()
    assert result_bubble.isVisible()
    assert result_bubble.width() == 400 and result_bubble.height() <= 280
    assert result_bubble.preview.isReadOnly()
    assert result_bubble.preview.focusPolicy() == Qt.NoFocus
    assert result_bubble.preview.toPlainText() == text
    assert result_bubble.preview.verticalScrollBar().maximum() > 0
    assert 'Demo' in result_bubble.status.text()
    result_bubble.copy_button.click()
    assert copied == [text]
    result_bubble.edit_button.click()
    assert edited == [text]
    result_bubble.dismiss_button.click()
    assert not result_bubble.isVisible()


def test_result_and_hidden_preview_do_not_take_focus(result_bubble, monkeypatch):
    host = QWidget()
    edit = QLineEdit()
    QVBoxLayout(host).addWidget(edit)
    host.show()
    QApplication.processEvents()
    edit.setFocus()
    QApplication.processEvents()
    focus = QApplication.focusWidget()
    monkeypatch.setattr(result_bubble, 'activateWindow', lambda: pytest.fail('Result activated itself'))
    result_bubble.show_result('A short result.')
    QApplication.processEvents()
    # Offscreen does not emulate native SW_SHOWNOACTIVATE; assert no result
    # control receives keyboard focus and the Windows activation flags exist.
    assert not result_bubble.isAncestorOf(QApplication.focusWidget()) if QApplication.focusWidget() else True
    assert result_bubble.testAttribute(Qt.WA_ShowWithoutActivating)
    assert result_bubble.windowFlags() & Qt.WindowDoesNotAcceptFocus
    host.activateWindow()
    edit.setFocus()
    QApplication.processEvents()
    focus = QApplication.focusWidget()
    preview = Preview()
    shown = []
    monkeypatch.setattr(preview, 'show', lambda: shown.append('show'))
    monkeypatch.setattr(preview, 'raise_', lambda: shown.append('raise'))
    monkeypatch.setattr(preview, 'activateWindow', lambda: shown.append('activate'))
    preview.show_text('Original', 'Final', 'Ready to edit', replace=False, show=False)
    assert shown == [] and not preview.isVisible()
    assert preview.raw.toPlainText() == 'Original' and preview.result.toPlainText() == 'Final'
    assert QApplication.focusWidget() is focus
    preview.show_text('Original', 'Final')
    assert shown == ['show', 'raise', 'activate']
    host.hide()


def test_empty_result_never_changes_clipboard(result_bubble, monkeypatch):
    monkeypatch.setattr(QApplication, 'clipboard', lambda: pytest.fail('Empty result accessed clipboard'))
    result_bubble.show_result('  \n')
    result_bubble.copy_result()
    assert not result_bubble.isVisible()


def test_short_result_does_not_need_scroll(result_bubble):
    result_bubble.show_result('The revised notes are ready. Copy them now, or edit the wording before sharing.')
    QApplication.processEvents()
    assert result_bubble.preview.verticalScrollBar().maximum() == 0


@pytest.mark.parametrize('edge', ('top', 'bottom'))
def test_result_uses_selected_screen_and_never_overflows(result_bubble, monkeypatch, edge):
    class Screen:
        def __init__(self, rect): self.rect = rect
        def availableGeometry(self): return self.rect
    rect = QRect(-650, 100, 400, 300)
    monkeypatch.setattr(QApplication, 'screens', lambda: [Screen(QRect(0, 0, 1920, 1080)), Screen(rect)])
    result_bubble.cfg.update(bubble_screen=1, bubble_offset=10000, bubble_position=edge)
    result_bubble.show_result('Result on a second screen.')
    assert rect.contains(result_bubble.geometry())


def test_usage_uses_only_tracked_totals_and_optional_prices(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(storage, 'credential', lambda *args: '')
    store = storage.Store(tmp_path)
    window = MainWindow(store)
    totals = dict(local_tokens=2500, external_tokens=900, external_cost_usd=.0012, requests=4, estimated_tokens=0, unpriced_calls=1, missing_usage_calls=1, tracked_since='2026-10-04T10:00:00')
    monkeypatch.setattr(store, 'usage_totals', lambda: totals)
    window.show_token_insights()
    assert window.token_values['local_tokens'].text() == '2,500'
    assert window.token_values['external_cost_usd'].text() == '$0.001200'
    assert '2026-10-04' in window.token_notice.text()
    assert 'Cost excludes unpriced calls' in window.token_notice.text()
    rates = ('llm_input_price_per_million', 'llm_output_price_per_million', 'llm_cache_price_per_million')
    assert all(window.fields[key].text() == '' for key in rates)
    config, secrets = window.service_test_values()
    assert all(config[key] is None for key in rates)
    window.fields[rates[0]].setText('0.14')
    config, secrets = window.service_test_values()
    assert config[rates[0]] == .14
    saved = []
    window.save_settings.connect(lambda *args: saved.append(args))
    window.fields[rates[1]].setText('.')
    window.save()
    assert saved == [] and 'non-negative USD price' in window.settings_status.text()
    totals['external_cost_usd'] = None
    window.refresh_token_insights()
    assert window.token_values['external_cost_usd'].text() == 'Not available'
    window.token_dialog.hide()
    window.hide()
    store.db.close()


def test_result_expands_from_capsule_to_same_anchor_and_cleans_effect(result_bubble, monkeypatch):
    source = Bubble({'bubble_enter_motion':'none','bubble_exit_motion':'none'})
    source.position()
    source.state('识别')
    start = QRect(source.geometry())
    monkeypatch.setattr(result_bubble, 'activateWindow', lambda: pytest.fail('Morph activated itself'))
    result_bubble.show_result('A compact result after processing.', source=source)
    target = QRect(result_bubble._target_geometry)
    assert result_bubble.geometry() == start
    assert target.center().x() == start.center().x()
    assert target.bottom() == start.bottom()
    source.state('完成')
    assert not source.isVisible()
    # Sample an actual Qt animation frame deterministically; wall-clock waits
    # can miss that frame when native model tests run on the same computer.
    result_bubble._morph.pause()
    result_bubble._morph.setCurrentTime(110)
    assert start.width() < result_bubble.width() < target.width()
    result_bubble._morph.resume()
    # Qt animation ticks may be delayed while parallel model tests load native
    # runtimes. Wait for completion, while still checking the actual geometry.
    for _ in range(100):
        if result_bubble._morph is None:
            break
        QTest.qWait(20)
    assert result_bubble.geometry() == target
    assert result_bubble._morph is None
    assert result_bubble.contents.graphicsEffect() is None
    assert result_bubble.isVisible()


@pytest.mark.parametrize('dismiss', ('hide', 'set_visible', 'button'))
def test_cancelled_result_animation_never_resurrects(result_bubble, dismiss):
    result_bubble.show_result('Cancelled result', source=QRect(300, 600, 168, 36))
    QTest.qWait(35)
    if dismiss == 'hide':
        result_bubble.hide()
    elif dismiss == 'set_visible':
        result_bubble.setVisible(False)
    else:
        result_bubble.dismiss_button.click()
    generation = result_bubble._morph_generation
    QTest.qWait(300)
    assert not result_bubble.isVisible()
    assert result_bubble._morph is None
    assert result_bubble._morph_generation == generation


def test_rapid_new_recording_and_result_invalidate_previous_animation(result_bubble):
    source = Bubble({'bubble_enter_motion':'none','bubble_exit_motion':'none'})
    source.position()
    source.state('识别')
    result_bubble.show_result('An old result', source=source)
    QTest.qWait(35)
    result_bubble.hide()
    source.state('录音')
    QTest.qWait(260)
    assert not result_bubble.isVisible()
    source.state('整理')
    result_bubble.show_result('A new result that is much longer.\n' * 20, source=source)
    target = QRect(result_bubble._target_geometry)
    source.state('完成')
    QTest.qWait(280)
    assert result_bubble.isVisible() and result_bubble.geometry() == target
    assert result_bubble.text.startswith('A new result')
    assert result_bubble.contents.graphicsEffect() is None

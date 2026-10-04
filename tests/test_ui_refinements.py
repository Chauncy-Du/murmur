"""Geometry, state cleanup, and unsaved service tests at compact window sizes."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest, QSignalSpy
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QCheckBox, QSpinBox, QStyleOptionSpinBox, QStyle
from murmur import storage
from murmur.dashboard import MainWindow
from murmur.ui import STYLE


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(storage, 'credential', lambda *args: '')
    store = storage.Store(tmp_path)
    widget = MainWindow(store)
    widget.show()
    app.processEvents()
    yield widget
    widget.hide()
    store.db.close()


@pytest.mark.parametrize('width', (800, 920))
@pytest.mark.parametrize('dpr', (1., 1.25, 1.5))
def test_calendar_cells_are_square_with_equal_row_and_column_spacing(window, width, dpr, monkeypatch):
    window.resize(width, 680)
    QApplication.processEvents()
    calendar = window.calendar
    monkeypatch.setattr(calendar, 'devicePixelRatioF', lambda: dpr)
    calendar.grab()
    assert 175 <= len(calendar.cells) <= 182
    for rect, day, count in calendar.cells:
        assert rect.width() == rect.height()
        assert rect.right() <= calendar.width()
        assert rect.bottom() < calendar.height() - 16
        for coordinate in (rect.x(), rect.y(), rect.width(), rect.height()):
            physical = coordinate * dpr
            assert physical == pytest.approx(round(physical))
    first, next_row, next_column = [calendar.cells[index][0] for index in (0, 1, 7)]
    step = first.width() + round(4 * dpr) / dpr
    assert next_row.top() - first.top() == pytest.approx(step)
    assert next_column.left() - first.left() == pytest.approx(step)
    assert step * dpr == pytest.approx(round(step * dpr))
    selected = calendar.cells[14]
    QTest.mouseClick(calendar, Qt.LeftButton, pos=selected[0].center().toPoint())
    assert window.day_filter == selected[1].isoformat()
    assert window.stack.currentIndex() == 1


def test_fast_page_switching_cleans_effects_when_entering_settings_mode(window):
    window.nav_buttons[0].setFocus()
    for index in (1, 2, 3, 1, 0, 3):
        window.navigate(index)
        assert all(page.graphicsEffect() is None for page in [window.stack.widget(i) for i in range(4)] if page is not window.stack.currentWidget())
    assert window.main_sidebar.isHidden()
    focused = QApplication.focusWidget()
    assert focused is None or window.stack.currentWidget().isAncestorOf(focused)
    assert isinstance(window.stack.currentWidget().graphicsEffect(), QGraphicsOpacityEffect)
    animation=window._page_animation
    assert animation.duration()==160
    finished=QSignalSpy(animation.finished)
    # Qt's first animation tick may follow a costly high-DPI initial paint.
    # Wait for its real finished signal; never advance animation time manually.
    assert finished.wait(600)
    assert all(window.stack.widget(i).graphicsEffect() is None for i in range(4))
    assert window._page_animation is None


def test_advanced_fields_preserve_values_and_save_stays_visible(window):
    window.navigate(3)
    window.settings_tabs.setCurrentIndex(1)
    QTest.qWait(180)
    for disclosure in (window.asr_advanced, window.offline_advanced, window.ali_advanced, window.llm_advanced):
        assert disclosure.content.isHidden()
    window.fields['asr_url'].setText('wss://unsaved.example/ws')
    window.asr_advanced.toggle.click()
    assert not window.asr_advanced.content.isHidden()
    window.asr_advanced.toggle.click()
    assert window.fields['asr_url'].text() == 'wss://unsaved.example/ws'
    assert window.store.config['asr_url'] != 'wss://unsaved.example/ws'
    for width in (800, 920):
        window.resize(width, 560)
        QApplication.processEvents()
        assert window.save_button.isVisible()
        assert window.save_button.mapTo(window, window.save_button.rect().bottomRight()).y() <= window.height()


def test_service_test_emits_current_snapshot_without_saving(window):
    received = []
    window.service_test.connect(lambda *args: received.append(args))
    original = window.store.config['llm_model']
    window.fields['llm_model'].setText('unsaved-model')
    window.llm_key.setText('mock unsaved secret')
    test, status, details = next(controls for controls in window.service_test_controls['llm']
                                if not controls[0].property('overviewTest'))
    test.click()
    kind, config, secrets = received[0]
    assert kind == 'llm'
    assert config['llm_model'] == 'unsaved-model'
    assert set(secrets) == {'asr', 'llm', 'ask_llm', 'ali_appkey', 'ali_token',
                            'asr_openai_key','asr_groq_key','asr_http_key'}
    assert secrets['llm'] == 'mock unsaved secret'
    assert window.store.config['llm_model'] == original
    config['prompts']['润色'] = 'Modified test snapshot'
    assert window.store.config['prompts']['润色'] != 'Modified test snapshot'
    assert not test.isEnabled() and test.text() == 'Checking…'
    assert status.text() == 'Checking…' and not details.isEnabled()
    overview_test, _, overview_details = next(controls for controls in window.service_test_controls['llm']
                                             if controls[0].property('overviewTest'))
    assert not overview_test.isEnabled() and overview_test.text() == 'Checking'
    assert not overview_details.isEnabled()
    assert 'No completed test yet' in window.service_overview_status['llm'].text()
    assert 'Checking' in window.service_overview_progress['llm'].text()
    assert not window.save_button.isEnabled()


def test_service_results_plain_text_reuse_dialog_and_preserve_result_during_retest(window):
    summary = '<b>API response</b>'
    detail = '<script>plain diagnostic output</script>\nNo settings saved.'
    window.set_service_test_state('asr', False, summary, detail, False)
    for test, status, details in window.service_test_controls['asr']:
        assert test.isEnabled() and details.isEnabled()
        assert status.textFormat() == Qt.PlainText
        assert status.text() == summary
    window.show_service_test_details('asr')
    dialog = window.service_test_dialogs['asr']
    assert not dialog.isModal()
    assert dialog.test_summary.textFormat() == Qt.PlainText
    assert dialog.test_detail.toPlainText() == detail
    window.show_service_test_details('asr')
    assert window.service_test_dialogs['asr'] is dialog
    window.set_service_test_state('asr', True)
    assert dialog.test_detail.toPlainText() == detail
    assert dialog.test_summary.text() == summary
    assert 'new check is running' in dialog.test_context.text()
    window.set_service_test_state('asr', False, 'Settings changed. Test again.')
    assert all(not controls[2].isEnabled() for controls in window.service_test_controls['asr'])
    dialog.close()


def test_setting_changes_invalidate_finished_tests_but_never_unlock_active_test(window):
    window.fields['asr_backend'].setCurrentIndex(window.fields['asr_backend'].findData('bailian'))
    window.set_service_test_state('llm', False, 'Connected', 'Model response received.', True)
    window.show_service_test_details('llm')
    dialog = window.service_test_dialogs['llm']
    window.fields['llm_model'].setText('changed-model')
    test, status, details = next(controls for controls in window.service_test_controls['llm']
                                if not controls[0].property('overviewTest'))
    assert status.text() == 'Not checked' and not details.isEnabled()
    assert not dialog.isVisible()
    window.set_service_test_state('llm', True)
    assert not window.remove_keys_button.isEnabled()
    window.llm_key.setText('mock changed key')
    assert status.text() == 'Checking…' and not test.isEnabled()
    assert 'No completed test yet' in window.service_overview_status['llm'].text()
    assert 'Checking' in window.service_overview_progress['llm'].text()
    assert all(not control[0].isEnabled() and not control[2].isEnabled()
               for control in window.service_test_controls['llm'])
    assert not window.save_button.isEnabled()
    window.set_service_test_state('llm', False, 'Settings changed. Test again.')
    assert window.remove_keys_button.isEnabled()
    window.set_service_test_state('asr', False, 'Connected', 'Provider accepted a session.', True)
    window.fields['asr_backend'].setCurrentIndex(window.fields['asr_backend'].findData('offline'))
    assert all(controls[1].text() == 'Not checked' and not controls[2].isEnabled() for controls in window.service_test_controls['asr'])


def test_switch_and_spin_controls_keep_keyboard_mouse_and_save_semantics(window):
    window.navigate(3)
    window.settings_tabs.setCurrentIndex(0)
    QTest.qWait(180)
    switch = window.fields['demo']
    assert isinstance(switch, QCheckBox)
    initial = switch.isChecked()
    switch.setFocus()
    QTest.keyClick(switch, Qt.Key_Space)
    assert switch.isChecked() is not initial
    QTest.mouseClick(switch, Qt.LeftButton, pos=switch.rect().center())
    assert switch.isChecked() is initial
    window.settings_tabs.setCurrentIndex(3)
    QApplication.processEvents()
    spin = window.fields['bubble_width']
    assert isinstance(spin, QSpinBox)
    spin.setFocus()
    spin.setValue(168)
    QTest.keyClick(spin, Qt.Key_Up)
    assert spin.value() == 169
    option = QStyleOptionSpinBox()
    spin.initStyleOption(option)
    up = spin.style().subControlRect(QStyle.CC_SpinBox, option, QStyle.SC_SpinBoxUp, spin)
    QTest.mouseClick(spin, Qt.LeftButton, pos=up.center())
    assert spin.value() == 170
    spin.setValue(180)
    QTest.keyClick(spin, Qt.Key_Up)
    assert spin.value() == 180
    spin.setValue(156)
    QTest.keyClick(spin, Qt.Key_Down)
    assert spin.value() == 156
    saved = []
    window.save_settings.connect(lambda config, secrets: saved.append(config))
    window.save()
    assert saved[0]['demo'] is initial
    assert saved[0]['bubble_width'] == 156


def test_default_home_has_no_needless_scroll_at_supported_widths(window):
    app = QApplication.instance()
    original_style = app.styleSheet()
    app.setStyleSheet(STYLE)
    try:
        for width in (800, 920):
            window.resize(width, 680)
            window.navigate(0)
            QTest.qWait(190)
            assert window.stack.widget(0).verticalScrollBar().maximum() == 0
    finally:
        app.setStyleSheet(original_style)


def test_navigation_keeps_keyboard_focus_distinct_from_mouse_selection(window):
    QTest.mouseClick(window.nav_buttons[3], Qt.LeftButton)
    assert window.nav_buttons[3].isChecked()
    assert not window.nav_buttons[3].property('keyboardFocus')
    window.nav_buttons[0].setFocus(Qt.TabFocusReason)
    assert window.nav_buttons[0].property('keyboardFocus')
    assert window.nav_buttons[3].isChecked()
    QTest.keyClick(window.nav_buttons[0], Qt.Key_Space)
    assert window.stack.currentIndex() == 0
    assert window.nav_buttons[0].isChecked()
    assert window.nav_buttons[0].hasFocus()


def test_busy_sessions_guard_saved_settings_and_asr_check_guards_recording(window, monkeypatch):
    changes, saved = [], []
    monkeypatch.setattr(storage, 'credential', lambda name, value=None: changes.append(name) if value is not None else '')
    window.save_settings.connect(lambda *args: saved.append(args))
    window.set_session_state('录音', '听写')
    assert not window.save_button.isEnabled() and not window.remove_keys_button.isEnabled()
    window.save()
    window.clear_keys()
    assert changes == [] and saved == []
    assert 'Finish the current' in window.settings_status.text()
    window.set_session_state('idle')
    window.navigate(1)
    window.set_service_test_state('asr', True)
    assert not window.record_button.isEnabled()
    assert not window.translation_button.isEnabled()
    assert not window.history_record_button.isEnabled()
    assert window.home_status.text() == 'Checking speech recognition…'
    assert not window.save_button.isEnabled() and not window.remove_keys_button.isEnabled()
    window.set_service_test_state('llm', True)
    window.set_service_test_state('asr', False, 'Checked')
    assert window.record_button.isEnabled() and window.translation_button.isEnabled()
    assert not window.save_button.isEnabled()
    window.set_service_test_state('llm', False, 'Checked')
    assert window.save_button.isEnabled() and window.remove_keys_button.isEnabled()


def test_provider_profiles_and_preset_label_follow_actual_unsaved_values(window):
    window.llm_preset.setCurrentIndex(window.llm_preset.findData('deepseek'))
    assert window.fields['llm_url'].text() == 'https://api.deepseek.com/v1'
    assert window.fields['llm_model'].text() == 'deepseek-flash'
    window.fields['ollama'].setCurrentIndex(window.fields['ollama'].findData(True))
    assert window.fields['ollama'].currentText() == 'Ollama'
    assert window.fields['llm_url'].text() == 'http://127.0.0.1:11434/v1'
    assert window.fields['llm_model'].text() == 'qwen3.5:2b'
    assert window.llm_preset.currentData() == 'auto'
    window.fields['ollama_auto'].setCurrentIndex(window.fields['ollama_auto'].findData(False))
    window.fields['llm_url'].setText('http://192.168.10.5:11434/v1')
    window.fields['llm_model'].setText('custom-model')
    assert window.llm_preset.currentData() == 'custom'
    window.fields['ollama'].setCurrentIndex(window.fields['ollama'].findData(False))
    assert window.fields['llm_url'].text() == 'https://api.deepseek.com/v1'
    assert window.fields['llm_model'].text() == 'deepseek-flash'
    assert window.llm_preset.currentData() == 'deepseek'
    window.fields['ollama'].setCurrentIndex(window.fields['ollama'].findData(True))
    assert window.fields['llm_url'].text() == 'http://192.168.10.5:11434/v1'
    assert window.fields['llm_model'].text() == 'custom-model'
    assert window.llm_preset.currentData() == 'custom'
    window.llm_preset.setCurrentIndex(window.llm_preset.findData('9b'))
    assert window.fields['llm_url'].text() == 'http://127.0.0.1:11434/v1'
    assert window.fields['llm_model'].text() == 'qwen3.5:9b'
    assert window.llm_preset.currentData() == '9b'
    window.fields['llm_model'].setText('different-model')
    assert window.llm_preset.currentData() == 'custom'


def test_initial_saved_custom_ollama_profile_is_preserved(window):
    window.store.config.update(ollama=True,ollama_auto=False,llm_url='http://192.168.10.6:11434/v1', llm_model='custom-model')
    another = MainWindow(window.store)
    try:
        assert another.fields['llm_url'].text() == 'http://192.168.10.6:11434/v1'
        assert another.fields['llm_model'].text() == 'custom-model'
        assert another.llm_preset.currentData() == 'custom'
        another.fields['ollama'].setCurrentIndex(another.fields['ollama'].findData(False))
        assert another.fields['llm_url'].text() == storage.DEFAULTS['llm_url']
        another.fields['ollama'].setCurrentIndex(another.fields['ollama'].findData(True))
        assert another.fields['llm_url'].text() == 'http://192.168.10.6:11434/v1'
        assert another.fields['llm_model'].text() == 'custom-model'
    finally:
        another.hide()



def test_local_auto_and_specific_model_controls_preserve_unsaved_value(window):
    assert window.fields['ollama'].currentData() is False
    assert window.fields['ollama_auto'].currentData() is True
    assert not window.llm_form.isRowVisible(window.fields['llm_model']) and not window.llm_form.isRowVisible(window.llm_key)
    window.fields['ollama_auto'].setCurrentIndex(window.fields['ollama_auto'].findData(False))
    assert not window.fields['llm_model'].isHidden()
    window.fields['llm_model'].setText('my-specific:4b')
    window.fields['ollama_auto'].setCurrentIndex(window.fields['ollama_auto'].findData(True))
    window.fields['ollama_auto'].setCurrentIndex(window.fields['ollama_auto'].findData(False))
    assert window.fields['llm_model'].text()=='my-specific:4b'
    cfg,_=window.service_test_values()
    assert not cfg['ollama_auto'] and cfg['llm_model']=='my-specific:4b'

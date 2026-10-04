"""Settings restructuring preserves unsaved drafts and controller safeguards."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea
from murmur import storage
from murmur.dashboard import MainWindow
from murmur.ui import STYLE


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    for font in ('segoeui.ttf', 'segoeuib.ttf'):
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + font)
    monkeypatch.setattr(storage, 'credential', lambda *args: '')
    import sounddevice
    monkeypatch.setattr(sounddevice, 'query_devices', lambda: [])
    store = storage.Store(tmp_path)
    widget = MainWindow(store)
    widget.setStyleSheet(STYLE)
    widget.navigate(3)
    widget.show()
    app.processEvents()
    QTest.qWait(180)
    yield widget
    widget.hide()
    store.db.close()


def test_categories_and_field_snapshot_are_complete(window):
    tabs = window.settings_tabs
    assert tabs.count() == 5
    assert tabs.tabBar().isHidden()
    assert [tabs.tabText(i) for i in range(5)] == ['General', 'Services', 'Shortcuts', 'Appearance', 'Writing']
    expected = {
        'demo', 'polish', 'microphone', 'language', 'startup', 'asr_backend',
        'asr_model', 'asr_url', 'vocabulary_id', 'offline_engine', 'offline_model_dir',
        'offline_language', 'offline_threads', 'ali_nls_url', 'ollama',
        'ollama_auto', 'llm_model', 'llm_url', 'llm_input_price_per_million',
        'llm_output_price_per_million', 'llm_cache_price_per_million', 'trigger',
        'dictation_key', 'translation_key', 'selection_key', 'bubble_position',
        'bubble_screen', 'bubble_offset', 'bubble_width', 'retention',
        'save_audio', 'style', 'rules', 'ask_key', 'ask_llm_url', 'ask_llm_model', 'offline_acceleration',
    }
    assert set(window.fields) == expected
    values, secrets = window._settings_snapshot()
    assert expected <= values.keys()
    assert set(values['prompts']) == set(window.store.config['prompts'])
    assert secrets == {'asr': '', 'llm': '', 'ali_appkey': '', 'ali_token': '', 'ask_llm': ''}
    assert window.fields['bubble_width'].value() == 168
    assert window.main_sidebar.isHidden()


def test_category_navigation_and_back_to_previous_page(window):
    for i, nav in enumerate(window.settings_nav_buttons):
        QTest.mouseClick(nav, Qt.LeftButton)
        assert window.settings_tabs.currentIndex() == i
        assert [b.isChecked() for b in window.settings_nav_buttons] == [j == i for j in range(5)]
    window.settings_tabs.setCurrentIndex(0)
    assert window.settings_nav_buttons[0].isChecked()
    window._settings_return_page = 2
    QTest.mouseClick(window.settings_close_button, Qt.LeftButton)
    assert window.stack.currentIndex() == 2


def test_service_panels_and_local_auto_rows_still_follow_draft(window):
    window.settings_tabs.setCurrentIndex(1)
    for provider, active in [('bailian', 'online_asr_panel'), ('offline', 'offline_asr_panel'), ('ali_nls', 'ali_nls_panel')]:
        window.fields['asr_backend'].setCurrentIndex(window.fields['asr_backend'].findData(provider))
        assert not getattr(window, active).isHidden()
        assert all(getattr(window, name).isHidden() for name in ('online_asr_panel', 'offline_asr_panel', 'ali_nls_panel') if name != active)
    window.fields['ollama'].setCurrentIndex(window.fields['ollama'].findData(True))
    assert window.llm_form.isRowVisible(window.fields['ollama_auto'])
    assert not window.llm_form.isRowVisible(window.fields['llm_model'])
    assert not window.llm_form.isRowVisible(window.llm_key)
    window.fields['ollama_auto'].setCurrentIndex(window.fields['ollama_auto'].findData(False))
    assert window.llm_form.isRowVisible(window.fields['llm_model'])
    window.fields['ollama'].setCurrentIndex(window.fields['ollama'].findData(False))
    window.fields['llm_url'].setText('https://example.invalid/v1')
    assert not window.llm_form.isRowVisible(window.fields['ollama_auto'])
    assert window.llm_form.isRowVisible(window.llm_key)


def test_busy_guards_and_service_feedback_remain_connected(window):
    window.set_session_state('录音', '听写')
    assert not window.save_button.isEnabled()
    assert not window.remove_keys_button.isEnabled()
    window.set_session_state('idle', '听写')
    window.set_service_test_state('asr', True)
    assert not window.save_button.isEnabled()
    assert not window.remove_keys_button.isEnabled()
    assert all(not b.isEnabled() for b, status, details in window.service_test_controls['asr'])
    assert window.service_overview_progress['asr'].isVisible() is False  # General is active.
    window.set_service_test_state('asr', False, 'Ready', 'Tested unsaved settings.', True)
    assert window.save_button.isEnabled() and window.remove_keys_button.isEnabled()
    assert all(details.isEnabled() for b, status, details in window.service_test_controls['asr'])
    window.fields['asr_model'].setText('Changed model')
    assert all(status.text() == 'Not checked' and not details.isEnabled() for b, status, details in window.service_test_controls['asr'])


@pytest.mark.parametrize('size', [(920, 680), (800, 560)])
def test_fixed_footer_and_no_horizontal_overflow(window, size):
    window.resize(*size)
    for i in range(5):
        window.settings_tabs.setCurrentIndex(i)
        QApplication.processEvents()
        scroll = window.settings_tabs.widget(i)
        if i == 1:
            assert scroll is window.services_stack
            assert window.services_overview.isVisible()
            assert not window.services_overview.findChildren(QScrollArea)
            continue
        assert isinstance(scroll, QScrollArea)
        assert scroll.horizontalScrollBar().maximum() == 0
        assert window.save_button.isVisible()
        assert window.save_button.mapTo(window, window.save_button.rect().bottomRight()).y() < window.height()


def test_unsaved_credentials_and_prompts_flow_to_existing_save_signal(window):
    saves = []
    window.save_settings.connect(lambda values, secrets: saves.append((values, secrets)))
    window.ali_appkey.setText('synthetic-appkey')
    window.ask_llm_key.setText('synthetic-ask-key')
    window.fields['language'].setText('French')
    mode = next(iter(window.prompt_fields))
    window.prompt_fields[mode].setPlainText('Synthetic prompt')
    window.save_button.click()
    assert len(saves) == 1
    values, secrets = saves[0]
    assert values['language'] == 'French'
    assert values['prompts'][mode] == 'Synthetic prompt'
    assert secrets['ali_appkey'] == 'synthetic-appkey'
    assert secrets['ask_llm'] == 'synthetic-ask-key'
    assert window.store.config['language'] != 'French'


def test_switch_center_and_keyboard_keep_boolean_save_values(window):
    switch = window.fields['demo']
    before = switch.isChecked()
    QTest.mouseClick(switch, Qt.LeftButton, pos=switch.rect().center())
    assert switch.isChecked() is not before
    switch.setFocus()
    QTest.keyClick(switch, Qt.Key_Space)
    assert switch.isChecked() is before
    window.settings_tabs.setCurrentIndex(3)
    width = window.fields['bubble_width']
    width.setValue(168)
    QTest.keyClick(width, Qt.Key_Up)
    values, _ = window._settings_snapshot()
    assert values['bubble_width'] == 169


def test_advanced_settings_do_not_create_horizontal_scroll(window):
    window.resize(800, 560)
    window.settings_tabs.setCurrentIndex(1)
    window.llm_advanced.toggle.setChecked(True)
    for provider, attr in [('bailian', 'asr_advanced'), ('offline', 'offline_advanced'), ('ali_nls', 'ali_advanced')]:
        window.fields['asr_backend'].setCurrentIndex(window.fields['asr_backend'].findData(provider))
        disclosure = getattr(window, attr)
        disclosure.toggle.setChecked(True)
        QApplication.processEvents()
        window.show_service_settings('asr')
        scroll = window.services_subpages['asr']
        assert scroll.horizontalScrollBar().maximum() == 0
        assert not disclosure.content.isHidden()
        assert window.save_button.isVisible()


def test_right_column_title_and_keyboard_only_close_focus(window):
    title = window.settings_title
    category = window.settings_nav_buttons[0]
    assert title.mapTo(window, title.rect().topLeft()).x() > category.mapTo(window, category.rect().bottomRight()).x()
    assert abs(title.mapTo(window, title.rect().center()).y() - category.mapTo(window, category.rect().center()).y()) <= 6
    close = window.settings_close_button
    close.setFocus(Qt.OtherFocusReason)
    QApplication.processEvents()
    assert close.property('keyboardFocus') is False
    category.setFocus(Qt.OtherFocusReason)
    close.setFocus(Qt.TabFocusReason)
    QApplication.processEvents()
    assert close.property('keyboardFocus') is True


def test_switch_has_accessible_name_and_description(window):
    switch = window.fields['demo']
    assert switch.text() == ''
    assert switch.accessibleName() == 'Demo mode'
    assert 'API requests' in switch.accessibleDescription()

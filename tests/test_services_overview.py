"""Service roles, model identity and finished diagnostics remain visible."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from copy import deepcopy

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea

from murmur import storage
from murmur.dashboard import MainWindow
from murmur.ui import STYLE


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    for font in ('segoeui.ttf', 'segoeuib.ttf'):
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + font)
    monkeypatch.setattr(storage, 'credential', lambda *args: '')
    monkeypatch.setattr(storage, 'DEFAULT_OFFLINE_MODELS_ROOT', tmp_path / 'models')
    import sounddevice
    monkeypatch.setattr(sounddevice, 'query_devices', lambda: [])
    import httpx
    def forbidden_request(*args, **kwargs):
        pytest.fail('Model identity must not make a network request')
    monkeypatch.setattr(httpx, 'Client', forbidden_request)
    store = storage.Store(tmp_path / 'data')
    store.config.update(online_llm_url='https://api.deepseek.com/v1', online_llm_model='deepseek-chat')
    widget = MainWindow(store)
    widget.setStyleSheet(STYLE)
    widget.navigate(3)
    widget.settings_tabs.setCurrentIndex(1)
    widget.show()
    QTest.qWait(180)
    yield widget
    for dialog in widget.service_test_dialogs.values():
        dialog.hide()
    widget.hide()
    store.db.close()


def mark_completed(window, kind='llm', model='qwen3.5:4b'):
    window.set_service_model_metadata(kind, {
        'success': True, 'model': model, 'model_selection': 'auto',
        'parameter_size': '4B', 'parameter_size_source': 'model_tag',
    })
    window.set_service_test_state(kind, False, 'Connected', 'Synthetic successful check.', True)


def test_overview_explains_separate_speech_and_text_models_without_guessing_auto(window):
    explanations = ' '.join(label.text() for label in window.services_overview.findChildren(QLabel))
    assert 'Speech to Text' in explanations and 'Turn your voice into text' in explanations
    assert 'Polish' in explanations and 'original language' in explanations
    assert 'Ask Anything' in explanations and 'separate model' in explanations
    assert 'SenseVoice' in window.service_overview_models['asr'].text()
    text_model = window.service_overview_models['llm'].text()
    assert 'Auto' in text_model and 'test to identify' in text_model
    assert 'qwen3.5:2b' not in text_model
    assert window.service_model_metadata == {}


def test_auto_model_identity_comes_only_from_successful_test_metadata(window):
    window.set_service_model_metadata('llm', {'success': False, 'model': 'unverified-model'})
    assert 'unverified-model' not in window.service_overview_models['llm'].text()
    mark_completed(window)
    text_model = window.service_overview_models['llm'].text()
    assert 'Auto' in text_model and 'qwen3.5:4b' in text_model
    assert 'last successful check' in window.service_overview_models['llm'].toolTip()


def test_reported_model_alias_is_visible_without_changing_the_configured_model(window):
    window.llm_source.setCurrentIndex(window.llm_source.findData(False))
    configured = window.fields['llm_model'].text()
    window.set_service_model_metadata('llm', {
        'success': True, 'model': configured, 'model_selection': 'manual',
        'response_model': 'deepseek-flash',
    })
    name = window.service_overview_models['llm'].text()
    assert configured in name and 'deepseek-flash' in name and 'online' in name
    assert window.fields['llm_model'].text() == configured


def test_remote_ollama_protocol_is_not_described_as_processing_on_this_device(window):
    window.fields['ollama'].setCurrentIndex(window.fields['ollama'].findData(True))
    window.fields['llm_url'].setText('https://remote-server.invalid/v1')
    assert window.llm_source.currentData() is False
    mark_completed(window)
    name = window.service_overview_models['llm'].text()
    assert 'Auto' in name and 'qwen3.5:4b' in name and ' · online' in name
    assert ' · local' not in name
    assert 'Remote Ollama' in window.llm_hint.text()
    assert 'receives your text' in window.llm_hint.toolTip()


def test_manual_four_billion_preset_is_visible_and_selects_the_text_model(window):
    assert not window.llm_advanced.isAncestorOf(window.llm_preset)
    window.show_service_settings('llm')
    assert window.llm_preset.isVisible()
    window.llm_preset.setCurrentIndex(window.llm_preset.findData('4b'))
    assert window.fields['ollama_auto'].currentData() is False
    assert window.fields['llm_model'].text() == 'qwen3.5:4b'
    assert window.llm_form.isRowVisible(window.fields['llm_model'])
    assert 'qwen3.5:4b' in window.service_overview_models['llm'].text()
    assert 'Auto' not in window.service_overview_models['llm'].text()
    assert 'SenseVoice' in window.service_overview_models['asr'].text()


def test_services_has_three_independent_subpages_and_controls_stay_with_their_role(window):
    speech = window.asr_service_section
    text = window.llm_service_section
    assert not speech.isAncestorOf(text) and not text.isAncestorOf(speech)
    assert speech.isAncestorOf(window.fields['asr_backend'])
    for panel in (window.offline_asr_panel, window.online_asr_panel, window.ali_nls_panel):
        assert speech.isAncestorOf(panel) and not text.isAncestorOf(panel)
    for control in (window.llm_source, window.llm_preset, window.fields['llm_model']):
        assert text.isAncestorOf(control) and not speech.isAncestorOf(control)
    assert window.ask_service_section.isAncestorOf(window.fields['ask_llm_model'])
    assert window.ask_service_section.isAncestorOf(window.ask_llm_key)
    assert not text.isAncestorOf(window.ask_llm_key)
    assert window.llm_advanced.isAncestorOf(window.fields['ollama'])
    assert not window.llm_advanced.isAncestorOf(window.llm_source)
    values, _ = window._settings_snapshot()
    assert 'llm_source' not in values  # Source chooses existing provider settings.


def test_source_switch_restores_local_and_online_drafts_without_saving(window):
    saved = deepcopy(window.store.config)
    window.llm_preset.setCurrentIndex(window.llm_preset.findData('4b'))
    window.fields['llm_url'].setText('http://localhost:11434/v1')
    assert window.llm_source.currentData() is True
    local = {key: window.fields[key].currentData() if key in ('ollama', 'ollama_auto')
             else window.fields[key].text() for key in ('llm_url', 'llm_model', 'ollama', 'ollama_auto')}
    window.llm_source.setCurrentIndex(window.llm_source.findData(False))
    assert window.fields['llm_url'].text() == saved['online_llm_url']
    assert window.fields['llm_model'].text() == saved['online_llm_model']
    assert window.fields['ollama'].currentData() is False
    assert 'deepseek-chat' in window.service_overview_models['llm'].text()
    assert 'online' in window.service_overview_models['llm'].text()
    window.fields['llm_url'].setText('https://example.invalid/v1')
    window.fields['llm_model'].setText('synthetic-online-draft')
    window.llm_source.setCurrentIndex(window.llm_source.findData(True))
    for key, expected in local.items():
        field = window.fields[key]
        actual = field.currentData() if key in ('ollama', 'ollama_auto') else field.text()
        assert actual == expected
    assert 'qwen3.5:4b' in window.service_overview_models['llm'].text()
    window.llm_source.setCurrentIndex(window.llm_source.findData(False))
    assert window.fields['llm_url'].text() == 'https://example.invalid/v1'
    assert window.fields['llm_model'].text() == 'synthetic-online-draft'
    assert window.llm_source.currentData() is False
    assert window.store.config == saved and not window.store.path.exists()


@pytest.mark.parametrize('ollama_protocol', [False, True])
def test_save_from_local_source_retains_the_edited_online_profile(window, ollama_protocol):
    window.fields['ollama'].setCurrentIndex(window.fields['ollama'].findData(ollama_protocol))
    window.fields['llm_url'].setText('http://127.0.0.1:11434/v1')
    window.llm_source.setCurrentIndex(window.llm_source.findData(False))
    window.fields['llm_url'].setText('https://example.invalid/v1')
    window.fields['llm_model'].setText('synthetic-online-draft')
    window.llm_source.setCurrentIndex(window.llm_source.findData(True))
    values, _ = window._settings_snapshot()
    assert values['llm_url'] == 'http://127.0.0.1:11434/v1'
    assert values['online_llm_url'] == 'https://example.invalid/v1'
    assert values['online_llm_model'] == 'synthetic-online-draft'
    window.store.config.update(values)
    window.store.save()
    reloaded = storage.Store(window.store.root)
    try:
        assert reloaded.config['online_llm_url'] == 'https://example.invalid/v1'
        assert reloaded.config['online_llm_model'] == 'synthetic-online-draft'
    finally:
        reloaded.db.close()


def test_online_preset_does_not_replace_the_previous_local_model_draft(window):
    window.llm_preset.setCurrentIndex(window.llm_preset.findData('4b'))
    window.llm_preset.setCurrentIndex(window.llm_preset.findData('deepseek'))
    assert window.llm_source.currentData() is False
    assert window.fields['llm_model'].text() == 'deepseek-flash'
    window.llm_source.setCurrentIndex(window.llm_source.findData(True))
    assert window.fields['llm_model'].text() == 'qwen3.5:4b'
    assert window.fields['ollama_auto'].currentData() is False


@pytest.mark.parametrize('field', ['llm_model', 'llm_url', 'llm_key'])
def test_draft_changes_clear_completed_model_identity_and_keep_recheck_locked(window, field):
    mark_completed(window)
    window.set_service_test_state('llm', True)
    control = window.llm_key if field == 'llm_key' else window.fields[field]
    control.setText('synthetic-new-key' if field == 'llm_key' else
                    'http://localhost:11434/v1' if field == 'llm_url' else 'qwen3.5:9b')
    assert 'llm' not in window.service_model_metadata
    assert 'qwen3.5:4b' not in window.service_overview_models['llm'].text()
    assert 'llm' not in window.service_test_results
    assert window.service_test_busy['llm']
    assert not window.save_button.isEnabled()
    assert all(not button.isEnabled() and not details.isEnabled()
               for button, status, details in window.service_test_controls['llm'])


@pytest.mark.parametrize('kind', ['asr', 'llm'])
def test_recheck_keeps_last_completed_diagnostics_separate_from_progress(window, kind):
    summary = 'Model loaded' if kind == 'asr' else 'Connected'
    expected = 'Speech model ready' if kind == 'asr' else summary
    detail = 'Synthetic completed diagnostics remain available during recheck.'
    window.set_service_test_state(kind, False, summary, detail, True)
    window.show_service_test_details(kind)
    dialog = window.service_test_dialogs[kind]
    window.set_service_test_state(kind, True)
    assert window.service_test_results[kind] == (expected, detail)
    assert dialog.test_summary.text() == expected and dialog.test_detail.toPlainText() == detail
    assert 'new check is running' in dialog.test_context.text()
    assert expected in window.service_overview_status[kind].text()
    assert window.service_overview_progress[kind].isVisible()
    assert all(expected in status.text() and details.isEnabled() and not button.isEnabled()
               for button, status, details in window.service_test_controls[kind])
    window.set_service_test_state(kind, False, 'Connection failed', 'New failure diagnostics.', False)
    assert not window.service_test_busy[kind]
    assert window.service_overview_progress[kind].isHidden()
    assert 'Connection failed' in window.service_overview_status[kind].text()
    assert dialog.test_detail.toPlainText() == 'New failure diagnostics.'


def test_initial_check_explains_that_no_completed_result_exists(window):
    window.set_service_test_state('llm', True)
    assert window.service_overview_progress['llm'].isVisible()
    assert 'Checking' in window.service_overview_progress['llm'].text()
    assert 'No completed test yet' in window.service_overview_status['llm'].text()
    assert all(not details.isEnabled()
               for button, status, details in window.service_test_controls['llm'])


def test_services_overview_has_no_scroll_and_returns_from_each_subpage(window):
    stack = window.settings_tabs.widget(1)
    overview = window.services_overview
    assert stack.currentWidget() is overview
    assert not overview.findChildren(QScrollArea)
    for kind in ('asr', 'llm', 'ask'):
        QTest.mouseClick(window.services_advanced_buttons[kind], Qt.LeftButton)
        assert not overview.isVisible() and window.services_subpages[kind].isVisible()
        QTest.mouseClick(window.services_back_buttons[kind], Qt.LeftButton)
        assert stack.currentWidget() is overview and overview.isVisible()
    assert window.save_button.isVisible()
    window.settings_tabs.setCurrentIndex(0)
    assert not overview.isVisible()
    window.settings_tabs.setCurrentIndex(1)
    assert overview.isVisible()


def test_long_connection_result_wraps_without_covering_buttons_or_footer(window):
    summary = ('Connection timed out. The selected text model did not finish its test request; '
               'check the local model service and try again.')
    window.set_service_test_state('llm', False, summary, 'Synthetic full diagnostics.', False)
    QTest.qWait(30)
    card = window.service_overview_status['llm']
    assert not card.wordWrap() and card.textFormat() == Qt.PlainText
    assert summary in card.toolTip()
    assert card.mapTo(window, card.rect().bottomRight()).y() < window.save_button.mapTo(window, QPoint(0, 0)).y()
    window.show_service_settings('llm')
    button, status, details = window.service_test_controls['llm'][1]
    scroll = window.services_subpages['llm']
    scroll.ensureWidgetVisible(status)
    QApplication.processEvents()
    assert status.wordWrap() and status.height() >= status.heightForWidth(status.width())
    assert status.width() > 0 and button.isEnabled() and details.isEnabled()
    assert not status.geometry().intersects(button.geometry())
    assert not status.geometry().intersects(details.geometry())
    assert scroll.horizontalScrollBar().maximum() == 0


def test_refreshing_file_readiness_does_not_erase_a_finished_speech_test(window):
    window.set_service_test_state('asr', False, 'Model loaded', 'Synthetic verified model.', True)
    window.update_offline_readiness()
    assert window.service_test_results['asr'] == ('Speech model ready', 'Synthetic verified model.')
    assert 'Speech model ready' in window.service_overview_status['asr'].text()
    assert 'first load' not in window.offline_status.text().lower()


def test_three_model_choices_change_existing_fields_without_saving(window):
    before = deepcopy(window.store.config)
    speech = window.services_model_choices['asr']
    speech.setCurrentIndex(speech.findData('paraformer'))
    assert window.fields['asr_backend'].currentData() == 'offline'
    assert window.fields['offline_engine'].currentData() == 'paraformer'
    speech.setCurrentIndex(speech.findData('bailian'))
    assert window.fields['asr_backend'].currentData() == 'bailian'
    polish = window.services_model_choices['llm']
    polish.setCurrentIndex(polish.findData('4b'))
    assert window.fields['llm_model'].text() == 'qwen3.5:4b'
    assert window.fields['ollama_auto'].currentData() is False
    assert window.llm_source.currentData() is True
    polish.setCurrentIndex(polish.findData('online'))
    assert window.fields['llm_model'].text() == before['online_llm_model']
    assert window.fields['llm_url'].text() == before['online_llm_url']
    assert window.llm_source.currentData() is False
    assert window.store.config == before and not window.store.path.exists()
    window.fields['ask_llm_url'].setText('https://api.deepseek.com/v1')
    ask = window.services_model_choices['ask']
    ask.setCurrentIndex(ask.findData('deepseek'))
    assert window.fields['ask_llm_model'].text() == 'deepseek-flash'
    assert window.fields['llm_model'].text() == before['online_llm_model']


def test_subpage_navigation_keeps_credentials_paths_and_independent_drafts(window):
    window.show_service_settings('asr')
    window.fields['offline_model_dir'].setText('D:/Artificial/model-draft')
    window.asr_key.setText('synthetic-key')
    window.show_services_overview()
    window.show_service_settings('ask')
    window.ask_llm_key.setText('synthetic-ask')
    window.fields['ask_llm_model'].setText('synthetic-custom-ask')
    window.show_services_overview()
    window.show_service_settings('llm')
    window.fields['llm_model'].setText('synthetic-polish')
    window.show_services_overview()
    cfg, secrets = window.service_test_values()
    assert cfg['offline_model_dir'] == 'D:/Artificial/model-draft'
    assert cfg['ask_llm_model'] == 'synthetic-custom-ask'
    assert cfg['llm_model'] == 'synthetic-polish'
    assert secrets['asr'] == 'synthetic-key' and secrets['ask_llm'] == 'synthetic-ask'
    assert window.services_model_choices['ask'].currentText() == 'synthetic-custom-ask'


def test_overview_rows_stay_bounded_with_long_models_results_and_busy_locks(window):
    window.fields['ask_llm_model'].setText('synthetic-custom-model-' * 12)
    summary = 'Synthetic failure summary with full diagnostics. ' * 15
    window.set_service_test_state('ask', False, summary, 'Artificial diagnostic detail', False)
    QApplication.processEvents()
    assert window.width() == 920 and window.height() == 680
    for kind, card in window.services_cards.items():
        assert card.height() < 160
        assert card.mapTo(window, card.rect().bottomRight()).y() < window.save_button.mapTo(window, QPoint()).y()
        assert window.services_model_choices[kind].isVisible()
    assert summary in window.service_overview_status['ask'].toolTip()
    assert 'synthetic-custom-model-' in window.service_overview_models['ask'].text()
    window.set_session_state('录音', '听写')
    assert not window.save_button.isEnabled()
    assert all(not combo.isEnabled() for combo in window.services_model_choices.values())
    window.set_session_state('idle', '听写')
    window.set_service_test_state('ask', True)
    assert not window.save_button.isEnabled()
    assert not window.services_model_choices['ask'].isEnabled()
    assert window.services_model_choices['asr'].isEnabled() and window.services_model_choices['llm'].isEnabled()
    window.set_service_test_state('ask', False, 'Connected', 'Artificial result', True)
    assert all(combo.isEnabled() for combo in window.services_model_choices.values())


@pytest.mark.parametrize('kind', ('asr', 'llm', 'ask'))
def test_overview_test_buttons_send_correct_current_draft_snapshot(window, kind):
    emitted = []
    window.service_test.connect(lambda *args: emitted.append(args))
    window.ask_llm_key.setText('synthetic-ask-test-key')
    test, _, _ = window.service_test_controls[kind][0]
    QTest.mouseClick(test, Qt.LeftButton)
    assert len(emitted) == 1
    service, config, secrets = emitted[0]
    assert service == kind
    assert config['ask_llm_model'] == window.fields['ask_llm_model'].text()
    assert secrets['ask_llm'] == 'synthetic-ask-test-key'
    assert window.service_test_busy[kind] and not test.isEnabled()
    assert not window.store.path.exists()

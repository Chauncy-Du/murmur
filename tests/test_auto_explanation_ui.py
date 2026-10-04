"""Auto policy and checked identity stay truthful without I/O or layout growth."""
from copy import deepcopy

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel
from PySide6.QtTest import QTest

from test_services_overview import window, mark_completed
from murmur.service_settings import AUTO_POLICY_HELP, ModelLabel


def test_auto_explains_preference_fallback_and_no_quality_guarantee(window):
    window.show_service_settings('llm')
    labels = ' '.join(widget.text() for widget in window.llm_service_section.findChildren(QLabel))
    assert 'Prefers installed 4–8B models' in labels
    assert 'otherwise uses other available local models' in labels
    field = window.fields['ollama_auto']
    assert field.currentData() is True
    assert 'prefer 4–8B' in field.currentText()
    assert 'metadata may be incomplete' in field.toolTip()
    assert 'does not guarantee writing accuracy' in field.toolTip()
    assert 'No downloads or cloud fallback' in field.toolTip()


def test_unchecked_auto_choice_has_no_invented_resolved_identity(window):
    choice = window.services_model_choices['llm']
    assert choice.currentData() == 'local_auto'
    assert choice.currentText() == 'Local · Auto'
    assert 'Test to identify' in choice.toolTip()
    assert choice.itemData(choice.currentIndex(), Qt.ToolTipRole) == AUTO_POLICY_HELP
    window.set_service_model_metadata('llm', {'success': False, 'model': 'unverified-model', 'model_selection': 'auto'})
    assert choice.currentText() == 'Local · Auto'


@pytest.mark.parametrize('resolved', ['qwen3.5:4b', 'only-installed:9b', 'unknown-parameter-model'])
def test_successful_auto_identity_is_visible_without_saving_or_quality_claim(window, resolved):
    before = deepcopy(window.store.config)
    mark_completed(window, model=resolved)
    choice = window.services_model_choices['llm']
    assert choice.currentData() == 'local_auto'
    assert choice.currentText() == 'Auto · ' + resolved
    assert resolved in choice.toolTip()
    assert resolved in window.service_overview_models['llm'].text()
    window.show_service_test_details('llm')
    dialog = window.service_test_dialogs['llm']
    assert resolved in dialog.test_context.text()
    assert 'Writing quality is not verified' in dialog.test_context.toolTip()
    assert dialog.test_detail.toPlainText() == 'Synthetic successful check.'
    assert window.store.config == before and not window.store.path.exists()


def test_draft_change_removes_checked_auto_identity_and_hides_old_details(window):
    mark_completed(window)
    window.show_service_test_details('llm')
    dialog = window.service_test_dialogs['llm']
    window.fields['llm_url'].setText('http://localhost:11434/v1')
    assert window.services_model_choices['llm'].currentText() == 'Local · Auto'
    assert 'qwen3.5:4b' not in window.service_overview_models['llm'].text()
    assert dialog.isHidden()


def test_explicit_model_remains_manual_and_is_not_presented_as_auto(window):
    window.llm_preset.setCurrentIndex(window.llm_preset.findData('4b'))
    window.set_service_model_metadata('llm', {'success': True, 'model': 'qwen3.5:4b', 'model_selection': 'manual'})
    assert window.services_model_choices['llm'].currentData() == '4b'
    assert window.services_model_choices['llm'].currentText() == 'Qwen3.5 · 4B'
    auto = window.services_model_choices['llm'].findData('local_auto')
    assert window.services_model_choices['llm'].itemText(auto) == 'Local · Auto'
    assert 'Auto' not in window.service_overview_models['llm'].text()


def test_long_auto_identity_is_bounded_and_busy_context_retains_previous_test(window):
    resolved = 'synthetic-long-model-' + 'abcd-' * 60
    mark_completed(window, model=resolved)
    window.show_service_test_details('llm')
    dialog = window.service_test_dialogs['llm']
    window.set_service_test_state('llm', True)
    QTest.qWait(30)
    assert isinstance(dialog.test_context, ModelLabel)
    assert 'new check is running' in dialog.test_context.text()
    assert resolved in dialog.test_context.toolTip()
    assert resolved in dialog.test_context.accessibleName()
    assert dialog.test_context.height() < 30
    assert dialog.test_detail.height() > 70
    assert (dialog.width(), dialog.height()) == (460, 240)
    assert (window.width(), window.height()) == (920, 680)
    assert not window.services_model_choices['llm'].isEnabled()

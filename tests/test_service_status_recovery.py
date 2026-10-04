"""Newest download/check evidence wins without confusing file presence with readiness."""
from copy import deepcopy

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest

from test_services_overview import window


DOWNLOAD_COMPLETE = 'Model files downloaded and verified. Save changes to use this folder.'


def finish_download(window, notice=DOWNLOAD_COMPLETE):
    window.set_offline_download_state(True)
    window.set_offline_download_state(False)
    window.offline_status.setText(notice)


def test_first_check_after_download_replaces_file_success_with_checking_state(window):
    finish_download(window)
    assert window.service_overview_status['asr'].text() == DOWNLOAD_COMPLETE
    window.set_service_test_state('asr', True)
    assert window.service_overview_status['asr'].text() == 'No completed test yet'
    assert window.service_overview_progress['asr'].text() == 'Checking…'
    assert window.service_overview_progress['asr'].isVisible()
    assert window.offline_status.text() == DOWNLOAD_COMPLETE
    assert all(not test.isEnabled() for test, _, _ in window.service_test_controls['asr'])
    assert not window.save_button.isEnabled()


@pytest.mark.parametrize('summary,success', [
    ('Model could not load', False), ('Check cancelled', None),
    ('Settings changed. Test again.', None), ('Model loaded', True),
])
def test_check_outcome_supersedes_download_without_fabricating_readiness(window, summary, success):
    saved = deepcopy(window.store.config)
    finish_download(window)
    window.set_service_test_state('asr', True)
    detail = 'Synthetic current check: ' + summary
    window.set_service_test_state('asr', False, summary, detail, success)
    expected = 'Speech model ready' if success else summary
    status = window.service_overview_status['asr']
    assert status.text() == expected and detail in status.toolTip()
    assert status.text() != DOWNLOAD_COMPLETE
    assert window.offline_status.text() == DOWNLOAD_COMPLETE
    assert window.service_test_success['asr'] is success
    assert window.service_overview_progress['asr'].isHidden()
    assert all(test.isEnabled() and details.isEnabled()
               for test, _, details in window.service_test_controls['asr'])
    window.show_service_test_details('asr')
    assert window.service_test_dialogs['asr'].test_summary.text() == expected
    assert window.service_test_dialogs['asr'].test_detail.toPlainText() == detail
    assert window.store.config == saved and not window.store.path.exists()


@pytest.mark.parametrize('notice', [DOWNLOAD_COMPLETE, 'Download failed. Try again.', 'Download cancelled.'])
def test_new_download_supersedes_previous_check_until_another_check_starts(window, notice):
    window.set_service_test_state('asr', False, 'Model could not load', 'Previous synthetic failure.', False)
    finish_download(window, notice)
    assert window.service_overview_status['asr'].text() == notice
    window.set_service_test_state('asr', True)
    status = window.service_overview_status['asr']
    assert status.text() == 'Last test: Model could not load'
    assert 'Previous synthetic failure.' in status.toolTip()
    assert window.service_overview_progress['asr'].isVisible()
    window.show_service_test_details('asr')
    assert 'new check is running' in window.service_test_dialogs['asr'].test_context.text()


def test_long_failure_stays_bounded_and_unrelated_text_check_does_not_hide_download(window):
    finish_download(window)
    window.set_service_test_state('llm', True)
    assert window.service_overview_status['asr'].text() == DOWNLOAD_COMPLETE
    summary = 'The selected speech model failed to initialize. ' * 12
    window.set_service_test_state('asr', True)
    window.set_service_test_state('asr', False, summary, 'Synthetic complete diagnostics.', False)
    QTest.qWait(30)
    status = window.service_overview_status['asr']
    assert status.text() == summary and summary in status.toolTip()
    assert not status.wordWrap()
    assert (window.width(), window.height()) == (920, 680)
    assert status.mapTo(window, status.rect().bottomRight()).y() < window.save_button.mapTo(window, QPoint()).y()
    assert all(window.services_overview.rect().contains(card.geometry()) for card in window.services_cards.values())

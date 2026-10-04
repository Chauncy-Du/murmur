"""Service actions remain identifiable and operable through Qt accessibility."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from copy import deepcopy
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from murmur import storage
from murmur.dashboard import MainWindow
from murmur.ui import STYLE


SERVICES = [('asr', 'Speech to Text'), ('llm', 'Polish'), ('ask', 'Ask Anything')]


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(storage, 'credential', lambda *args: '')
    monkeypatch.setattr(storage, 'DEFAULT_OFFLINE_MODELS_ROOT', tmp_path / 'models')
    import sounddevice
    monkeypatch.setattr(sounddevice, 'query_devices', lambda *args, **kwargs: [])
    import httpx
    def blocked_network(*args, **kwargs):
        pytest.fail('Accessibility checks must not contact a service')
    monkeypatch.setattr(httpx, 'Client', blocked_network)
    store = storage.Store(tmp_path / 'data')
    widget = MainWindow(store)
    widget.setStyleSheet(STYLE)
    widget.navigate(3)
    widget.settings_tabs.setCurrentIndex(1)
    widget.show()
    QTest.qWait(180)
    yield widget
    widget.hide()
    widget.deleteLater()
    store.db.close()


def accessible(control):
    interface = QAccessible.queryAccessibleInterface(control)
    assert interface is not None
    assert interface.role() == QAccessible.Role.Button
    return interface


def overview_test(window, kind):
    return next(test for test, _, _ in window.service_test_controls[kind]
                if test.property('overviewTest'))


@pytest.mark.parametrize('kind,service_name', SERVICES)
def test_accessible_test_identifies_and_dispatches_only_its_service(window, kind, service_name):
    test = overview_test(window, kind)
    interface = accessible(test)
    name = interface.text(QAccessible.Text.Name)
    assert service_name in name and name != test.text()
    assert interface.text(QAccessible.Text.Description) == test.toolTip()
    assert interface.text(QAccessible.Text.Description)
    assert not interface.state().disabled
    names = [accessible(overview_test(window, key)).text(QAccessible.Text.Name)
             for key, _ in SERVICES]
    assert len(set(names)) == len(SERVICES)
    saved = deepcopy(window.store.config)
    spy = QSignalSpy(window.service_test)
    test.setFocus(Qt.TabFocusReason)
    QTest.keyClick(test, Qt.Key_Space)
    assert spy.count() == 1 and spy.at(0)[0] == kind
    assert accessible(test).state().disabled
    assert accessible(test).text(QAccessible.Text.Name) == name
    assert window.service_test_busy[kind]
    assert all(not window.service_test_busy[key] for key, _ in SERVICES if key != kind)
    assert window.store.config == saved and not window.store.path.exists()
    assert test.text() == 'Checking'


@pytest.mark.parametrize('kind,service_name', SERVICES)
def test_busy_service_advanced_remains_identifiable_and_keyboard_navigable(window, kind, service_name):
    window.fields['llm_model'].setText('synthetic-unsaved-model')
    draft, _ = window.service_test_values()
    window.set_service_test_state(kind, True)
    advanced = window.services_advanced_buttons[kind]
    interface = accessible(advanced)
    name = interface.text(QAccessible.Text.Name)
    assert service_name in name and 'settings' in name.lower()
    assert not interface.state().disabled
    assert accessible(overview_test(window, kind)).state().disabled
    advanced.setFocus(Qt.TabFocusReason)
    QTest.keyClick(advanced, Qt.Key_Space)
    assert window.services_stack.currentWidget() is window.service_detail_pages[kind]
    back = window.services_back_buttons[kind]
    back.setFocus(Qt.TabFocusReason)
    QTest.keyClick(back, Qt.Key_Space)
    assert window.services_stack.currentWidget() is window.services_overview
    assert accessible(advanced).text(QAccessible.Text.Name) == name
    assert window.service_test_values()[0] == draft
    assert window.service_test_busy[kind]


def test_recording_locks_tests_without_erasing_service_identity(window):
    names = {kind: accessible(overview_test(window, kind)).text(QAccessible.Text.Name)
             for kind, _ in SERVICES}
    window.set_session_state('recording', '听写')
    for kind, _ in SERVICES:
        interface = accessible(overview_test(window, kind))
        assert interface.state().disabled and interface.text(QAccessible.Text.Name) == names[kind]
        assert not accessible(window.services_advanced_buttons[kind]).state().disabled
    window.set_session_state('idle', '')
    for kind, _ in SERVICES:
        assert not accessible(overview_test(window, kind)).state().disabled
    assert (window.width(), window.height()) == (920, 680)


def test_http_accessible_description_explains_connection_only_scope(window):
    selector=window.fields['asr_backend']
    selector.setCurrentIndex(selector.findData('openai'))
    interface=accessible(overview_test(window,'asr'))
    description=interface.text(QAccessible.Text.Description)
    assert 'authentication' in description and '/models' in description
    assert 'No audio is recorded or sent' in description
    assert 'transcription quality and audio API access are not tested' in description

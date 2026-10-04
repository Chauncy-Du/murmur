"""The compact Services hub keeps independent drafts and detail navigation."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QStackedWidget

from murmur import storage
from murmur.dashboard import MainWindow
from murmur.ui import STYLE


def _seed_config(store):
    store.config.update(
        online_llm_url='https://api.deepseek.com/v1', online_llm_model='deepseek-chat',
        ask_llm_url='https://ask.example.invalid/v1', ask_llm_model='synthetic-ask-model',
    )


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    for font in ('segoeui.ttf', 'segoeuib.ttf'):
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + font)
    monkeypatch.setattr(storage, 'credential', lambda *args: '')
    monkeypatch.setattr(storage, 'DEFAULT_OFFLINE_MODELS_ROOT', tmp_path / 'models')
    from murmur import windows
    monkeypatch.setattr(windows, 'prepare_text_context', lambda: None)
    import sounddevice
    monkeypatch.setattr(sounddevice, 'query_devices', lambda: [])
    import httpx
    def forbidden_request(*args, **kwargs):
        pytest.fail('Opening or selecting a Services page must not request a service')
    monkeypatch.setattr(httpx, 'Client', forbidden_request)
    store = storage.Store(tmp_path / 'data')
    _seed_config(store)
    store.config_before_gui = deepcopy(store.config)
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


def _select_model(selector, value):
    index = selector.findData(value)
    assert index >= 0, f'Missing model choice {value!r}'
    selector.setCurrentIndex(index)
    QApplication.processEvents()


def _ask_snapshot(window):
    return window.fields['ask_llm_url'].text(), window.fields['ask_llm_model'].text(), window.ask_llm_key.text()


def test_hub_has_three_distinct_services_and_model_icons(window):
    assert isinstance(window.services_stack, QStackedWidget)
    assert window.services_stack.currentWidget() is window.services_overview
    expected = {'asr', 'llm', 'ask'}
    assert set(window.services_model_choices) == set(window.services_advanced_buttons) == expected
    assert set(window.service_overview_models) == set(window.service_overview_status) == expected
    assert window.store.config == window.store.config_before_gui
    titles = ' '.join(label.text() for label in window.services_overview.findChildren(QLabel))
    for title in ('Speech to Text', 'Polish', 'Ask Anything'):
        assert title in titles
    for kind in expected:
        selector = window.services_model_choices[kind]
        assert selector.isVisible() and selector.count() > 0
        assert window.services_overview.isAncestorOf(selector)
        assert window.services_advanced_buttons[kind].isVisible()
        assert all(not selector.itemIcon(i).isNull() for i in range(selector.count()))


@pytest.mark.parametrize('kind', ['asr', 'llm', 'ask'])
def test_advanced_enters_a_separate_detail_page_and_back_returns_to_hub(window, kind):
    saved = deepcopy(window.store.config)
    emitted = []
    window.service_test.connect(lambda *args: emitted.append(args))
    QTest.mouseClick(window.services_advanced_buttons[kind], Qt.LeftButton)
    assert window.services_stack.currentWidget().isAncestorOf(window.services_subpages[kind])
    assert window.services_stack.currentWidget() is not window.services_overview
    assert isinstance(window.services_subpages[kind], QScrollArea)
    assert window.services_back_buttons[kind].isVisible()
    assert all(page.isVisible() == (service == kind) for service, page in window.services_subpages.items())
    field = {'asr': 'asr_backend', 'llm': 'llm_model', 'ask': 'ask_llm_model'}[kind]
    assert window.services_subpages[kind].isAncestorOf(window.fields[field])
    QTest.mouseClick(window.services_back_buttons[kind], Qt.LeftButton)
    assert window.services_stack.currentWidget() is window.services_overview
    assert window.store.config == saved and not window.store.path.exists()
    assert emitted == []


@pytest.mark.parametrize('choice, backend, engine', [
    ('paraformer', 'offline', 'paraformer'),
    ('qwen_asr', 'offline', 'qwen_asr'),
    ('bailian', 'bailian', None),
    ('ali_nls', 'ali_nls', None),
])
def test_speech_choice_updates_only_the_speech_draft(window, choice, backend, engine):
    saved = deepcopy(window.store.config)
    ask = _ask_snapshot(window)
    text = (window.fields['llm_url'].text(), window.fields['llm_model'].text())
    emitted = []
    window.service_test.connect(lambda *args: emitted.append(args))
    _select_model(window.services_model_choices['asr'], choice)
    assert window.fields['asr_backend'].currentData() == backend
    if engine is not None:
        assert window.fields['offline_engine'].currentData() == engine
    assert (window.fields['llm_url'].text(), window.fields['llm_model'].text()) == text
    assert _ask_snapshot(window) == ask
    assert window.store.config == saved and not window.store.path.exists()
    assert emitted == []


def test_text_four_billion_and_deepseek_choices_leave_ask_independent(window):
    saved = deepcopy(window.store.config)
    ask = _ask_snapshot(window)
    emitted = []
    window.service_test.connect(lambda *args: emitted.append(args))
    _select_model(window.services_model_choices['llm'], '4b')
    assert window.fields['llm_model'].text() == 'qwen3.5:4b'
    assert window.fields['ollama_auto'].currentData() is False
    assert 'qwen3.5:4b' in window.service_overview_models['llm'].text()
    assert _ask_snapshot(window) == ask
    _select_model(window.services_model_choices['llm'], 'online')
    assert window.fields['llm_model'].text() == saved['online_llm_model'] == 'deepseek-chat'
    assert window.fields['llm_url'].text().rstrip('/') == 'https://api.deepseek.com/v1'
    assert window.fields['ollama'].currentData() is False
    assert _ask_snapshot(window) == ask
    assert 'synthetic-ask-model' in window.service_overview_models['ask'].text()
    assert window.store.config == saved and not window.store.path.exists()
    assert emitted == []


def test_opening_hub_preserves_a_custom_ask_configuration(window):
    ask = _ask_snapshot(window)
    assert ask == ('https://ask.example.invalid/v1', 'synthetic-ask-model', '')
    assert window.services_model_choices['ask'].currentData() == 'custom'
    window.show_service_settings('ask')
    window.show_services_overview()
    window.update_services_overview()
    assert _ask_snapshot(window) == ask
    assert 'synthetic-ask-model' in window.service_overview_models['ask'].text()


def test_ask_model_choice_changes_only_the_independent_assistant_draft(window):
    saved = deepcopy(window.store.config)
    before = {key: window.fields[key].currentData() if key in ('asr_backend', 'offline_engine', 'ollama', 'ollama_auto')
              else window.fields[key].text()
              for key in ('asr_backend', 'offline_engine', 'llm_url', 'llm_model', 'ollama', 'ollama_auto')}
    window.fields['ask_llm_url'].setText('https://api.deepseek.com/v1')
    window.ask_llm_key.setText('synthetic-assistant-key')
    emitted = []
    window.service_test.connect(lambda *args: emitted.append(args))
    _select_model(window.services_model_choices['ask'], 'deepseek')
    assert window.fields['ask_llm_url'].text().rstrip('/') == 'https://api.deepseek.com/v1'
    assert window.fields['ask_llm_model'].text() == 'deepseek-flash'
    assert window.ask_llm_key.text() == 'synthetic-assistant-key'
    for key, expected in before.items():
        field = window.fields[key]
        actual = field.currentData() if key in ('asr_backend', 'offline_engine', 'ollama', 'ollama_auto') else field.text()
        assert actual == expected
    assert window.store.config == saved and not window.store.path.exists()
    assert emitted == []


@pytest.mark.parametrize('kind', ['asr', 'llm', 'ask'])
def test_busy_service_locks_model_choice_but_keeps_advanced_and_back_navigation(window, kind):
    emitted = []
    window.service_test.connect(lambda *args: emitted.append(args))
    window.set_service_test_state(kind, True)
    selector = window.services_model_choices[kind]
    index = selector.currentIndex()
    assert not selector.isEnabled()
    assert window.services_advanced_buttons[kind].isEnabled()
    QTest.mouseClick(selector, Qt.LeftButton)
    assert selector.currentIndex() == index
    QTest.mouseClick(window.services_advanced_buttons[kind], Qt.LeftButton)
    assert window.services_stack.currentWidget().isAncestorOf(window.services_subpages[kind])
    QTest.mouseClick(window.services_back_buttons[kind], Qt.LeftButton)
    assert window.services_stack.currentWidget() is window.services_overview
    assert window.service_test_busy[kind] and not window.save_button.isEnabled()
    assert emitted == []
    window.set_service_test_state(kind, False, 'Connected', 'Synthetic completed check.', True)
    assert selector.isEnabled() and window.save_button.isEnabled()


def _dpi_probe(data_root):
    """Called by an isolated Qt process, with no private profile or live services."""
    app = QApplication.instance() or QApplication([])
    for font in ('segoeui.ttf', 'segoeuib.ttf'):
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + font)
    storage.credential = lambda *args: ''
    storage.DEFAULT_OFFLINE_MODELS_ROOT = Path(data_root) / 'models'
    from murmur import windows
    windows.prepare_text_context = lambda: None
    import sounddevice
    sounddevice.query_devices = lambda: []
    import httpx
    requests = []
    def forbidden_request(*args, **kwargs):
        requests.append('unexpected request')
        raise RuntimeError('No services are permitted in the geometry fixture')
    httpx.Client = forbidden_request
    store = storage.Store(Path(data_root) / 'data')
    _seed_config(store)
    window = MainWindow(store)
    window.setStyleSheet(STYLE)
    window.navigate(3)
    window.settings_tabs.setCurrentIndex(1)
    window.show()
    QTest.qWait(200)
    assert window.services_stack.currentWidget() is window.services_overview
    home = window.services_overview
    for kind in ('asr', 'llm', 'ask'):
        for control in (window.services_model_choices[kind], window.services_advanced_buttons[kind],
                        window.service_overview_models[kind], window.service_overview_status[kind]):
            assert control.isVisible(), (kind, type(control).__name__, 'hidden')
            top = control.mapTo(home, QPoint(0, 0))
            bottom = control.mapTo(home, control.rect().bottomRight())
            assert home.rect().contains(top) and home.rect().contains(bottom), (kind, type(control).__name__, 'clipped')
    visible_scrolls = [scroll for scroll in window.findChildren(QScrollArea) if scroll.isVisible()]
    assert all(scroll.verticalScrollBar().maximum() == 0 and scroll.horizontalScrollBar().maximum() == 0
               for scroll in visible_scrolls), 'The Services home must not require scrolling'
    assert window.save_button.isVisible()
    assert window.rect().contains(window.save_button.mapTo(window, window.save_button.rect().bottomRight()))
    assert not requests and not store.path.exists()
    print(json.dumps({'dpr': window.devicePixelRatioF(), 'visible_scroll_areas': len(visible_scrolls),
                      'size': [window.width(), window.height()]}))
    window.hide()
    store.db.close()


@pytest.mark.parametrize('scale', [1.25, 1.5])
def test_fixed_services_home_fits_at_125_and_150_percent(tmp_path, scale):
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_SCALE_FACTOR=str(scale),
               QT_SCALE_FACTOR_ROUNDING_POLICY='PassThrough', QT_FONT_DPI='96')
    code = "import runpy, sys; runpy.run_path(sys.argv[1])['_dpi_probe'](sys.argv[2])"
    result = subprocess.run([sys.executable, '-B', '-c', code, str(Path(__file__).resolve()), str(tmp_path)],
                            cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True,
                            text=True, encoding='utf-8', errors='replace', timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout
    probe = json.loads(result.stdout.strip().splitlines()[-1])
    assert probe['dpr'] == pytest.approx(scale)
    assert probe['size'] == [920, 680]

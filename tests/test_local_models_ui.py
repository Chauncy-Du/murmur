"""Local ASR choices retain imported paths and freeze download destinations."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import threading
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from murmur import storage
from murmur.app import Controller
from murmur.dashboard import MainWindow


@pytest.fixture(autouse=True)
def shared_model_root(tmp_path, monkeypatch):
    root = tmp_path / 'shared-models'
    monkeypatch.setattr(storage, 'DEFAULT_OFFLINE_MODELS_ROOT', root)
    return root


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(storage, 'credential', lambda *args: '')
    import sounddevice
    monkeypatch.setattr(sounddevice, 'query_devices', lambda: [])
    store = storage.Store(tmp_path)
    widget = MainWindow(store)
    yield widget
    widget.hide()
    store.db.close()


def test_local_engine_switch_keeps_custom_folders_and_language_preference(window, tmp_path):
    engine = window.fields['offline_engine']
    folder = window.fields['offline_model_dir']
    language = window.fields['offline_language']
    assert window.fields['asr_backend'].itemData(0) == 'offline'
    assert engine.currentData() == 'sensevoice'
    custom_sensevoice = str(tmp_path / 'imported-sensevoice')
    custom_paraformer = str(tmp_path / 'imported-capswriter')
    folder.setText(custom_sensevoice)
    language.setCurrentIndex(language.findData('ja'))
    engine.setCurrentIndex(engine.findData('paraformer'))
    assert folder.text() == str(tmp_path / 'shared-models' / 'paraformer-zh')
    assert not language.isEnabled()
    assert 'automatically' in window.offline_language_hint.text()
    folder.setText(custom_paraformer)
    engine.setCurrentIndex(engine.findData('sensevoice'))
    assert folder.text() == custom_sensevoice
    assert language.isEnabled() and language.currentData() == 'ja'
    engine.setCurrentIndex(engine.findData('paraformer'))
    assert folder.text() == custom_paraformer
    values, _ = window._settings_snapshot()
    assert values['offline_engine'] == 'paraformer'
    assert values['offline_model_dir'] == custom_paraformer
    assert values['offline_language'] == 'ja'
    assert window.store.config['offline_engine'] == 'sensevoice'


def test_imported_fp32_model_readiness_and_selected_engine_feedback(window, tmp_path):
    window.fields['offline_engine'].setCurrentIndex(window.fields['offline_engine'].findData('paraformer'))
    model_folder = tmp_path / 'capswriter-model'
    model_folder.mkdir()
    (model_folder / 'model.onnx').write_bytes(b'fixture-model')
    (model_folder / 'tokens.txt').write_text('fixture', encoding='utf-8')
    window.fields['offline_model_dir'].setText(str(model_folder))
    assert 'Paraformer' in window.offline_status.text()
    assert 'files found' in window.offline_status.text()
    assert 'Silero VAD' in window.offline_status.text()
    (model_folder / 'silero_vad.onnx').write_bytes(b'fixture-vad')
    window.update_offline_readiness()
    assert 'Test below to verify' in window.offline_status.text()
    (model_folder / 'tokens.txt').unlink()
    window.update_offline_readiness()
    assert 'files are missing' in window.offline_status.text()


def test_model_switch_invalidates_connection_result(window):
    window.set_service_test_state('asr', False, 'Ready', 'SenseVoice verified.', True)
    window.fields['offline_engine'].setCurrentIndex(window.fields['offline_engine'].findData('paraformer'))
    assert all(status.text() == 'Not checked' and not details.isEnabled() for _, status, details in window.service_test_controls['asr'])


def test_asr_snapshot_changes_when_only_model_engine_changes():
    cfg = dict(storage.DEFAULTS)
    first = Controller.service_snapshot('asr', cfg, {})
    cfg['offline_engine'] = 'paraformer'
    assert Controller.service_snapshot('asr', cfg, {}) != first


@pytest.fixture
def controller(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(storage, 'credential', lambda *args: '')
    import sounddevice
    monkeypatch.setattr(sounddevice, 'query_devices', lambda: [])
    c = Controller(app, storage.Store(tmp_path), False)
    yield c
    c.model_cancel.set()
    c.quitting = True
    c.monitor.stop()
    for widget in (c.tray, c.bubble, c.result_bubble, c.preview, c.window):
        widget.hide()
    c.store.db.close()


@pytest.mark.parametrize('fails', [False, True])
def test_download_uses_selected_model_and_freezes_destination(controller, monkeypatch, fails):
    from murmur import models
    c = controller
    engine = c.window.fields['offline_engine']
    engine.setCurrentIndex(engine.findData('paraformer'))
    folder = c.window.fields['offline_model_dir'].text()
    entered, release = threading.Event(), threading.Event()
    seen = []

    def install(selected, destination, progress, cancel):
        seen.append((selected, destination))
        entered.set()
        assert release.wait(2)
        if fails:
            raise RuntimeError('Synthetic failure')
    monkeypatch.setattr(models, 'install_model', install)
    c.install_offline()
    try:
        assert entered.wait(2)
        assert seen == [('paraformer', folder)]
        assert c.model_busy and not c.window.offline_download.isEnabled()
        assert not engine.isEnabled() and not c.window.fields['offline_model_dir'].isEnabled()
        assert not c.window.offline_browse.isEnabled()
        backend = c.window.fields['asr_backend']
        backend.setCurrentIndex(backend.findData('bailian'))
        backend.setCurrentIndex(backend.findData('offline'))
        assert not engine.isEnabled() and not c.window.fields['offline_model_dir'].isEnabled()
        c.install_offline()
        assert len(seen) == 1
    finally:
        release.set()
    for _ in range(200):
        if not c.model_busy:
            break
        QTest.qWait(10)
    assert not c.model_busy
    assert engine.isEnabled() and c.window.fields['offline_model_dir'].isEnabled()
    assert c.window.offline_browse.isEnabled() and c.window.offline_download.isEnabled()
    assert ('Download failed' if fails else 'downloaded and verified') in c.window.offline_status.text()


@pytest.mark.parametrize('engine, imported', [('sensevoice', False), ('sensevoice', True), ('paraformer', False), ('paraformer', True)])
def test_cli_engine_override_selects_matching_folder(tmp_path, monkeypatch, engine, imported):
    import sys
    import wave
    from murmur import app as app_module, offline
    profile = tmp_path / 'profile'
    store = storage.Store(profile)
    custom_sensevoice = str(tmp_path / 'custom-sensevoice')
    store.config.update(offline_engine='sensevoice', offline_model_dir=custom_sensevoice)
    store.save()
    store.db.close()
    wav_path = tmp_path / 'sample.wav'
    with wave.open(str(wav_path), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b'\0' * 3200)
    output = tmp_path / 'result.txt'
    argv = ['murmur', '--data-dir', str(profile), '--transcribe-wav', str(wav_path), '--output-file', str(output), '--offline-engine', engine]
    explicit = str(tmp_path / 'imported-model')
    if imported:
        argv += ['--offline-model-dir', explicit]
    monkeypatch.setattr(sys, 'argv', argv)
    seen = []
    monkeypatch.setattr(offline, 'transcribe_pcm', lambda pcm, cfg: seen.append(cfg) or 'Fixture recognition')
    assert app_module.main() == 0
    assert seen[0]['offline_engine'] == engine
    expected = explicit if imported else custom_sensevoice if engine == 'sensevoice' else str(tmp_path / 'shared-models' / 'paraformer-zh')
    assert seen[0]['offline_model_dir'] == expected
    assert output.read_text(encoding='utf-8') == 'Fixture recognition'



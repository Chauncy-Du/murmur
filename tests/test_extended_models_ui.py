"""Four local speech models share settings without mixing model formats."""
import json
import os
import sys
import wave

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtWidgets import QApplication

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


@pytest.mark.parametrize('engine,folder', [
    ('sensevoice', 'sensevoice-small'), ('paraformer', 'paraformer-zh'),
    ('fun_asr_nano', 'fun-asr-nano'), ('qwen_asr', 'qwen3-asr'),
])
def test_all_engines_round_trip_with_their_default_folder(tmp_path, engine, folder):
    (tmp_path / 'settings.json').write_text(json.dumps({'offline_engine': engine}), 'utf-8')
    store = storage.Store(tmp_path)
    try:
        assert store.config['offline_engine'] == engine
        assert store.config['offline_acceleration'] == 'cpu'
        assert store.config['offline_model_dir'] == str(tmp_path / 'shared-models' / folder)
        assert store.config['demo'] is False
        assert store.config['dictation_key'] == 'right_alt'
        store.save()
        assert json.loads(store.path.read_text('utf-8'))['offline_engine'] == engine
    finally:
        store.db.close()


def test_sensevoice_gpu_has_its_own_default_folder(tmp_path):
    (tmp_path / 'settings.json').write_text(json.dumps({'offline_acceleration': 'gpu'}), 'utf-8')
    store = storage.Store(tmp_path)
    try:
        assert store.config['offline_model_dir'] == str(tmp_path / 'shared-models' / 'sensevoice-small-dml')
        assert storage.default_offline_model_dir(engine='sensevoice', acceleration='gpu') == tmp_path / 'shared-models' / 'sensevoice-small-dml'
    finally:
        store.db.close()


@pytest.mark.parametrize('invalid', [None, True, 'cuda', 'auto', []])
def test_invalid_acceleration_defaults_to_cpu(invalid):
    assert storage.validated_config({'offline_acceleration': invalid})['offline_acceleration'] == 'cpu'


def test_paraformer_settings_use_cpu():
    assert storage.validated_config({'offline_engine': 'paraformer', 'offline_acceleration': 'gpu'})['offline_acceleration'] == 'cpu'


def test_engine_menu_has_four_models_and_keeps_imported_folders(window, tmp_path):
    engine = window.fields['offline_engine']
    folder = window.fields['offline_model_dir']
    assert [engine.itemData(i) for i in range(engine.count())] == ['sensevoice', 'paraformer', 'fun_asr_nano', 'qwen_asr']
    custom = {}
    for selected in ('sensevoice', 'fun_asr_nano', 'qwen_asr', 'paraformer'):
        engine.setCurrentIndex(engine.findData(selected))
        custom[selected] = str(tmp_path / ('imported-' + selected))
        folder.setText(custom[selected])
    for selected in custom:
        engine.setCurrentIndex(engine.findData(selected))
        assert folder.text() == custom[selected]
    assert window.store.config['offline_engine'] == 'sensevoice'


def test_sensevoice_acceleration_keeps_separate_custom_model_folders(window, tmp_path):
    acceleration = window.fields['offline_acceleration']
    folder = window.fields['offline_model_dir']
    cpu = str(tmp_path / 'custom-int8')
    gpu = str(tmp_path / 'custom-split-onnx')
    folder.setText(cpu)
    acceleration.setCurrentIndex(acceleration.findData('gpu'))
    assert folder.text() == str(tmp_path / 'shared-models' / 'sensevoice-small-dml')
    folder.setText(gpu)
    acceleration.setCurrentIndex(acceleration.findData('cpu'))
    assert folder.text() == cpu
    acceleration.setCurrentIndex(acceleration.findData('gpu'))
    assert folder.text() == gpu
    values, _ = window._settings_snapshot()
    assert values['offline_acceleration'] == 'gpu'
    assert values['offline_model_dir'] == gpu


@pytest.mark.parametrize('engine,acceleration,folder', [
    ('sensevoice', 'cpu', 'sensevoice-small'),
    ('sensevoice', 'gpu', 'sensevoice-small-dml'),
    ('paraformer', 'cpu', 'paraformer-zh'),
    ('fun_asr_nano', 'gpu', 'fun-asr-nano'),
    ('qwen_asr', 'gpu', 'qwen3-asr'),
])
def test_model_switch_placeholder_and_browse_share_the_default_root(window, tmp_path, monkeypatch, engine, acceleration, folder):
    from murmur import dashboard
    engine_field = window.fields['offline_engine']
    engine_field.setCurrentIndex(engine_field.findData(engine))
    acceleration_field = window.fields['offline_acceleration']
    acceleration_field.setCurrentIndex(acceleration_field.findData(acceleration))
    directory_field = window.fields['offline_model_dir']
    expected = str(tmp_path / 'shared-models' / folder)
    assert directory_field.text() == expected
    assert directory_field.placeholderText() == expected
    directory_field.clear()
    seen = []
    imported = str(tmp_path / 'imported-model')

    def choose_directory(parent, title, starting_directory):
        seen.append(starting_directory)
        return imported

    monkeypatch.setattr(dashboard.QFileDialog, 'getExistingDirectory', choose_directory)
    window.browse_offline_model()
    assert seen == [expected]
    assert directory_field.text() == imported


@pytest.mark.parametrize('engine,folder', [('fun_asr_nano', 'fun-asr-nano'), ('qwen_asr', 'qwen3-asr')])
def test_gguf_execution_modes_share_default_weights(window, tmp_path, engine, folder):
    engine_field = window.fields['offline_engine']
    engine_field.setCurrentIndex(engine_field.findData(engine))
    acceleration_field = window.fields['offline_acceleration']
    directory_field = window.fields['offline_model_dir']
    expected = str(tmp_path / 'shared-models' / folder)
    assert directory_field.text() == expected
    for mode in ('gpu', 'cpu'):
        acceleration_field.setCurrentIndex(acceleration_field.findData(mode))
        assert directory_field.text() == expected


def test_paraformer_disables_gpu_execution(window):
    acceleration = window.fields['offline_acceleration']
    acceleration.setCurrentIndex(acceleration.findData('gpu'))
    engine = window.fields['offline_engine']
    engine.setCurrentIndex(engine.findData('paraformer'))
    assert acceleration.currentData() == 'cpu'
    assert not acceleration.model().item(acceleration.findData('gpu')).isEnabled()
    assert 'CPU execution only' in window.offline_acceleration_hint.text()
    engine.setCurrentIndex(engine.findData('qwen_asr'))
    assert acceleration.model().item(acceleration.findData('gpu')).isEnabled()


@pytest.mark.parametrize('selected', ['fun_asr_nano', 'qwen_asr'])
def test_gguf_readiness_requires_each_catalog_component(window, tmp_path, selected):
    from murmur.models import model_spec
    engine = window.fields['offline_engine']
    engine.setCurrentIndex(engine.findData(selected))
    folder = tmp_path / selected
    folder.mkdir()
    # Legacy SenseVoice/Paraformer files are insufficient for a GGUF engine.
    (folder / 'model.int8.onnx').write_bytes(b'fixture')
    (folder / 'tokens.txt').write_bytes(b'fixture')
    window.fields['offline_model_dir'].setText(str(folder))
    assert 'files are missing' in window.offline_status.text()
    info = model_spec(selected)
    for alternatives in info['required_files']:
        path = folder / alternatives[0]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fixture')
    (folder / 'silero_vad.onnx').write_bytes(b'fixture')
    window.update_offline_readiness()
    assert 'files found' in window.offline_status.text()
    assert info['name'] in window.offline_status.text()
    # A missing decoder must not pass based on ONNX presence alone.
    decoder = next(name for alternatives in info['required_files'] for name in alternatives if name.endswith('.gguf'))
    (folder / decoder).unlink()
    window.update_offline_readiness()
    assert 'files are missing' in window.offline_status.text()


def test_acceleration_change_invalidates_connection_result(window):
    cfg = dict(storage.DEFAULTS)
    before = Controller.service_snapshot('asr', cfg, {})
    cfg['offline_acceleration'] = 'gpu'
    assert Controller.service_snapshot('asr', cfg, {}) != before
    window.set_service_test_state('asr', False, 'Ready', 'CPU configuration verified.', True)
    acceleration = window.fields['offline_acceleration']
    acceleration.setCurrentIndex(acceleration.findData('gpu'))
    assert all(status.text() == 'Not checked' and not details.isEnabled() for _, status, details in window.service_test_controls['asr'])


def test_download_locks_every_local_model_setting(window):
    window.set_offline_download_state(True)
    for key in ('offline_engine', 'offline_model_dir', 'offline_acceleration', 'offline_language', 'offline_threads'):
        assert not window.fields[key].isEnabled()
    assert not window.offline_browse.isEnabled()
    window.set_offline_download_state(False)
    assert all(window.fields[key].isEnabled() for key in ('offline_engine', 'offline_model_dir', 'offline_acceleration', 'offline_language', 'offline_threads'))


@pytest.mark.parametrize('engine,acceleration,folder', [
    ('fun_asr_nano', 'cpu', 'fun-asr-nano'), ('qwen_asr', 'gpu', 'qwen3-asr'),
    ('sensevoice', 'gpu', 'sensevoice-small-dml'),
])
def test_cli_selects_extended_engine_and_execution_mode(tmp_path, monkeypatch, engine, acceleration, folder):
    from murmur import app as app_module, offline
    profile = tmp_path / 'profile'
    wav_path = tmp_path / 'sample.wav'
    with wave.open(str(wav_path), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b'\0' * 3200)
    output = tmp_path / 'result.txt'
    monkeypatch.setattr(sys, 'argv', ['murmur', '--data-dir', str(profile), '--transcribe-wav', str(wav_path), '--output-file', str(output), '--offline-engine', engine, '--offline-acceleration', acceleration])
    seen = []
    monkeypatch.setattr(offline, 'transcribe_pcm', lambda pcm, cfg: seen.append(cfg) or 'Fixture recognition')
    assert app_module.main() == 0
    assert seen[0]['offline_engine'] == engine
    assert seen[0]['offline_acceleration'] == acceleration
    assert seen[0]['offline_model_dir'] == str(tmp_path / 'shared-models' / folder)
    assert output.read_text('utf-8') == 'Fixture recognition'

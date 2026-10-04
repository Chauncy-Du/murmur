"""Speech weights use one root while profile data and custom paths stay intact."""
import json
import os
from pathlib import Path

import pytest

from murmur import storage


MODEL_SELECTIONS = [
    ('sensevoice', 'cpu', 'sensevoice-small'),
    ('sensevoice', 'gpu', 'sensevoice-small-dml'),
    ('paraformer', 'gpu', 'paraformer-zh'),
    ('fun_asr_nano', 'cpu', 'fun-asr-nano'),
    ('qwen_asr', 'gpu', 'qwen3-asr'),
]


@pytest.fixture(autouse=True)
def shared_model_root(tmp_path, monkeypatch):
    root = tmp_path / 'shared-models'
    monkeypatch.setattr(storage, 'DEFAULT_OFFLINE_MODELS_ROOT', root)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local-app-data'))
    return root


def save_settings(profile, **values):
    profile.mkdir(parents=True, exist_ok=True)
    path = profile / 'settings.json'
    path.write_text(json.dumps(values), encoding='utf-8')
    return path


@pytest.mark.parametrize('engine,acceleration,folder', MODEL_SELECTIONS)
def test_profiles_share_models_without_creating_or_moving_weights(tmp_path, shared_model_root, engine, acceleration, folder):
    for name in ('profile-a', 'profile-b'):
        profile = tmp_path / name
        save_settings(profile, offline_engine=engine, offline_acceleration=acceleration)
        store = storage.Store(profile)
        try:
            assert store.root == profile
            assert store.path == profile / 'settings.json'
            assert Path(store.config['offline_model_dir']) == shared_model_root / folder
            assert (profile / 'history.db').is_file()
            assert not (profile / 'models').exists()
        finally:
            store.db.close()
    assert not shared_model_root.exists()


@pytest.mark.parametrize('engine,acceleration,folder', MODEL_SELECTIONS)
@pytest.mark.parametrize('legacy_location', ['profile', 'local-app-data'])
def test_legacy_default_migrates_in_memory_then_survives_save(tmp_path, shared_model_root, engine, acceleration, folder, legacy_location):
    profile = tmp_path / 'profile'
    legacy_root = profile if legacy_location == 'profile' else Path(os.environ['LOCALAPPDATA']) / 'MurMur'
    old_directory = str(legacy_root / 'models' / folder)
    path = save_settings(profile, offline_engine=engine, offline_acceleration=acceleration,
                         offline_model_dir=old_directory, microphone='custom-input', dictation_key='f9')
    original = path.read_bytes()
    store = storage.Store(profile)
    expected = str(shared_model_root / folder)
    try:
        assert store.config['offline_model_dir'] == expected
        assert store.config['microphone'] == 'custom-input'
        assert store.config['dictation_key'] == 'f9'
        assert path.read_bytes() == original
        store.save()
        assert json.loads(path.read_text('utf-8'))['offline_model_dir'] == expected
    finally:
        store.db.close()
    reopened = storage.Store(profile)
    try:
        assert reopened.config['offline_model_dir'] == expected
    finally:
        reopened.db.close()


@pytest.mark.parametrize('path_style', ['forward-slashes', 'trailing-separator', 'case'])
def test_windows_legacy_path_spelling_does_not_disable_migration(tmp_path, shared_model_root, path_style):
    if path_style == 'case' and os.name != 'nt':
        pytest.skip('Windows file paths are case insensitive')
    profile = tmp_path / 'profile'
    old = profile / 'models' / 'sensevoice-small'
    old_text = old.as_posix() if path_style == 'forward-slashes' else str(old) + os.sep if path_style == 'trailing-separator' else str(old).upper()
    save_settings(profile, offline_model_dir=old_text)
    store = storage.Store(profile)
    try:
        assert Path(store.config['offline_model_dir']) == shared_model_root / 'sensevoice-small'
    finally:
        store.db.close()


def test_resolved_appdata_default_is_migrated(tmp_path, shared_model_root, monkeypatch):
    profile = tmp_path / 'profile'
    logical = Path(os.environ['LOCALAPPDATA']) / 'MurMur' / 'models' / 'sensevoice-small'
    physical = tmp_path / 'package-cache' / 'MurMur' / 'models' / 'sensevoice-small'
    original_resolve = Path.resolve

    def redirected_resolve(path, *args, **kwargs):
        if path == logical:
            return physical
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'resolve', redirected_resolve)
    save_settings(profile, offline_model_dir=str(physical))
    store = storage.Store(profile)
    try:
        assert Path(store.config['offline_model_dir']) == shared_model_root / 'sensevoice-small'
    finally:
        store.db.close()


@pytest.mark.parametrize('kind', ['missing-custom', 'existing-custom', 'different-engine', 'unrecognized-folder'])
def test_custom_model_paths_are_preserved(tmp_path, kind):
    profile = tmp_path / 'profile'
    custom = {
        'missing-custom': tmp_path / 'external' / 'sensevoice-small',
        'existing-custom': tmp_path / 'existing-import',
        'different-engine': profile / 'models' / 'paraformer-zh',
        'unrecognized-folder': profile / 'models' / 'my-sensevoice',
    }[kind]
    if kind == 'existing-custom':
        custom.mkdir()
        (custom / 'tokens.txt').write_text('fixture', encoding='utf-8')
    path = save_settings(profile, offline_model_dir=str(custom))
    original = path.read_bytes()
    store = storage.Store(profile)
    try:
        assert store.config['offline_model_dir'] == str(custom)
        assert path.read_bytes() == original
        store.save()
    finally:
        store.db.close()
    reopened = storage.Store(profile)
    try:
        assert reopened.config['offline_model_dir'] == str(custom)
    finally:
        reopened.db.close()


def test_explicit_model_root_is_used_directly(tmp_path):
    custom_root = tmp_path / 'chosen-models'
    assert storage.default_offline_model_dir(custom_root, 'qwen_asr', 'gpu') == custom_root / 'qwen3-asr'
    assert not custom_root.exists()

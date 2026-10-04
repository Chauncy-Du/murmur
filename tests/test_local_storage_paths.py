"""Default storage and smoke isolation remain local without touching profiles."""
import importlib.util
import runpy
import sys
import types
from pathlib import Path

import pytest

from murmur import native_runtime, paths, storage


SOURCE_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    monkeypatch.setattr(paths, 'PROJECT_ROOT', project)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'legacy-appdata'))
    monkeypatch.delenv('MURMUR_LLAMA_BIN', raising=False)
    return project


def test_declared_defaults_use_the_local_project():
    project = Path(r'D:\LocalProjects\MurMur')
    assert paths.PROJECT_ROOT == project
    assert paths.data_dir() == project / 'data'
    assert paths.model_root() == project / 'models'
    assert paths.runtime_root() == project / 'runtimes'
    assert paths.startup_error_log() == project / 'data' / 'startup-error.log'
    assert storage.DEFAULT_OFFLINE_MODELS_ROOT == paths.model_root()


def test_default_store_reopens_the_same_local_profile(isolated_paths, tmp_path):
    store = storage.Store()
    try:
        assert store.root == isolated_paths / 'data'
        assert store.path == paths.data_dir() / 'settings.json'
        store.config['retention'] = 0
        store.config['dictation_key'] = 'f9'
        store.save()
        store.add('fixture', '听写', 'Fixture input', 'Fixture output', 1, 1, True)
    finally:
        store.db.close()
    reopened = storage.Store()
    try:
        assert reopened.config['dictation_key'] == 'f9'
        assert [row['session'] for row in reopened.rows()] == ['fixture']
    finally:
        reopened.db.close()
    assert not (tmp_path / 'legacy-appdata' / 'MurMur').exists()


def test_explicit_store_root_remains_isolated(isolated_paths, tmp_path):
    explicit = tmp_path / 'isolated-profile'
    store = storage.Store(explicit)
    try:
        assert store.root == explicit
        assert store.path == explicit / 'settings.json'
        assert (explicit / 'history.db').is_file()
    finally:
        store.db.close()
    assert not paths.data_dir().exists()


def test_native_runtime_default_is_separate_from_profile(isolated_paths):
    assert native_runtime.runtime_dir() == (isolated_paths / 'runtimes' / ('llama-' + native_runtime.VERSION)).resolve()
    assert not isolated_paths.exists()


def test_native_runtime_environment_override_still_wins(isolated_paths, tmp_path, monkeypatch):
    override = tmp_path / 'custom-runtime'
    monkeypatch.setenv('MURMUR_LLAMA_BIN', str(override))
    assert native_runtime.runtime_dir() == override.resolve()
    assert not isolated_paths.exists()


def test_startup_failure_writes_to_local_data(isolated_paths, tmp_path, monkeypatch, capsys):
    fake_app = types.ModuleType('murmur.app')
    def fail():
        raise RuntimeError('Synthetic startup failure')
    fake_app.main = fail
    monkeypatch.setitem(sys.modules, 'murmur.app', fake_app)
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(SOURCE_ROOT / 'run.py'), run_name='__main__')
    assert exc.value.code == 1
    assert 'Synthetic startup failure' in paths.startup_error_log().read_text('utf-8')
    assert 'Synthetic startup failure' in capsys.readouterr().err
    assert not (tmp_path / 'legacy-appdata' / 'MurMur').exists()


@pytest.fixture
def smoke(isolated_paths):
    spec = importlib.util.spec_from_file_location('murmur_ask_smoke_path_test', SOURCE_ROOT / 'scripts' / 'ask_windows_smoke.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def smoke_args(monkeypatch, output, data=None):
    args = ['ask_windows_smoke.py', '--role', 'editor', '--scenario', 'answer', '--output-dir', str(output)]
    if data is not None:
        args += ['--data-dir', str(data)]
    monkeypatch.setattr(sys, 'argv', args)


@pytest.mark.parametrize('location', ['current', 'legacy'])
@pytest.mark.parametrize('child', [False, True])
def test_smoke_rejects_formal_profiles_even_if_empty(smoke, tmp_path, monkeypatch, capsys, location, child):
    output = tmp_path / 'public-output'
    output.mkdir()
    root = paths.data_dir() if location == 'current' else tmp_path / 'legacy-appdata' / 'MurMur'
    protected = root / 'empty-subfolder' if child else root
    protected.mkdir(parents=True)
    smoke_args(monkeypatch, output, protected)
    with pytest.raises(SystemExit) as exc:
        smoke.arguments()
    assert exc.value.code == 2
    assert 'Normal MurMur data cannot be used for this smoke' in capsys.readouterr().err


@pytest.mark.parametrize('location', ['current', 'legacy'])
@pytest.mark.parametrize('child', [False, True])
def test_smoke_output_cannot_write_into_formal_profiles(smoke, tmp_path, monkeypatch, capsys, location, child):
    root = paths.data_dir() if location == 'current' else tmp_path / 'legacy-appdata' / 'MurMur'
    protected = root / 'empty-output' if child else root
    protected.mkdir(parents=True)
    smoke_args(monkeypatch, protected)
    with pytest.raises(SystemExit) as exc:
        smoke.arguments()
    assert exc.value.code == 2
    assert 'Normal MurMur data cannot be used for smoke output' in capsys.readouterr().err


def test_smoke_accepts_an_unrelated_empty_profile(smoke, tmp_path, monkeypatch):
    output = tmp_path / 'public-output'
    output.mkdir()
    isolated = paths.data_dir().with_name('data-smoke')
    smoke_args(monkeypatch, output, isolated)
    args = smoke.arguments()
    assert args.data_dir == isolated.resolve()
    assert args.output_dir == output.resolve()
    assert not paths.data_dir().exists()


def test_smoke_still_rejects_nonempty_isolated_profiles(smoke, tmp_path, monkeypatch, capsys):
    output = tmp_path / 'public-output'
    output.mkdir()
    isolated = tmp_path / 'smoke-profile'
    isolated.mkdir()
    (isolated / 'fixture.txt').write_text('Fixture', 'utf-8')
    smoke_args(monkeypatch, output, isolated)
    with pytest.raises(SystemExit):
        smoke.arguments()
    assert 'absent or an empty isolated directory' in capsys.readouterr().err

"""A transient Windows file lock must not lose the last saved settings."""
import json
from pathlib import Path
import pytest
from murmur import storage


def lock_error(code):
    error = PermissionError('Fixture file lock')
    error.winerror = code
    return error


def test_short_windows_lock_recovers_atomic_save(tmp_path, monkeypatch):
    store = storage.Store(tmp_path)
    store.save()
    store.config['style'] = 'Changed style'
    original = Path.replace
    calls, delays = [], []
    def replace(path, target):
        calls.append(path)
        if len(calls) < 3: raise lock_error(32)
        return original(path, target)
    monkeypatch.setattr(Path, 'replace', replace)
    monkeypatch.setattr(storage.time, 'sleep', delays.append)
    store.save()
    assert len(calls) == 3 and delays == [.02, .04]
    assert json.loads(store.path.read_text('utf-8'))['style'] == 'Changed style'
    assert not store.path.with_suffix('.tmp').exists()
    store.db.close()


def test_persistent_lock_is_bounded_and_keeps_original(tmp_path, monkeypatch):
    store = storage.Store(tmp_path)
    store.save()
    original = store.path.read_bytes()
    store.config['style'] = 'Unsaved style'
    calls, delays = [], []
    def replace(path, target):
        calls.append(path)
        raise lock_error(5)
    monkeypatch.setattr(Path, 'replace', replace)
    monkeypatch.setattr(storage.time, 'sleep', delays.append)
    with pytest.raises(PermissionError): store.save()
    assert len(calls) == 4 and delays == [.02, .04, .08]
    assert store.path.read_bytes() == original
    store.db.close()


def test_unrelated_permission_error_is_not_retried(tmp_path, monkeypatch):
    store = storage.Store(tmp_path)
    delays = []
    def replace(path, target): raise lock_error(1314)
    monkeypatch.setattr(Path, 'replace', replace)
    monkeypatch.setattr(storage.time, 'sleep', delays.append)
    with pytest.raises(PermissionError): store.save()
    assert not delays and not store.path.exists()
    store.db.close()

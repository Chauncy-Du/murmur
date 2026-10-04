"""Transaction and element identity tests; no external application is modified."""
import queue
from murmur import windows


def test_unknown_element_is_never_safe(monkeypatch):
    t=windows.Target(10,11,12)
    monkeypatch.setattr(windows,'window_valid',lambda expected:True)
    monkeypatch.setattr(windows,'target',lambda:t)
    assert not windows.valid(t)


def test_same_window_different_uia_element_is_rejected(monkeypatch):
    first=windows.Target(10,11,12,(42,1),12,True)
    second=windows.Target(10,11,12,(42,2),12,True)
    monkeypatch.setattr(windows,'window_valid',lambda expected:True)
    monkeypatch.setattr(windows,'target',lambda:second)
    assert not windows.valid(first)
    assert windows.valid(second)


def test_read_only_element_is_never_safe(monkeypatch):
    t=windows.Target(10,11,12,(42,1),12,False)
    monkeypatch.setattr(windows,'window_valid',lambda expected:True)
    monkeypatch.setattr(windows,'target',lambda:t)
    assert not windows.valid(t)


def test_uia_timeout_returns_unknown_instead_of_stale_identity():
    reader=windows._FocusReader.__new__(windows._FocusReader);reader.requests=queue.Queue(maxsize=1)
    assert reader.read(windows.Target(10,11,12),timeout=.001) is None
    assert reader.read(windows.Target(10,11,12),timeout=.001) is None


def test_clipboard_capture_requires_target_owner(monkeypatch):
    tx=windows.ClipboardTransaction.__new__(windows.ClipboardTransaction)
    t=windows.Target(10,11,12,(42,1),13,True)
    for pid,allowed in [(12,True),(13,True),(14,False),(0,False)]:
        monkeypatch.setattr(windows,'clipboard_owner_pid',lambda pid=pid:pid)
        assert tx.owned_by(t)==allowed

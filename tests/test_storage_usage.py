import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from types import SimpleNamespace
import stat
import threading

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from murmur import storage_usage
from murmur.storage_usage import StorageSnapshot,scan_storage,LocalStorageUsage
from murmur.storage import Store,validated_config

_APPLICATION=QApplication.instance() or QApplication([])


def test_storage_counts_files_and_sidecars_without_reading_or_modifying_them(tmp_path,monkeypatch):
    files={'history.db':100,'history.db-wal':20,'history.db-shm':10,
           'audio/a.wav':1000,'audio/nested/b.wav':2000,'settings.json':12,'logs/error.txt':15}
    for name,size in files.items():
        file=tmp_path/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(b'x'*size)
    monkeypatch.setattr(Path,'read_bytes',lambda *a:pytest.fail('Usage read file contents'))
    snapshot=scan_storage(tmp_path)
    assert snapshot==StorageSnapshot(history=130,recordings=3000,other=27)
    assert snapshot.total==sum(files.values())
    assert {p.relative_to(tmp_path).as_posix():p.stat().st_size for p in tmp_path.rglob('*') if p.is_file()}==files


def test_unavailable_directory_marks_the_snapshot_partial(tmp_path,monkeypatch):
    monkeypatch.setattr(storage_usage.os,'scandir',lambda *a:(_ for _ in ()).throw(PermissionError()))
    assert scan_storage(tmp_path)==StorageSnapshot(unavailable=1)


def test_reparse_directory_is_not_followed(tmp_path,monkeypatch):
    class Entry:
        name='external';path=str(tmp_path/'external')
        def stat(self,**kwargs):return SimpleNamespace(st_mode=stat.S_IFDIR,st_file_attributes=0x400)
    class Entries:
        def __enter__(self):return iter([Entry()])
        def __exit__(self,*args):pass
    calls=[]
    monkeypatch.setattr(storage_usage.os,'scandir',lambda path:(calls.append(path) or Entries()))
    assert scan_storage(tmp_path)==StorageSnapshot(unavailable=1)
    assert calls==[tmp_path]


def test_new_defaults_preserve_existing_explicit_preferences(tmp_path):
    defaults=validated_config({})
    assert (defaults['bubble_offset'],defaults['retention'],defaults['save_audio'])==(20,0,True)
    old=validated_config({'bubble_offset':48,'retention':90,'save_audio':False})
    assert (old['bubble_offset'],old['retention'],old['save_audio'])==(48,90,False)
    store=Store(tmp_path)
    store.config['bubble_wave_style']='centered';store.save();store.db.close()
    reopened=Store(tmp_path)
    assert reopened.config['bubble_wave_style']=='centered'
    assert validated_config({'bubble_wave_style':'invalid'})['bubble_wave_style']=='bars'
    reopened.db.close()


def test_usage_scan_is_off_gui_thread_and_refreshes_after_file_changes(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    worker_threads=[];original=scan_storage
    def measure(root):worker_threads.append(threading.get_ident());return original(root)
    monkeypatch.setattr(storage_usage,'scan_storage',measure)
    widget=LocalStorageUsage(tmp_path);widget.show()
    for _ in range(100):
        QTest.qWait(5)
        if not widget._busy:break
    assert widget.bar.snapshot.total==0 and widget.total_label.text()=='0 B'
    (tmp_path/'audio').mkdir();(tmp_path/'audio/test.wav').write_bytes(b'x'*1000)
    (tmp_path/'history.db').write_bytes(b'x'*250)
    widget.refresh()
    for _ in range(100):
        QTest.qWait(5)
        if not widget._busy:break
    assert widget.bar.snapshot.total==1250
    assert widget.part_labels['history'][1].text()=='20.0%'
    assert widget.part_labels['recordings'][1].text()=='80.0%'
    assert all(ident!=threading.get_ident() for ident in worker_threads)
    widget.set_snapshot(StorageSnapshot(history=250,unavailable=1))
    assert widget.total_label.text().startswith('At least ') and 'known total' in widget.notice.text()
    widget.hide();assert not widget.timer.isActive()


def test_window_can_be_destroyed_while_a_pure_io_scan_finishes(tmp_path,monkeypatch):
    import shiboken6
    started=threading.Event();release=threading.Event();finished=threading.Event()
    def measure(root):
        started.set();release.wait(2);finished.set();return StorageSnapshot(history=10)
    monkeypatch.setattr(storage_usage,'scan_storage',measure)
    widget=LocalStorageUsage(tmp_path);widget.show()
    assert started.wait(.5)
    widget.hide();shiboken6.delete(widget);release.set()
    assert finished.wait(.5)

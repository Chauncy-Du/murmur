"""Synthetic SQLite contention, durable cleanup and canonical dictionary tests."""
import json
import os
import sqlite3
import time
from pathlib import Path

import pytest
from murmur.storage import Store


@pytest.fixture
def store(tmp_path):
    value=Store(tmp_path)
    yield value
    value.db.close()


def add_audio(store,session='fixture',age=None):
    path=store.root/'audio'/f'{session}.wav'
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(b'SYNTHETIC FILE ONLY; NO RECORDED AUDIO')
    store.add(session,'听写','Fixture original','Fixture result',1,0,True,audio=str(path))
    if age:
        store.db.execute('UPDATE history SET time=? WHERE session=?',(age,session));store.db.commit()
    return path,next(row['id'] for row in store.rows() if row['session']==session)


def lock_database(store,kind='writer'):
    connection=sqlite3.connect(store.root/'history.db',timeout=0)
    connection.execute('BEGIN IMMEDIATE' if kind=='writer' else 'BEGIN')
    if kind=='reader':connection.execute('SELECT * FROM history').fetchall()
    return connection


@pytest.mark.parametrize('kind',['writer','reader'])
def test_delete_transaction_failure_preserves_row_audio_and_rolls_back_queue(store,kind):
    path,ident=add_audio(store)
    lock=lock_database(store,kind)
    try:
        assert 0<store.db.execute('PRAGMA busy_timeout').fetchone()[0]<=250
        started=time.monotonic()
        with pytest.raises(sqlite3.OperationalError):store.delete([ident])
        assert time.monotonic()-started<.8
        assert path.exists() and len(store.rows())==1
        assert not store.db.in_transaction
        assert not store.db.execute('SELECT * FROM pending_audio_delete').fetchall()
    finally:
        lock.rollback();lock.close()
    assert store.delete([ident])==0 and not path.exists() and not store.rows()


def test_multi_record_delete_is_one_transaction(store):
    one,first=add_audio(store,'first');two,second=add_audio(store,'reject')
    store.db.execute("CREATE TRIGGER fail_second BEFORE DELETE ON history WHEN OLD.session='reject' BEGIN SELECT RAISE(ABORT,'fixture only'); END")
    store.db.commit()
    with pytest.raises(sqlite3.IntegrityError):store.delete([first,second])
    assert one.exists() and two.exists() and len(store.rows())==2
    assert not store.db.in_transaction
    assert not store.db.execute('SELECT * FROM pending_audio_delete').fetchall()


@pytest.mark.parametrize('mutation',['history','usage','add_word','delete_word'])
def test_actual_writer_lock_is_bounded_and_failed_mutation_recovers(store,mutation):
    before=store.words();hotwords=store.config['hotwords']
    lock=lock_database(store)
    actions={'history':lambda:store.add('failed','听写','raw','final',0,0,True),
             'usage':lambda:store.record_usage({'request_id':'fixture-usage'}),
             'add_word':lambda:store.add_word('Fixture blocked word'),
             'delete_word':lambda:store.delete_word(before[0]['word'])}
    try:
        started=time.monotonic()
        with pytest.raises(sqlite3.OperationalError):actions[mutation]()
        assert time.monotonic()-started<.8
        assert not store.db.in_transaction
        assert store.words()==before and store.config['hotwords']==hotwords
    finally:
        lock.rollback();lock.close()
    store.add('next','听写','raw','final',0,0,True)
    assert len(store.rows())==1


def test_locked_schema_initialization_is_bounded_and_recoverable(tmp_path):
    connection=sqlite3.connect(tmp_path/'history.db',timeout=0)
    connection.execute('BEGIN IMMEDIATE')
    try:
        started=time.monotonic()
        with pytest.raises(sqlite3.OperationalError):Store(tmp_path)
        assert time.monotonic()-started<.8
    finally:
        connection.rollback();connection.close()
    recovered=Store(tmp_path)
    assert recovered.words()
    recovered.db.close()


def test_queued_cleanup_survives_interruption_after_sql_commit(store,monkeypatch):
    path,ident=add_audio(store)
    monkeypatch.setattr(store,'cleanup_audio',lambda:1)
    assert store.delete([ident])==1
    assert not store.rows() and path.exists()
    assert len(store.db.execute('SELECT * FROM pending_audio_delete').fetchall())==1
    store.db.close()
    reopened=Store(store.root)
    try:
        assert not path.exists() and not reopened.rows()
        assert not reopened.db.execute('SELECT * FROM pending_audio_delete').fetchall()
        assert not reopened.cleanup_warning
    finally:reopened.db.close()


def test_cleanup_stops_after_first_database_lock_instead_of_waiting_per_file(store,monkeypatch):
    files=[add_audio(store,f'fixture-{i}') for i in range(5)]
    real_cleanup=store.cleanup_audio
    monkeypatch.setattr(store,'cleanup_audio',lambda:5)
    store.delete([ident for path,ident in files])
    monkeypatch.setattr(store,'cleanup_audio',real_cleanup)
    lock=lock_database(store)
    try:
        started=time.monotonic()
        assert store.cleanup_audio()==5 and time.monotonic()-started<.8
        assert sum(not path.exists() for path,ident in files)==1
        assert not store.db.in_transaction
        assert len(store.db.execute('SELECT * FROM pending_audio_delete').fetchall())==5
    finally:lock.rollback();lock.close()
    assert store.cleanup_audio()==0 and all(not path.exists() for path,ident in files)


@pytest.mark.skipif(os.name!='nt',reason='Windows sharing-lock integration')
def test_actual_unlink_permission_failure_stays_queued_and_retries_on_reopen(store):
    import win32file,win32con
    path,ident=add_audio(store)
    handle=win32file.CreateFile(str(path),win32con.GENERIC_READ,win32con.FILE_SHARE_READ,
                               None,win32con.OPEN_EXISTING,0,None)
    try:
        assert store.delete([ident])==1
        assert path.exists() and not store.rows()
        assert 'History was deleted' in store.cleanup_warning
        assert str(path) not in store.cleanup_warning
        store.db.close()
        reopened=Store(store.root)
        try:
            assert reopened.cleanup_warning and path.exists()
            assert len(reopened.db.execute('SELECT * FROM pending_audio_delete').fetchall())==1
        finally:reopened.db.close()
    finally:handle.Close()
    final=Store(store.root)
    try:assert not path.exists() and not final.cleanup_warning
    finally:final.db.close()


def test_outside_audio_paths_are_never_deleted(store,tmp_path):
    outside=tmp_path/'outside.wav';outside.write_bytes(b'SYNTHETIC OUTSIDE FILE')
    store.add('outside','听写','raw','final',0,0,True,audio=str(outside))
    assert store.delete([store.rows()[0]['id']])==0
    assert outside.read_bytes()==b'SYNTHETIC OUTSIDE FILE'
    assert not store.db.execute('SELECT * FROM pending_audio_delete').fetchall()


@pytest.mark.skipif(os.name!='nt',reason='Windows reparse-point integration')
@pytest.mark.parametrize('whole_audio_root',[False,True])
def test_junction_escape_is_refused_and_external_file_survives(store,tmp_path,whole_audio_root):
    import _winapi
    external=tmp_path/'external';external.mkdir()
    protected=external/'protected.wav';protected.write_bytes(b'SYNTHETIC PROTECTED FILE')
    audio=tmp_path/'audio'
    if not whole_audio_root:audio.mkdir()
    junction=audio if whole_audio_root else audio/'linked'
    _winapi.CreateJunction(str(external),str(junction))
    try:
        escaped=junction/'protected.wav'
        store.add('escape','听写','raw','final',0,0,True,audio=str(escaped))
        assert store.delete([store.rows()[0]['id']])==1
        assert protected.read_bytes()==b'SYNTHETIC PROTECTED FILE'
        assert not store.rows() and store.cleanup_warning
    finally:junction.rmdir()  # Remove only the junction itself, never its target.


def test_prune_uses_same_durable_cleanup_path(store,monkeypatch):
    path,ident=add_audio(store,'old','2000-01-01T12:00:00')
    def deny(path):raise PermissionError('fixture private path')
    monkeypatch.setattr(store,'_unlink_audio',deny)
    assert store.prune()==1 and path.exists() and not store.rows()
    assert len(store.db.execute('SELECT * FROM pending_audio_delete').fetchall())==1
    assert 'fixture private' not in store.cleanup_warning


@pytest.mark.skipif(os.name!='nt',reason='Windows verified-handle race integration')
def test_reparse_swap_between_path_check_and_open_cannot_delete_outside_file(store,tmp_path,monkeypatch):
    import ctypes,_winapi
    folder=tmp_path/'audio'/'recorded';folder.mkdir(parents=True)
    original=folder/'fixture.wav';original.write_bytes(b'SYNTHETIC INSIDE FILE')
    external=tmp_path/'external';external.mkdir()
    protected=external/'fixture.wav';protected.write_bytes(b'SYNTHETIC OUTSIDE FILE')
    backup=tmp_path/'audio'/'recorded-backup'
    store.add('race','听写','raw','final',0,0,True,audio=str(original))
    loader=ctypes.WinDLL;api=loader('kernel32',use_last_error=True);swapped=[]

    class OpenProxy:
        def __setattr__(self,name,value):setattr(api.CreateFileW,name,value)
        def __call__(self,*args):
            if not swapped:
                # Both paths belong to this synthetic fixture. The swap occurs
                # after lstat/resolve checks, immediately before the real open.
                assert folder.resolve().is_relative_to(tmp_path.resolve())
                assert backup.resolve().is_relative_to(tmp_path.resolve())
                folder.rename(backup)
                _winapi.CreateJunction(str(external),str(folder));swapped.append(True)
            return api.CreateFileW(*args)

    class ApiProxy:
        CreateFileW=OpenProxy()
        def __getattr__(self,name):return getattr(api,name)

    monkeypatch.setattr(ctypes,'WinDLL',lambda name,**kw:ApiProxy() if name=='kernel32' else loader(name,**kw))
    try:
        assert store.delete([store.rows()[0]['id']])==1
        assert swapped and protected.read_bytes()==b'SYNTHETIC OUTSIDE FILE'
        assert (backup/'fixture.wav').read_bytes()==b'SYNTHETIC INSIDE FILE'
        assert not store.rows() and store.cleanup_warning
    finally:
        if swapped:
            folder.rmdir()
            assert backup.resolve().is_relative_to(tmp_path.resolve())
            assert folder.resolve().is_relative_to(tmp_path.resolve())
            backup.rename(folder)
    assert store.cleanup_audio()==0
    assert not original.exists() and protected.exists()


@pytest.mark.parametrize('operation',['add','delete','delete_all'])
def test_dictionary_db_is_canonical_after_json_failure_and_reopen(store,monkeypatch,operation):
    store.add_word('Fixture retained term');before_json=store.path.read_bytes()
    def deny():raise PermissionError('fixture private settings path')
    monkeypatch.setattr(store,'save',deny)
    if operation=='add':store.add_word('Fixture newly committed term')
    elif operation=='delete':store.delete_word('Fixture retained term')
    else:
        for word in store.words():store.delete_word(word['word'])
    expected={row['word'] for row in store.words()}
    assert store.dictionary_warning and 'fixture private' not in store.dictionary_warning
    assert store.path.read_bytes()==before_json
    assert set(store.config['hotwords'].splitlines())==expected
    store.db.close();reopened=Store(store.root)
    try:
        assert {row['word'] for row in reopened.words()}==expected
        assert set(reopened.config['hotwords'].splitlines())==expected
        assert reopened.path.read_bytes()==before_json  # Opening doesn't rewrite config.
    finally:reopened.db.close()


def test_legacy_hotwords_import_is_marked_once_without_config_rewrite(tmp_path):
    path=tmp_path/'settings.json'
    path.write_text(json.dumps({'hotwords':'Fixture legacy term'}),'utf-8')
    original=path.read_bytes()
    connection=sqlite3.connect(tmp_path/'history.db')
    connection.execute('CREATE TABLE dictionary(word TEXT PRIMARY KEY COLLATE NOCASE,source TEXT,created TEXT)')
    connection.execute("INSERT INTO dictionary VALUES('Fixture existing term','分析','2026-01-01')")
    connection.commit();connection.close()
    store=Store(tmp_path)
    try:
        assert {row['word'] for row in store.words()}=={'Fixture existing term','Fixture legacy term'}
        assert path.read_bytes()==original
        assert store.db.execute("SELECT value FROM store_metadata WHERE key='dictionary_canonical_v1'").fetchone()[0]=='1'
        with store.db:store.db.execute('DELETE FROM dictionary')
    finally:store.db.close()
    reopened=Store(tmp_path)
    try:assert not reopened.words() and reopened.config['hotwords']=='' and path.read_bytes()==original
    finally:reopened.db.close()

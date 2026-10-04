"""Runtime dependencies are authenticated before any existing DLL is replaced."""
import hashlib
import io
import json
import threading
import zipfile
from contextlib import contextmanager

import pytest

from murmur import native_runtime


def make_archive(entries):
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as archive:
        for name,data in entries:archive.writestr(name,data)
    return output.getvalue()


def fake_runtime(monkeypatch,*,entries=None,license_payload=None):
    expected={'llama.dll':b'first dll','ggml.dll':b'second dll'}
    license_data=b'upstream license'
    packed=make_archive(list((entries or expected).items()))
    monkeypatch.setattr(native_runtime,'DLL_FILES',{
        name:(len(data),hashlib.sha256(data).hexdigest()) for name,data in expected.items()})
    monkeypatch.setattr(native_runtime,'ARCHIVE_SIZE',len(packed))
    monkeypatch.setattr(native_runtime,'ARCHIVE_SHA256',hashlib.sha256(packed).hexdigest())
    monkeypatch.setattr(native_runtime,'LICENSE_SIZE',len(license_data))
    monkeypatch.setattr(native_runtime,'LICENSE_SHA256',hashlib.sha256(license_data).hexdigest())
    payloads={'archive':packed,'license':license_data if license_payload is None else license_payload}
    requested=[];hooks={}
    class Response:
        def __init__(self,data):self.content=data
        def raise_for_status(self):pass
        def iter_bytes(self,size):
            # Multiple chunks let cancellation be observed during a download.
            for start in range(0,len(self.content),64):yield self.content[start:start+64]
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        @contextmanager
        def stream(self,method,url):
            requested.append(url)
            assert url==native_runtime.ARCHIVE_URL
            yield Response(payloads['archive'])
        def get(self,url):
            requested.append(url)
            assert url==native_runtime.LICENSE_URL
            if hooks.get('license'):hooks['license']()
            return Response(payloads['license'])
    monkeypatch.setattr(native_runtime.httpx,'Client',Client)
    return payloads,requested,hooks


def assert_clean(folder):
    assert not list(folder.rglob('*.download'))
    assert not list(folder.glob('.murmur-runtime-install-*'))


def test_official_runtime_release_has_fixed_archive_dll_and_license_integrity():
    assert native_runtime.VERSION=='b10621'
    assert native_runtime.ARCHIVE_URL=='https://github.com/ggml-org/llama.cpp/releases/download/b10621/llama-b10621-bin-win-vulkan-x64.zip'
    assert native_runtime.ARCHIVE_SIZE==34403304
    assert native_runtime.ARCHIVE_SHA256=='2672d85bf87c8280d94dee01eb6a86280046878f70a07d786a93637fa9081163'
    assert native_runtime.LICENSE_SIZE==1078
    assert len(native_runtime.LICENSE_SHA256)==64
    assert 'llama.dll' in native_runtime.DLL_FILES
    assert 'ggml-vulkan.dll' in native_runtime.DLL_FILES
    assert all(not name.lower().endswith('.exe') for name in native_runtime.DLL_FILES)
    assert all(size>0 and len(sha)==64 for size,sha in native_runtime.DLL_FILES.values())


def test_verified_download_installs_only_allowlisted_libraries_and_license(tmp_path,monkeypatch):
    _,requested,_=fake_runtime(monkeypatch,entries={
        'llama.dll':b'first dll','ggml.dll':b'second dll',
        'llama-cli.exe':b'ignored executable','../outside.exe':b'ignored traversal'})
    progress=[]
    assert native_runtime.install_runtime(destination=tmp_path,progress=progress.append)==tmp_path
    assert requested==[native_runtime.ARCHIVE_URL,native_runtime.LICENSE_URL]
    assert (tmp_path/'llama.dll').read_bytes()==b'first dll'
    assert native_runtime.verify_runtime(tmp_path)
    assert not (tmp_path/'llama-cli.exe').exists()
    assert not (tmp_path.parent/'outside.exe').exists()
    manifest=json.loads((tmp_path/'murmur-runtime.json').read_text('utf-8'))
    assert manifest['archive_sha256']==native_runtime.ARCHIVE_SHA256
    assert set(manifest['files'])=={'llama.dll','ggml.dll'}
    assert progress[-1]=='Local decoder runtime installed and verified'
    assert_clean(tmp_path)


def test_verified_cache_skips_network_but_tampered_dll_triggers_reinstallation(tmp_path,monkeypatch):
    _,requested,_=fake_runtime(monkeypatch)
    native_runtime.install_runtime(destination=tmp_path)
    requested.clear()
    native_runtime.install_runtime(destination=tmp_path)
    assert requested==[]
    (tmp_path/'ggml.dll').write_bytes(b'corrupted!')
    assert not native_runtime.verify_runtime(tmp_path)
    native_runtime.install_runtime(destination=tmp_path)
    assert requested==[native_runtime.ARCHIVE_URL,native_runtime.LICENSE_URL]
    assert native_runtime.verify_runtime(tmp_path)
    assert_clean(tmp_path)


@pytest.mark.parametrize('corrupt',['hash','oversize','short'])
def test_unverified_archive_preserves_existing_files_and_cleans_download(tmp_path,monkeypatch,corrupt):
    payloads,requested,_=fake_runtime(monkeypatch)
    packed=payloads['archive']
    if corrupt=='hash':payloads['archive']=packed[:-1]+bytes([packed[-1]^1])
    elif corrupt=='oversize':payloads['archive']=packed+b'larger'
    else:payloads['archive']=packed[:-1]
    (tmp_path/'llama.dll').write_bytes(b'custom runtime')
    with pytest.raises(RuntimeError,match='integrity|expected size'):
        native_runtime.install_runtime(destination=tmp_path)
    assert (tmp_path/'llama.dll').read_bytes()==b'custom runtime'
    assert requested==[native_runtime.ARCHIVE_URL]
    assert not (tmp_path/'murmur-runtime.json').exists()
    assert_clean(tmp_path)


@pytest.mark.parametrize('entries',[
    {'llama.dll':b'first dll'},
    {'llama.dll':b'first dll','ggml.dll':b'wrong hash'},
])
def test_late_archive_member_failure_preserves_every_existing_dll(tmp_path,monkeypatch,entries):
    fake_runtime(monkeypatch,entries=entries)
    (tmp_path/'llama.dll').write_bytes(b'custom runtime')
    (tmp_path/'ggml.dll').write_bytes(b'custom backend')
    with pytest.raises(RuntimeError,match='incomplete|integrity'):
        native_runtime.install_runtime(destination=tmp_path)
    assert (tmp_path/'llama.dll').read_bytes()==b'custom runtime'
    assert (tmp_path/'ggml.dll').read_bytes()==b'custom backend'
    assert not (tmp_path/'LICENSE-llama.cpp.txt').exists()
    assert_clean(tmp_path)


def test_license_hash_failure_preserves_existing_dlls(tmp_path,monkeypatch):
    fake_runtime(monkeypatch,license_payload=b'corrupt license!')
    (tmp_path/'llama.dll').write_bytes(b'custom runtime')
    with pytest.raises(RuntimeError,match='license integrity'):
        native_runtime.install_runtime(destination=tmp_path)
    assert (tmp_path/'llama.dll').read_bytes()==b'custom runtime'
    assert not (tmp_path/'ggml.dll').exists()
    assert_clean(tmp_path)


def test_duplicate_archive_members_are_rejected_before_publishing(tmp_path,monkeypatch):
    payloads,_,_=fake_runtime(monkeypatch)
    with pytest.warns(UserWarning,match='Duplicate name'):
        payloads['archive']=make_archive([('llama.dll',b'first dll'),('llama.dll',b'first dll'),('ggml.dll',b'second dll')])
    monkeypatch.setattr(native_runtime,'ARCHIVE_SIZE',len(payloads['archive']))
    monkeypatch.setattr(native_runtime,'ARCHIVE_SHA256',hashlib.sha256(payloads['archive']).hexdigest())
    (tmp_path/'llama.dll').write_bytes(b'custom runtime')
    with pytest.raises(RuntimeError,match='Duplicate files'):
        native_runtime.install_runtime(destination=tmp_path)
    assert (tmp_path/'llama.dll').read_bytes()==b'custom runtime'
    assert_clean(tmp_path)


def test_cancel_during_download_cleans_partials_and_releases_install_lock(tmp_path,monkeypatch):
    fake_runtime(monkeypatch)
    cancel=threading.Event()
    (tmp_path/'llama.dll').write_bytes(b'custom runtime')
    with pytest.raises(InterruptedError):
        native_runtime.install_runtime(destination=tmp_path,cancel=cancel,progress=lambda text:cancel.set())
    assert (tmp_path/'llama.dll').read_bytes()==b'custom runtime'
    assert_clean(tmp_path)
    cancel.clear();native_runtime.install_runtime(destination=tmp_path,cancel=cancel)
    assert native_runtime.verify_runtime(tmp_path)


def test_cancel_after_license_download_does_not_publish_staged_dlls(tmp_path,monkeypatch):
    _,_,hooks=fake_runtime(monkeypatch)
    cancel=threading.Event();hooks['license']=cancel.set
    (tmp_path/'llama.dll').write_bytes(b'custom runtime')
    with pytest.raises(InterruptedError):native_runtime.install_runtime(destination=tmp_path,cancel=cancel)
    assert (tmp_path/'llama.dll').read_bytes()==b'custom runtime'
    assert not (tmp_path/'ggml.dll').exists()
    assert_clean(tmp_path)


def test_pre_cancelled_install_performs_no_network_io(tmp_path,monkeypatch):
    _,requested,_=fake_runtime(monkeypatch)
    cancel=threading.Event();cancel.set()
    with pytest.raises(InterruptedError):native_runtime.install_runtime(destination=tmp_path,cancel=cancel)
    assert requested==[]
    assert_clean(tmp_path)


def test_explicit_local_archive_is_verified_and_preserved(tmp_path,monkeypatch):
    payloads,requested,_=fake_runtime(monkeypatch)
    source=tmp_path/'provided.zip';source.write_bytes(payloads['archive'])
    destination=tmp_path/'runtime'
    native_runtime.install_runtime(destination=destination,archive=source)
    assert source.read_bytes()==payloads['archive']
    assert requested==[native_runtime.LICENSE_URL]
    assert native_runtime.verify_runtime(destination)
    assert_clean(destination)


def test_bad_explicit_local_archive_does_not_get_deleted(tmp_path,monkeypatch):
    _,requested,_=fake_runtime(monkeypatch)
    source=tmp_path/'provided.zip';source.write_bytes(b'bad archive')
    destination=tmp_path/'runtime';destination.mkdir()
    (destination/'llama.dll').write_bytes(b'custom runtime')
    with pytest.raises(RuntimeError,match='runtime integrity'):
        native_runtime.install_runtime(destination=destination,archive=source)
    assert source.read_bytes()==b'bad archive'
    assert (destination/'llama.dll').read_bytes()==b'custom runtime'
    assert requested==[]
    assert_clean(destination)

import hashlib
import json
import threading
from contextlib import contextmanager

import pytest

from murmur import models


def fake_download(monkeypatch, payload, expected):
    monkeypatch.setattr(models, 'FILES', {'model.int8.onnx': (len(expected), hashlib.sha256(expected).hexdigest())})
    class Response:
        def raise_for_status(self): pass
        def iter_bytes(self, size): yield payload
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        @contextmanager
        def stream(self, *args): yield Response()
    monkeypatch.setattr(models.httpx, 'Client', Client)


def test_model_hash_failure_preserves_existing_and_removes_partial(tmp_path, monkeypatch):
    path=tmp_path/'model.int8.onnx';path.write_bytes(b'custom model')
    fake_download(monkeypatch, b'corrupted', b'verified!')
    with pytest.raises(RuntimeError, match='integrity'):
        models.install_sensevoice(tmp_path)
    assert path.read_bytes()==b'custom model'
    assert not list(tmp_path.glob('*.download'))
    assert not (tmp_path/'murmur-model.json').exists()


def test_verified_model_retains_replaced_custom_file(tmp_path, monkeypatch):
    path=tmp_path/'model.int8.onnx';path.write_bytes(b'custom model')
    fake_download(monkeypatch, b'verified', b'verified')
    models.install_sensevoice(tmp_path)
    assert path.read_bytes()==b'verified'
    assert [p.read_bytes() for p in tmp_path.glob('*.previous-*')]==[b'custom model']
    assert (tmp_path/'murmur-model.json').exists()


def test_model_cancel_preserves_existing_and_releases_download_slot(tmp_path, monkeypatch):
    fake_download(monkeypatch, b'verified', b'verified')
    cancel=threading.Event();cancel.set()
    with pytest.raises(InterruptedError):models.install_sensevoice(tmp_path, cancel=cancel)
    assert not list(tmp_path.glob('*.download'))
    cancel.clear();models.install_sensevoice(tmp_path, cancel=cancel)
    assert (tmp_path/'model.int8.onnx').read_bytes()==b'verified'


def fake_paraformer_download(monkeypatch, payload):
    spec={**models.MODELS['paraformer'],
          'base':'https://model.test/pinned/', 'sources':{},
          'files':{name:(len(data),hashlib.sha256(data).hexdigest())
                   for name,data in payload.items()}}
    monkeypatch.setitem(models.MODELS,'paraformer',spec)
    requested=[]
    class Response:
        def __init__(self,data):self.data=data
        def raise_for_status(self):pass
        def iter_bytes(self,size):yield self.data
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        @contextmanager
        def stream(self,method,url):
            requested.append(url)
            yield Response(payload[url.rsplit('/',1)[-1]])
    monkeypatch.setattr(models.httpx,'Client',Client)
    return requested


def test_selected_model_download_uses_pinned_sources_and_records_engine(tmp_path,monkeypatch):
    payload={'model.int8.onnx':b'paraformer','tokens.txt':b'tokens'}
    requested=fake_paraformer_download(monkeypatch,payload)
    progress=[]
    folder=models.install_model('paraformer',tmp_path,progress.append)
    assert folder==tmp_path
    assert requested==['https://model.test/pinned/model.int8.onnx',
                       'https://model.test/pinned/tokens.txt']
    assert all((tmp_path/name).read_bytes()==data for name,data in payload.items())
    manifest=json.loads((tmp_path/'murmur-model.json').read_text('utf-8'))
    assert manifest['engine']=='paraformer'
    assert manifest['revision']==models.PARAFORMER_REVISION
    assert any('Paraformer' in message for message in progress)
    assert 'does not restore punctuation' in (tmp_path/'NOTICE.txt').read_text('utf-8')


def test_verified_paraformer_files_are_reused_without_download(tmp_path,monkeypatch):
    payload={'model.int8.onnx':b'paraformer','tokens.txt':b'tokens'}
    requested=fake_paraformer_download(monkeypatch,payload)
    models.install_model('paraformer',tmp_path)
    requested.clear()
    models.install_model('paraformer',tmp_path)
    assert requested==[]
    assert not list(tmp_path.glob('*.previous-*'))


def test_paraformer_failure_preserves_custom_file(tmp_path,monkeypatch):
    path=tmp_path/'model.int8.onnx';path.write_bytes(b'custom')
    payload={'model.int8.onnx':b'corrupted'}
    fake_paraformer_download(monkeypatch,payload)
    # A file with the right byte count but wrong SHA must never replace a model.
    models.MODELS['paraformer']['files']['model.int8.onnx']=(len(b'corrupted'),hashlib.sha256(b'verified!').hexdigest())
    with pytest.raises(RuntimeError,match='integrity'):
        models.install_model('paraformer',tmp_path)
    assert path.read_bytes()==b'custom'
    assert not list(tmp_path.glob('*.download'))

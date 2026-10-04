"""Authenticated model archives must never overwrite a working model on failure."""
import hashlib
import io
import json
import threading
import zipfile
from contextlib import contextmanager

import pytest

from murmur import models, native_runtime


def archive_bytes(files):
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as archive:
        for name,data in files.items():
            entry=zipfile.ZipInfo(name);entry.filename=name
            archive.writestr(entry,data)
    return buffer.getvalue()


def mock_archive_model(monkeypatch,archive_files=None,*,extra=None):
    archive_files=archive_files or {'nested/encoder.onnx':b'encoder','nested/decoder.gguf':b'decoder'}
    packed=archive_bytes(archive_files)
    members={'encoder.onnx':len(b'encoder'),'decoder.gguf':len(b'decoder')}
    files={name:(len(data),hashlib.sha256(data).hexdigest()) for name,data in (extra or {}).items()}
    spec={**models.MODELS['fun_asr_nano'],'base':'https://models.test/fixed/','revision':'pinned-archive',
          'archive':{'name':'model.zip','size':len(packed),'sha256':hashlib.sha256(packed).hexdigest(),
                     'members':members},'files':files,'sources':{}}
    monkeypatch.setitem(models.MODELS,'fun_asr_nano',spec)
    responses={'model.zip':packed,**(extra or {})};requested=[];runtime_calls=[]
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
            yield Response(responses[url.removeprefix('https://models.test/fixed/')])
    monkeypatch.setattr(models.httpx,'Client',Client)
    monkeypatch.setattr(native_runtime,'install_runtime',lambda **kwargs:runtime_calls.append(kwargs))
    return responses,requested,runtime_calls


def test_catalog_includes_all_four_engines_and_keeps_original_cpu_default():
    assert set(models.MODELS)=={'sensevoice','paraformer','fun_asr_nano','qwen_asr'}
    assert models.model_spec('sensevoice')['kind']=='sherpa'
    assert models.model_spec('sensevoice')['files'] is models.FILES
    assert models.model_spec('sensevoice','gpu')['kind']=='split_onnx'
    assert models.model_spec('sensevoice','gpu')['folder']=='sensevoice-small-dml'
    for engine in ('fun_asr_nano','qwen_asr'):
        spec=models.model_spec(engine)
        assert spec['kind']=='gguf'
        assert len(spec['archive']['sha256'])==64
        assert spec['revision']==spec['archive']['sha256']
        assert all(set(group)&set(spec['archive']['members']) for group in spec['required_files'])
        assert models.download_size(engine)>spec['archive']['size']


def test_paraformer_cannot_select_gpu_and_unknown_models_fail_clearly():
    with pytest.raises(RuntimeError,match='CPU inference only'):models.model_spec('paraformer','gpu')
    with pytest.raises(RuntimeError,match='supported local model'):models.model_spec('unknown')
    with pytest.raises(RuntimeError,match='CPU or GPU'):models.model_spec('sensevoice','cuda')


def test_archive_install_flattens_allowlisted_members_and_records_authenticated_files(tmp_path,monkeypatch):
    _,requested,runtime_calls=mock_archive_model(monkeypatch,extra={'licenses/model.txt':b'license'})
    model_file=tmp_path/'encoder.onnx';model_file.write_bytes(b'custom')
    models.install_model('fun_asr_nano',tmp_path)
    assert requested==['https://models.test/fixed/model.zip','https://models.test/fixed/licenses/model.txt']
    assert model_file.read_bytes()==b'encoder'
    assert (tmp_path/'decoder.gguf').read_bytes()==b'decoder'
    assert (tmp_path/'licenses/model.txt').read_bytes()==b'license'
    assert [p.read_bytes() for p in tmp_path.glob('encoder.onnx.previous-*')]==[b'custom']
    manifest=json.loads((tmp_path/'murmur-model.json').read_text('utf-8'))
    assert manifest['files']['decoder.gguf']==[len(b'decoder'),hashlib.sha256(b'decoder').hexdigest()]
    assert manifest['engine']=='fun_asr_nano'
    assert runtime_calls and isinstance(runtime_calls[0]['cancel'],threading.Event)
    assert not list(tmp_path.glob('.murmur-install-*'))


def test_installed_archive_is_reused_only_while_recorded_hashes_match(tmp_path,monkeypatch):
    _,requested,_=mock_archive_model(monkeypatch)
    models.install_model('fun_asr_nano',tmp_path)
    requested.clear()
    models.install_model('fun_asr_nano',tmp_path)
    assert requested==[]
    models.install_model('fun_asr_nano',tmp_path,acceleration='gpu')
    assert requested==[]
    (tmp_path/'decoder.gguf').write_bytes(b'changed')
    models.install_model('fun_asr_nano',tmp_path)
    assert requested==['https://models.test/fixed/model.zip']
    assert (tmp_path/'decoder.gguf').read_bytes()==b'decoder'


def test_file_hash_metadata_is_checked_without_rehashing_models(tmp_path,monkeypatch):
    mock_archive_model(monkeypatch)
    assert models.installed_file_hashes(tmp_path,'fun_asr_nano')=={}
    models.install_model('fun_asr_nano',tmp_path)
    monkeypatch.setattr(models,'_matches',lambda *args:pytest.fail('Metadata lookup must not rehash model files'))
    expected=models.installed_file_hashes(tmp_path,'fun_asr_nano','gpu')
    assert expected['encoder.onnx']==(len(b'encoder'),hashlib.sha256(b'encoder').hexdigest())
    manifest=json.loads((tmp_path/'murmur-model.json').read_text('utf-8'))
    manifest['files']['encoder.onnx'][1]='untrusted-sha'
    (tmp_path/'murmur-model.json').write_text(json.dumps(manifest),'utf-8')
    assert models.installed_file_hashes(tmp_path,'fun_asr_nano')=={}


def test_archive_hash_metadata_requires_matching_revision_and_exact_member_size(tmp_path,monkeypatch):
    mock_archive_model(monkeypatch);models.install_model('fun_asr_nano',tmp_path)
    path=tmp_path/'murmur-model.json';manifest=json.loads(path.read_text('utf-8'))
    manifest['revision']='old-archive';path.write_text(json.dumps(manifest),'utf-8')
    assert models.installed_file_hashes(tmp_path,'fun_asr_nano')=={}
    manifest['revision']='pinned-archive';manifest['files']['encoder.onnx'][0]+=1
    path.write_text(json.dumps(manifest),'utf-8')
    assert models.installed_file_hashes(tmp_path,'fun_asr_nano')=={}


def test_archive_hash_failure_preserves_working_model(tmp_path,monkeypatch):
    responses,_,runtime_calls=mock_archive_model(monkeypatch)
    responses['model.zip']=responses['model.zip'].replace(b'encoder',b'corrupt',1)
    (tmp_path/'encoder.onnx').write_bytes(b'custom')
    with pytest.raises(RuntimeError,match='integrity'):models.install_model('fun_asr_nano',tmp_path)
    assert (tmp_path/'encoder.onnx').read_bytes()==b'custom'
    assert not runtime_calls
    assert not (tmp_path/'murmur-model.json').exists()
    assert not list(tmp_path.glob('.murmur-install-*'))


@pytest.mark.parametrize('archive_files',[
    {'../encoder.onnx':b'encoder','decoder.gguf':b'decoder'},
    {'C:/encoder.onnx':b'encoder','decoder.gguf':b'decoder'},
    {'a\\encoder.onnx':b'encoder','decoder.gguf':b'decoder'},
    {'a/encoder.onnx':b'encoder','b/encoder.onnx':b'encoder','decoder.gguf':b'decoder'},
    {'encoder.onnx':b'encoder','decoder.gguf':b'decoder','unexpected.exe':b'no'},
    {'encoder.onnx':b'encoder'},
])
def test_archive_rejects_traversal_duplicates_unlisted_or_missing_members(tmp_path,monkeypatch,archive_files):
    mock_archive_model(monkeypatch,archive_files)
    (tmp_path/'encoder.onnx').write_bytes(b'custom')
    with pytest.raises(RuntimeError):models.install_model('fun_asr_nano',tmp_path)
    assert (tmp_path/'encoder.onnx').read_bytes()==b'custom'
    assert not (tmp_path/'decoder.gguf').exists()
    assert not list(tmp_path.glob('.murmur-install-*'))


def test_late_auxiliary_failure_does_not_publish_any_archive_files(tmp_path,monkeypatch):
    responses,_,_=mock_archive_model(monkeypatch,extra={'LICENSE':b'license'})
    responses['LICENSE']=b'corrupt'
    (tmp_path/'encoder.onnx').write_bytes(b'custom')
    with pytest.raises(RuntimeError,match='integrity'):models.install_model('fun_asr_nano',tmp_path)
    assert (tmp_path/'encoder.onnx').read_bytes()==b'custom'
    assert not (tmp_path/'decoder.gguf').exists()
    assert not list(tmp_path.glob('*.previous-*'))


def test_cancelled_archive_download_never_opens_network_connection(tmp_path,monkeypatch):
    _,requested,_=mock_archive_model(monkeypatch)
    cancel=threading.Event();cancel.set()
    with pytest.raises(InterruptedError):models.install_model('fun_asr_nano',tmp_path,cancel=cancel)
    assert requested==[]
    assert not list(tmp_path.glob('.murmur-install-*'))

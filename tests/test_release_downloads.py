"""Parallel release ranges preserve offsets and retain full-file authentication."""
import hashlib
import re
import threading
from collections import Counter
from contextlib import contextmanager
from urllib.parse import parse_qs,urlsplit

import httpx
import pytest

from murmur import models

MIB=1024*1024
RELEASE_URL='https://github.com/example/models/releases/download/fixed/model.onnx'


def range_bytes(start,end):
    return bytes([(start//MIB)%251])*(end-start+1)


def range_digest(size):
    digest=hashlib.sha256()
    for start in range(0,size,MIB):digest.update(range_bytes(start,min(size,start+MIB)-1))
    return digest.hexdigest()


class RangeClient:
    """Thread-safe deterministic stub; never opens a network connection."""
    def __init__(self,size,*,invalid=None,failures=0,failure_stage='open',out_of_order=False,
                 final_url=None,probe_invalid=None):
        self.size=size;self.invalid=invalid;self.failures=failures
        self.failure_stage=failure_stage;self.out_of_order=out_of_order
        self.requests=[];self.probe_requests=[];self.attempts=Counter();self.completed=[]
        self.final_url=final_url;self.probe_invalid=probe_invalid
        self.active=0;self.max_active=0;self.lock=threading.Lock()
        self.later_finished=threading.Event();self.small_body=b'verified'

    def __enter__(self):return self
    def __exit__(self,*args):pass

    @contextmanager
    def stream(self,method,url,headers=None,timeout=None):
        assert method=='GET'
        if not headers:
            yield SimpleResponse(self.small_body)
            return
        match=re.fullmatch(r'bytes=(\d+)-(\d+)',headers['Range'])
        assert match
        start,end=map(int,match.groups())
        assert 0<=start<=end<self.size
        if parse_qs(urlsplit(url).query).get('murmur_probe')==['1']:
            self.probe_requests.append(url)
            assert start==end==0
            probe=RangeResponse(self,start,end,False)
            probe.status_code=206;probe.headers={'Content-Range':f'bytes 0-0/{self.size}'}
            probe.url=self.final_url or url
            if self.probe_invalid=='status':probe.status_code=200
            elif self.probe_invalid=='range':probe.headers['Content-Range']=f'bytes 0-1/{self.size}'
            probe.probe=True
            yield probe
            return
        with self.lock:
            self.requests.append((url,start,end,timeout));self.attempts[start]+=1
            attempt=self.attempts[start];self.active+=1
            self.max_active=max(self.max_active,self.active)
        fails=start==0 and attempt<=self.failures
        try:
            if fails and self.failure_stage=='open':raise httpx.ConnectError('Fixture connection failed')
            yield RangeResponse(self,start,end,fails)
        finally:
            with self.lock:self.active-=1


class SimpleResponse:
    def __init__(self,data):self.data=data
    def raise_for_status(self):pass
    def iter_bytes(self,size):yield self.data


class RangeResponse:
    def __init__(self,client,start,end,fails):
        self.client=client;self.start=start;self.end=end;self.fails=fails
        self.probe=False
        self.status_code=200 if client.invalid=='status' else 206
        value=f'bytes {start}-{end}/{client.size}'
        if client.invalid=='offset':value=f'bytes {start+1}-{end}/{client.size}'
        elif client.invalid=='total':value=f'bytes {start}-{end}/{client.size+1}'
        elif client.invalid=='missing':value=None
        self.headers={} if value is None else {'Content-Range':value}

    def raise_for_status(self):pass

    def iter_bytes(self,chunk_size):
        if self.probe:
            yield b'' if self.client.probe_invalid=='short' else b'XX' if self.client.probe_invalid=='oversize' else b'X'
            return
        if self.client.out_of_order and self.start==0:
            assert self.client.later_finished.wait(2),'Another submitted range never completed'
        data=range_bytes(self.start,self.end)
        if self.client.invalid=='oversize':data+=b'extra'
        elif self.client.invalid=='short':data=data[:-1]
        if self.fails and self.client.failure_stage=='body':
            yield data[:chunk_size]
            raise httpx.ReadError('Fixture connection dropped after a partial body')
        for offset in range(0,len(data),chunk_size):yield data[offset:offset+chunk_size]
        with self.client.lock:self.client.completed.append(self.start)
        if self.start:self.client.later_finished.set()


def no_range_threads_left():
    assert not [thread for thread in threading.enumerate() if thread.name.startswith('MurMur-model-part')]


def test_out_of_order_ranges_are_assembled_at_correct_offsets_with_bounded_workers():
    size=8*MIB+17;client=RangeClient(size,out_of_order=True)
    chunks=list(models._release_chunks(client,RELEASE_URL,size,threading.Event()))
    expected=[range_bytes(start,min(size,start+MIB)-1) for start in range(0,size,MIB)]
    assert chunks==expected
    assert client.completed[0]!=0  # A later range demonstrably finished first.
    assert sorted(start for url,start,end,timeout in client.requests)==list(range(0,size,MIB))
    assert 2<=client.max_active<=6 and client.active==0
    assert len(chunks[-1])==17
    no_range_threads_left()


def test_each_range_has_distinct_cache_query_and_preserves_existing_query():
    size=2*MIB+9;client=RangeClient(size)
    list(models._release_chunks(client,RELEASE_URL+'?token=keep',size,threading.Event()))
    targets=[url for url,start,end,timeout in client.requests]
    assert len(set(targets))==3
    for url,start,end,timeout in client.requests:
        query=parse_qs(urlsplit(url).query)
        assert query=={'token':['keep'],'murmur_range':[str(start)]}
        assert timeout.read==15 and timeout.connect==15
        assert end==min(size,start+MIB)-1
    no_range_threads_left()


def test_official_asset_redirect_is_resolved_once_and_reused_for_all_ranges():
    size=2*MIB+9
    signed='https://release-assets.githubusercontent.com/fixed/archive?sig=private&expiry=fixed'
    client=RangeClient(size,final_url=signed)
    chunks=list(models._release_chunks(client,RELEASE_URL,size,threading.Event()))
    assert len(chunks)==3 and len(client.probe_requests)==1
    assert urlsplit(client.probe_requests[0]).hostname=='github.com'
    for url,start,end,timeout in client.requests:
        assert urlsplit(url).hostname=='release-assets.githubusercontent.com'
        assert parse_qs(urlsplit(url).query)=={'sig':['private'],'expiry':['fixed'],'murmur_range':[str(start)]}
    no_range_threads_left()


@pytest.mark.parametrize('final_url',[
    'http://release-assets.githubusercontent.com/archive',
    'https://untrusted.example/archive',
    'https://release-assets.githubusercontent.com.untrusted.example/archive',
    'https://user:password@release-assets.githubusercontent.com/archive',
    'https://release-assets.githubusercontent.com:444/archive',
])
def test_unexpected_redirect_origin_is_rejected_before_starting_range_workers(final_url):
    client=RangeClient(MIB,final_url=final_url)
    with pytest.raises(RuntimeError,match='unexpected download host'):
        list(models._release_chunks(client,RELEASE_URL,MIB,threading.Event()))
    assert len(client.probe_requests)==1 and client.requests==[]
    no_range_threads_left()


@pytest.mark.parametrize('invalid,message',[
    ('status','unexpected download range'),('range','unexpected download range'),
    ('short','incomplete'),('oversize','exceeded its expected size'),
])
def test_redirect_probe_itself_requires_exact_single_byte_range(invalid,message):
    client=RangeClient(MIB,probe_invalid=invalid)
    with pytest.raises(RuntimeError,match=message):
        list(models._release_chunks(client,RELEASE_URL,MIB,threading.Event()))
    assert client.requests==[]
    no_range_threads_left()


def test_http_failures_do_not_expose_temporary_signed_url(monkeypatch):
    signed='https://release-assets.githubusercontent.com/archive?sig=private-signature'
    client=RangeClient(MIB,final_url=signed)
    def reject(self):
        if self.probe:return
        request=httpx.Request('GET',signed)
        response=httpx.Response(403,request=request)
        response.raise_for_status()
    monkeypatch.setattr(RangeResponse,'raise_for_status',reject)
    with pytest.raises(RuntimeError,match='server rejected') as error:
        list(models._release_chunks(client,RELEASE_URL,MIB,threading.Event()))
    assert 'private-signature' not in str(error.value)
    assert 'release-assets' not in str(error.value)
    no_range_threads_left()


@pytest.mark.parametrize('invalid,message',[
    ('status','unexpected download range'),('offset','unexpected download range'),
    ('total','unexpected download range'),('missing','unexpected download range'),
    ('oversize','exceeded its expected size'),('short','incomplete'),
])
def test_wrong_range_status_headers_and_lengths_are_rejected(invalid,message):
    size=MIB+17;client=RangeClient(size,invalid=invalid)
    with pytest.raises(RuntimeError,match=message):
        list(models._release_chunks(client,RELEASE_URL,size,threading.Event()))
    assert client.attempts[0]==1  # Invalid data must not be treated as a transient transport error.
    assert client.active==0
    no_range_threads_left()


@pytest.mark.parametrize('failure_stage',['open','body'])
def test_transient_transport_errors_retry_same_range_without_duplicating_partial_data(failure_stage):
    size=MIB+17;client=RangeClient(size,failures=2,failure_stage=failure_stage)
    chunks=list(models._release_chunks(client,RELEASE_URL,size,threading.Event()))
    assert chunks==[range_bytes(0,MIB-1),range_bytes(MIB,size-1)]
    assert client.attempts[0]==3 and client.attempts[MIB]==1
    assert client.active==0
    no_range_threads_left()


def test_exhausted_transport_retries_propagate_and_close_every_worker():
    size=MIB+1;client=RangeClient(size,failures=10)
    with pytest.raises(RuntimeError,match='could not finish a download range'):
        list(models._release_chunks(client,RELEASE_URL,size,threading.Event()))
    assert client.attempts[0]==3 and client.active==0
    no_range_threads_left()


def test_pre_cancelled_parallel_download_never_requests_any_range():
    size=MIB;client=RangeClient(size);cancel=threading.Event();cancel.set()
    with pytest.raises(InterruptedError):list(models._release_chunks(client,RELEASE_URL,size,cancel))
    assert client.requests==[] and client.active==0
    no_range_threads_left()


def test_closing_range_generator_joins_outstanding_workers():
    size=8*MIB+17;client=RangeClient(size)
    chunks=models._release_chunks(client,RELEASE_URL,size,threading.Event())
    assert next(chunks)==range_bytes(0,MIB-1)
    chunks.close()
    assert client.active==0
    no_range_threads_left()


def test_large_release_download_still_checks_complete_sha_before_replacing(tmp_path):
    # Synthetic bytes just over the routing threshold exercise the real range
    # branch without any model weights or network access.
    size=64*MIB+1;client=RangeClient(size)
    path=tmp_path/'model.onnx';path.write_bytes(b'working model')
    with pytest.raises(RuntimeError,match='integrity'):
        models._download(client,RELEASE_URL,path,size,'0'*64,threading.Event(),
                         lambda text:None,{'name':'Fixture'},0,size)
    assert path.read_bytes()==b'working model'
    assert not (tmp_path/'model.onnx.download').exists()
    assert len(client.requests)==65
    models._download(client,RELEASE_URL,path,size,range_digest(size),threading.Event(),
                     lambda text:None,{'name':'Fixture'},0,size)
    assert path.stat().st_size==size
    with path.open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==range_digest(size)
    assert not (tmp_path/'model.onnx.download').exists()
    no_range_threads_left()


def test_cancelled_release_install_cleans_partial_files_and_releases_install_lock(tmp_path,monkeypatch):
    size=64*MIB+1;client=RangeClient(size);cancel=threading.Event()
    spec={**models.MODELS['paraformer'],'base':RELEASE_URL.rsplit('/',1)[0]+'/',
          'sources':{},'files':{'model.onnx':(size,range_digest(size))}}
    monkeypatch.setitem(models.MODELS,'paraformer',spec)
    monkeypatch.setattr(models.httpx,'Client',lambda **kwargs:client)
    path=tmp_path/'model.onnx';path.write_bytes(b'working model')
    with pytest.raises(InterruptedError):
        models.install_model('paraformer',tmp_path,progress=lambda text:cancel.set(),cancel=cancel)
    assert path.read_bytes()==b'working model'
    assert not list(tmp_path.rglob('*.download'))
    assert not list(tmp_path.glob('.murmur-install-*'))
    assert not (tmp_path/'murmur-model.json').exists()
    assert models._INSTALL_LOCK.acquire(blocking=False),'The cancelled model install retained its lock'
    models._INSTALL_LOCK.release()
    no_range_threads_left()
    # A small valid retry proves a later installation can complete normally.
    cancel.clear();spec['files']={'model.onnx':(len(client.small_body),hashlib.sha256(client.small_body).hexdigest())}
    models.install_model('paraformer',tmp_path,cancel=cancel)
    assert path.read_bytes()==client.small_body

"""HTTP speech fixtures never open a microphone, Vault or network."""
import io
import struct
import threading
import wave
from types import SimpleNamespace

import httpx
import pytest

from murmur import cloud_asr as api


@pytest.fixture
def cfg():
    return dict(asr_backend='openai',asr_http_url='https://fixture.invalid/v1',
                asr_http_model='gpt-transcribe',asr_http_language='auto',asr_http_timeout=5)


@pytest.fixture
def transport(monkeypatch):
    original=httpx.Client
    requests=[]
    def install(handler):
        def wrapped(request):
            requests.append(request)
            return handler(request)
        monkeypatch.setattr(api.httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(wrapped),**kwargs))
        return requests
    return install


def audio():
    return api.pcm_wav(struct.pack('<h',1000)*1600)


@pytest.mark.parametrize('backend,model,field',[('openai','gpt-transcribe','languages[]'),('openai','whisper-1','language'),('groq','whisper-large-v3-turbo','language')])
def test_original_language_transcription_payload(cfg,transport,backend,model,field):
    requests=transport(lambda request:httpx.Response(200,json={'text':'中文 and English.','languages':['zh','en']}))
    cfg.update(asr_backend=backend,asr_http_model=model,asr_http_language='zh')
    assert api.transcribe_wav(audio(),cfg,'synthetic-key')=='中文 and English.'
    request=requests[0]
    assert str(request.url)=='https://fixture.invalid/v1/audio/transcriptions'
    assert b'name="'+field.encode()+b'"' in request.content
    if field=='languages[]':assert b'name="language"' not in request.content
    assert b'name="model"' in request.content and model.encode() in request.content
    assert b'RIFF' in request.content and b'audio/wav' in request.content
    assert b'name="response_format"' in request.content and b'json' in request.content
    assert 'translations' not in str(request.url)


def test_auto_language_does_not_force_english(cfg,transport):
    requests=transport(lambda request:httpx.Response(200,json={'text':'中文'}))
    assert api.transcribe_wav(audio(),cfg,'key')=='中文'
    assert b'name="language' not in requests[0].content


@pytest.mark.parametrize('backend,model,field',[('openai','gpt-transcribe','keywords[]'),('openai','gpt-4o-mini-transcribe','prompt'),('groq','whisper-large-v3-turbo','prompt')])
def test_supported_hotwords_are_in_actual_multipart(cfg,transport,backend,model,field):
    cfg.update(asr_backend=backend,asr_http_model=model,hotwords='MurMur\n百炼\nMurMur\n<bad>\nunsafe\rinside\n'+('界'*100))
    requests=transport(lambda request:httpx.Response(200,json={'text':'MurMur 百炼'}))
    api.transcribe_wav(audio(),cfg,'key')
    body=requests[0].content
    assert b'name="'+field.encode()+b'"' in body
    assert b'MurMur' in body and '百炼'.encode() in body
    assert b'<bad>' not in body and b'unsafe' not in body
    assert body.count(b'MurMur')==1
    assert b'name="language' not in body
    if field=='keywords[]':assert body.count(b'name="keywords[]"')==2 and b'name="prompt"' not in body


@pytest.mark.parametrize('backend,model',[('http_asr','gpt-transcribe'),('openai','unknown-custom'),('groq','unknown-custom')])
def test_unknown_capabilities_do_not_guess_context(cfg,transport,backend,model):
    cfg.update(asr_backend=backend,asr_http_model=model,hotwords='must-not-send')
    requests=transport(lambda request:httpx.Response(200,json={'text':'text'}))
    api.transcribe_wav(audio(),cfg,'key')
    assert b'must-not-send' not in requests[0].content
    assert b'name="prompt"' not in requests[0].content and b'name="keywords[]"' not in requests[0].content


def test_prompt_byte_cap_preserves_whole_terms(cfg):
    cfg.update(asr_backend='groq',asr_http_model='whisper-large-v3',hotwords='\n'.join('词汇'+str(i) for i in range(100)))
    prompt=api.recognition_context(cfg)['prompt']
    assert len(prompt.encode())<=200
    assert all(term in cfg['hotwords'].split('\n') for term in prompt.split(', '))


def test_keyword_count_and_byte_cap(cfg):
    cfg['hotwords']='\n'.join('term-'+str(i) for i in range(100))
    terms=api.recognition_context(cfg)['keywords[]']
    assert len(terms)<=32 and sum(len(term.encode()) for term in terms)<=1000


def test_compressed_response_is_rejected_before_decoding(cfg,transport):
    import gzip
    transport(lambda request:httpx.Response(200,content=gzip.compress(b'{"text":"result"}'),headers={'Content-Encoding':'gzip'}))
    with pytest.raises(api.CloudAsrError,match='Compressed'):api.transcribe_wav(audio(),cfg,'key')


@pytest.mark.parametrize('status',[301,302,307,401,403,429,500])
def test_statuses_do_not_leak_response_or_follow_redirects(cfg,transport,status):
    requests=transport(lambda request:httpx.Response(status,headers={'Location':'https://untrusted.invalid'},text='private-key private-text'))
    with pytest.raises(api.CloudAsrError) as failure:api.transcribe_wav(audio(),cfg,'private-key')
    assert len(requests)==1
    assert 'private' not in str(failure.value) and 'untrusted' not in str(failure.value)


@pytest.mark.parametrize('body',[b'[]',b'not JSON',b'{"text":""}',b'{"text":null}',b'{"text":123}'])
def test_empty_or_malformed_result_is_not_accepted(cfg,transport,body):
    transport(lambda request:httpx.Response(200,content=body))
    with pytest.raises(api.CloudAsrError):api.transcribe_wav(audio(),cfg,'key')


@pytest.mark.parametrize('declared',[False,True])
def test_response_limit_without_trusting_content_length(cfg,transport,monkeypatch,declared):
    monkeypatch.setattr(api,'MAX_RESPONSE_BYTES',40)
    transport(lambda request:httpx.Response(200,content=b' '*41,headers={'Content-Length':'41'} if declared else {}))
    with pytest.raises(api.CloudAsrError,match='size limit'):api.transcribe_wav(audio(),cfg,'key')


def test_timeout_safe_message(cfg,transport):
    def timeout(request):raise httpx.ReadTimeout('private-url-and-key')
    transport(timeout)
    with pytest.raises(api.CloudAsrError,match='before the timeout'):api.transcribe_wav(audio(),cfg,'key')


def test_late_cancelled_response_cannot_escape(cfg,transport):
    cancel=threading.Event()
    def late(request):
        cancel.set()
        return httpx.Response(200,json={'text':'late result'})
    transport(late)
    with pytest.raises(InterruptedError):api.transcribe_wav(audio(),cfg,'key',cancel)


def test_model_test_only_gets_catalog_without_audio(cfg,transport):
    requests=transport(lambda request:httpx.Response(200,json={'data':[{'id':'gpt-transcribe'},{'id':'other'}]}))
    assert api.list_models(cfg,'key')==(True,2)
    assert requests[0].method=='GET' and requests[0].content==b''
    assert str(requests[0].url).endswith('/models')


@pytest.mark.parametrize('endpoint',['https://name:secret@host/v1','https://host/v1?secret=key','https://host/v1#x','http://remote.example/v1','http://0.0.0.0/v1','https://host/v1/audio/transcriptions'])
def test_bad_endpoint_has_fixed_safe_message(endpoint):
    with pytest.raises(api.CloudAsrError) as failure:api.normalized_base(endpoint)
    assert 'secret=key' not in str(failure.value) and 'name:secret' not in str(failure.value)


@pytest.mark.parametrize('endpoint',['https://host/v1','http://127.0.0.1:8000/v1','http://192.168.1.10:8000/v1'])
def test_explicit_secure_or_lan_endpoint(endpoint):assert api.normalized_base(endpoint)==endpoint


@pytest.mark.parametrize('backend,slot',list(api.KEY_SLOTS.items()))
def test_keys_are_provider_scoped(cfg,monkeypatch,backend,slot):
    calls=[]
    monkeypatch.setattr(api,'credential',lambda name:calls.append(name) or 'synthetic')
    cfg['asr_backend']=backend
    assert api.read_key(cfg)=='synthetic' and calls==[slot]
    assert api.read_key(cfg,'draft')=='draft' and calls==[slot]


def test_custom_model_never_guessed(cfg):
    cfg.update(asr_backend='http_asr',asr_http_model='')
    with pytest.raises(api.CloudAsrError,match='automatically'):api.request_settings(cfg)


@pytest.mark.parametrize('wav',[b'RIFFnotwave',b'',api.pcm_wav(b'\0\0')[:44]])
def test_invalid_wav_rejected_before_network(cfg,wav,monkeypatch):
    monkeypatch.setattr(api,'_request_json',lambda *args,**kwargs:pytest.fail('invalid WAV must not upload'))
    with pytest.raises(api.CloudAsrError):api.transcribe_wav(wav,cfg,'key')


def recorder_fixture(cfg,monkeypatch,pcm=None):
    import murmur.audio_capture as capture
    pcm=struct.pack('<h',1500)*1600 if pcm is None else pcm
    class Collector:
        duration=.1;error='';started=1
        def __init__(self,*args):self.pcm=pcm;self.closed=False;self.aborted=False
        def start(self):pass
        def close_input(self):self.closed=True
        def request_stop(self):self.closed=True
        def stop(self):return self.pcm
        def abort(self):self.aborted=True
    monkeypatch.setattr(capture,'PCMCollector',Collector)
    monkeypatch.setattr(api,'credential',lambda slot:'synthetic')
    recorder=api.HttpAsrRecorder(cfg,lambda text:pytest.fail('batch must not fake partial text'),lambda level:None,threading.Event())
    return recorder


def test_batch_recorder_waits_for_stop_and_saves_original(cfg,monkeypatch,tmp_path):
    cfg['save_audio']=True
    recorder=recorder_fixture(cfg,monkeypatch)
    requests=[]
    monkeypatch.setattr(api,'transcribe_wav',lambda wav,*args:requests.append(wav) or '中文')
    recorder.start()
    assert requests==[] and recorder.raw==''
    assert recorder.stop()=='中文' and recorder.collector.closed
    assert recorder.stop()=='中文' and len(requests)==1
    assert recorder._key=='' and recorder.audio_metadata['silent'] is False
    path=recorder.save_audio(tmp_path/'synthetic.wav')
    with wave.open(path,'rb') as saved:assert saved.readframes(saved.getnframes())==recorder.collector.pcm


def test_silent_recording_does_not_upload(cfg,monkeypatch):
    recorder=recorder_fixture(cfg,monkeypatch,b'\0\0'*1600)
    monkeypatch.setattr(api,'transcribe_wav',lambda *args:pytest.fail('silence must not upload'))
    recorder.start()
    with pytest.raises(RuntimeError,match='speech-level'):recorder.stop()
    assert recorder.raw=='' and recorder.error and recorder._key==''


def test_abort_suppresses_late_recorder_result(cfg,monkeypatch):
    recorder=recorder_fixture(cfg,monkeypatch)
    def late(*args):recorder.abort();return 'late text'
    monkeypatch.setattr(api,'transcribe_wav',late)
    recorder.start()
    with pytest.raises(InterruptedError):recorder.stop()
    assert recorder.raw=='' and recorder.collector.aborted


def test_audio_not_saved_unless_enabled(cfg,monkeypatch,tmp_path):
    recorder=recorder_fixture(cfg,monkeypatch)
    recorder.start()
    assert recorder.save_audio(tmp_path/'must-not-exist.wav')==''
    assert not (tmp_path/'must-not-exist.wav').exists()


def test_request_stop_seals_early_but_does_not_cancel_inference(cfg,monkeypatch):
    recorder=recorder_fixture(cfg,monkeypatch)
    monkeypatch.setattr(api,'transcribe_wav',lambda *args:'accepted before stop')
    recorder.start();recorder.request_stop()
    assert recorder.collector.closed and not recorder.cancel.is_set()
    assert recorder.stop()=='accepted before stop'


def test_request_stop_before_collector_publish_prevents_later_microphone(cfg,monkeypatch):
    import murmur.audio_capture as capture
    instances=[]
    class Collector:
        duration=0;error='';started=0;pcm=b''
        def __init__(self,*args):self.closed=False;instances.append(self)
        def request_stop(self):self.closed=True
        def start(self):assert self.closed, 'start must not open a late microphone'
        def abort(self):pass
    monkeypatch.setattr(capture,'PCMCollector',Collector)
    recorder=api.HttpAsrRecorder(cfg,lambda value:None,lambda level:None,threading.Event())
    def key(*args):recorder.request_stop();return 'synthetic'
    monkeypatch.setattr(api,'read_key',key)
    recorder.start()
    assert instances[0].closed and not recorder.cancel.is_set()

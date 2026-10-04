"""Connection checks negotiate services with synthetic inputs, never a mic."""
import copy
import hashlib
import json
import threading
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import sounddevice
from murmur import service_checks as checks
from murmur.storage import DEFAULTS


@pytest.fixture
def fixture(monkeypatch):
    cfg = copy.deepcopy(DEFAULTS)
    cfg.update(ollama=False,ollama_auto=False,llm_url='https://fixture.invalid/v1',asr_backend='bailian')
    calls = []
    saved = {'asr':'saved-asr', 'llm':'saved-llm', 'ali_appkey':'saved-appkey'}
    def credential(name, value=None):
        assert value is None, 'Connection check saved a draft credential'
        calls.append(name)
        return saved.get(name, '')
    monkeypatch.setattr(checks, 'credential', credential)
    monkeypatch.setattr(checks, '_CHECK_SLOTS', threading.BoundedSemaphore(2))
    monkeypatch.setattr(sounddevice, 'RawInputStream', lambda **kwargs:pytest.fail('Check opened microphone'))
    monkeypatch.setattr(checks.ali_auth, 'obtain_token', lambda cancel=None:'saved-token')
    return cfg, calls, saved


def install_http(monkeypatch, handler=None):
    requests = []
    real_client = httpx.Client
    def respond(request):
        requests.append(request)
        return handler(request) if handler else httpx.Response(200, json={
            'choices':[{'message':{'content':'OK'}}]})
    monkeypatch.setattr(checks.httpx, 'Client', lambda **kwargs:real_client(
        transport=httpx.MockTransport(respond), **kwargs))
    return requests


class Socket:
    def __init__(self, mode='success', cancel=None):
        self.mode = mode;self.cancel = cancel;self.commands = [];self.events = [];self.closed = False
    def settimeout(self, value):assert value == .5
    def send(self, value):
        command = json.loads(value);self.commands.append(command)
        header = command['header'];task_id = header['task_id']
        if header.get('name') == 'StartTranscription':
            response = {'header':{'task_id':task_id, 'name':'TranscriptionStarted', 'status':20000000}}
        elif header.get('action') == 'run-task':
            response = {'header':{'task_id':task_id, 'event':'task-started'}}
        else:return
        if self.mode == 'reject':
            response['header'].update(name='TaskFailed', event='task-failed', status=40000001,
                                      status_text='typed-secret token=typed-token', error_message='typed-secret')
        if self.mode == 'other_task':response['header']['task_id'] = 'different-task'
        self.events.append(json.dumps(response))
    def recv(self):
        if self.cancel:self.cancel.set()
        if self.mode == 'closed':return ''
        return self.events.pop(0) if self.events else ''
    def send_binary(self, value):pytest.fail('Check sent audio')
    def close(self, timeout=1):self.closed = True


def install_socket(monkeypatch, mode='success', cancel=None):
    sock = Socket(mode, cancel);connections = []
    def connect(url, **kwargs):connections.append((url, kwargs));return sock
    monkeypatch.setattr(checks.websocket, 'create_connection', connect)
    return sock, connections


def test_llm_current_config_draft_key_and_elapsed(fixture, monkeypatch):
    cfg, calls, _ = fixture;requests = install_http(monkeypatch)
    cfg.update(llm_url='https://fixture.invalid/v1', llm_model='draft-model', demo=True)
    result = checks.check_service('llm', cfg, {'llm':'typed-secret'})
    assert result['success'] and result['summary'] == 'Connected' and result['elapsed'] >= 0
    assert 's)' in result['detail'] and 'short test message' in result['detail']
    assert calls == [] and len(requests) == 1
    request = requests[0];body = json.loads(request.content)
    assert request.headers['Authorization'] == 'Bearer typed-secret'
    assert body['model'] == 'draft-model' and body['max_tokens'] == 8
    assert body['messages'] == [{'role':'user', 'content':'Reply with only OK.'}]
    assert 'reasoning_effort' not in body
    assert str(request.url) == 'https://fixture.invalid/v1/chat/completions'
    assert 'typed-secret' not in str(result)
    assert result['model'] == 'draft-model' and result['model_selection'] == 'manual'
    assert result['parameter_size'] is None and result['parameter_size_source'] is None


def test_blank_key_keeps_saved_key_and_ollama_needs_no_vault(fixture, monkeypatch):
    cfg, calls, _ = fixture;requests = install_http(monkeypatch)
    checks.check_service('llm', cfg, {'llm':'   '})
    assert calls == ['llm'] and requests[0].headers['Authorization'] == 'Bearer saved-llm'
    calls.clear();cfg.update(ollama=True, llm_url='http://127.0.0.1:11434')
    assert checks.check_service('llm', cfg)['success']
    assert calls == [] and json.loads(requests[-1].content)['reasoning_effort'] == 'none'
    assert str(requests[-1].url) == 'http://127.0.0.1:11434/v1/chat/completions'


@pytest.mark.parametrize('body', [{}, {'choices':[]}, {'choices':[{'message':{'content':''}}]},
    {'choices':[{'message':{'content':'   '}}]}, {'choices':[{'message':{'content':None}}]}])
def test_empty_llm_response_rejected(fixture, monkeypatch, body):
    cfg, _, _ = fixture;install_http(monkeypatch, lambda request:httpx.Response(200, json=body))
    result = checks.check_service('llm', cfg)
    assert not result['success'] and result['summary'] == 'Empty or invalid model response'


def test_llm_http_failure_body_and_exception_are_redacted(fixture, monkeypatch):
    cfg, _, _ = fixture
    install_http(monkeypatch, lambda request:httpx.Response(401, text='typed-secret signed-url token=typed-token'))
    result = checks.check_service('llm', cfg, {'llm':'typed-secret'})
    assert not result['success'] and 'HTTP 401' in result['detail'] and 'typed-secret' not in str(result)


@pytest.mark.parametrize('backend', ['bailian', 'ali_nls'])
def test_asr_requires_matching_start_ack_and_sends_stop_without_audio(fixture, monkeypatch, backend):
    cfg, calls, _ = fixture;cfg['asr_backend'] = backend;sock, connections = install_socket(monkeypatch)
    result = checks.check_service('asr', cfg, {'asr':'typed-secret', 'ali_appkey':'typed-appkey', 'ali_token':'typed-token'})
    assert result['success'] and 'credentials were accepted' in result['detail']
    assert 'No microphone audio was sent' in result['detail'] and sock.closed
    assert calls == [] and len(sock.commands) == 2
    first, last = sock.commands
    assert first['header']['task_id'] == last['header']['task_id']
    if backend == 'ali_nls':
        assert first['header']['name'] == 'StartTranscription' and last['header']['name'] == 'StopTranscription'
        assert parse_qs(urlsplit(connections[0][0]).query) == {'token':['typed-token']}
    else:
        assert first['header']['action'] == 'run-task' and last['header']['action'] == 'finish-task'
        assert first['payload']['model'] == cfg['asr_model']
        assert first['payload']['parameters']['sample_rate'] == 16000
        assert connections[0][1]['header']['Authorization'] == 'Bearer typed-secret'
    assert 'typed-token' not in str(result) and 'typed-secret' not in str(result)


@pytest.mark.parametrize('backend', ['bailian', 'ali_nls'])
@pytest.mark.parametrize('mode', ['reject', 'closed', 'other_task'])
def test_tcp_connect_or_wrong_task_never_proves_service(fixture, monkeypatch, backend, mode):
    cfg, _, _ = fixture;cfg['asr_backend'] = backend;sock, _ = install_socket(monkeypatch, mode)
    result = checks.check_service('asr', cfg)
    assert not result['success'] and sock.closed
    assert 'typed-secret' not in str(result) and 'typed-token' not in str(result)
    assert len(sock.commands) == 1


def test_unsaved_ak_only_uses_ephemeral_token_request_and_manual_token_wins(fixture, monkeypatch):
    cfg, _, saved = fixture;cfg['asr_backend'] = 'ali_nls';requests = []
    saved['ali_access_key_secret'] = 'saved-secret'
    def ephemeral(key_id, secret, cancel):
        requests.append((key_id, secret));return 'ephemeral-token', 2000003600
    monkeypatch.setattr(checks.ali_auth, '_request_token', ephemeral)
    install_socket(monkeypatch)
    assert checks.check_service('asr', cfg, {'ali_access_key_id':'typed-id'})['success']
    assert requests == [('typed-id', 'saved-secret')]
    install_socket(monkeypatch)
    assert checks.check_service('asr', cfg, {'ali_token':'typed-token', 'ali_access_key_id':'another-id'})['success']
    assert len(requests) == 1


def test_cancel_before_request_and_after_start_closes_without_success(fixture, monkeypatch):
    cfg, calls, _ = fixture;cfg['asr_backend'] = 'ali_nls';cancel = threading.Event();cancel.set()
    sock, connections = install_socket(monkeypatch)
    assert checks.check_service('asr', cfg, cancel=cancel)['summary'] == 'Cancelled'
    assert calls == [] and connections == []
    cancel.clear();sock, _ = install_socket(monkeypatch, cancel=cancel)
    result = checks.check_service('asr', cfg, cancel=cancel)
    assert not result['success'] and result['summary'] == 'Cancelled' and sock.closed


def test_socket_timeout_and_original_exception_never_escape(fixture, monkeypatch):
    cfg, _, _ = fixture
    for error in (checks.websocket.WebSocketTimeoutException, RuntimeError):
        def fail(*args, **kwargs):raise error('typed-secret signed-url token=typed-token')
        monkeypatch.setattr(checks.websocket, 'create_connection', fail)
        result = checks.check_service('asr', cfg, {'asr':'typed-secret'})
        assert not result['success'] and 'typed-secret' not in str(result) and 'typed-token' not in str(result)


def test_offline_integrity_then_load_no_decode_network_or_credential(fixture, monkeypatch, tmp_path):
    cfg, calls, _ = fixture;cfg.update(asr_backend='offline', offline_model_dir=str(tmp_path));loaded = []
    files = {'model.int8.onnx':b'fixture-model', 'tokens.txt':b'fixture-tokens'}
    for name, data in files.items():(tmp_path / name).write_bytes(data)
    monkeypatch.setattr(checks.models, 'FILES', {name:(len(data), hashlib.sha256(data).hexdigest()) for name,data in files.items()})
    monkeypatch.setattr(checks.offline, 'load_recognizer', lambda cfg,cancel:loaded.append(cfg))
    monkeypatch.setattr(checks.websocket, 'create_connection', lambda *args,**kwargs:pytest.fail('Offline check accessed network'))
    result = checks.check_service('asr', cfg)
    assert result['success'] and result['summary'] == 'Model loaded' and len(loaded) == 1 and calls == []
    assert 'local model loaded successfully' in result['detail'] and 'longer than 30 seconds' in result['detail']
    (tmp_path / 'tokens.txt').write_bytes(b'damaged-tokens')
    result = checks.check_service('asr', cfg)
    assert not result['success'] and result['summary'] == 'Model integrity check failed' and len(loaded) == 1


def test_check_concurrency_is_bounded_and_slot_releases(fixture):
    cfg, _, _ = fixture
    checks._CHECK_SLOTS.acquire();checks._CHECK_SLOTS.acquire()
    try:
        result = checks.check_service('llm', cfg)
        assert not result['success'] and result['summary'] == 'Checks already running'
    finally:checks._CHECK_SLOTS.release();checks._CHECK_SLOTS.release()
    cfg['asr_backend'] = 'unknown'
    assert not checks.check_service('asr', cfg)['success']
    assert checks._CHECK_SLOTS.acquire(blocking=False)
    assert checks._CHECK_SLOTS.acquire(blocking=False)
    assert not checks._CHECK_SLOTS.acquire(blocking=False)
    checks._CHECK_SLOTS.release();checks._CHECK_SLOTS.release()


def test_invalid_kind_and_missing_configuration_fail_safely(fixture):
    cfg, _, saved = fixture
    assert checks.check_service('unknown', cfg)['summary'] == 'Unknown service'
    saved.clear()
    assert checks.check_service('llm', cfg)['summary'] == 'API key missing'
    cfg['llm_url'] = 'https://typed-secret@fixture.invalid/?token=typed-token'
    result = checks.check_service('llm', cfg)
    assert not result['success'] and 'typed-secret' not in str(result) and 'typed-token' not in str(result)


def test_changed_saved_credentials_get_actionable_retry_message(fixture, monkeypatch):
    cfg, _, _ = fixture;cfg['asr_backend'] = 'ali_nls'
    def changed(cancel=None):
        raise checks.ali_auth.AliAuthError('Credentials changed. Try again.')
    monkeypatch.setattr(checks.ali_auth, 'obtain_token', changed)
    result = checks.check_service('asr', cfg)
    assert not result['success'] and result['summary'] == 'Credentials changed'
    assert result['detail'] == 'Saved credentials changed during the check. Test again.'


def test_auto_check_reports_the_selected_request_model_without_an_extra_inventory_call(fixture, monkeypatch):
    cfg, calls, _ = fixture
    cfg.update(ollama=True, ollama_auto=True, llm_url='http://127.0.0.1:11434', llm_model='saved:4b')
    def respond(request):
        if request.url.path == '/api/tags':
            return httpx.Response(200, json={'models':[
                {'name':'qwen3.5:9b', 'details':{'parameter_size':'9B'}},
                {'name':'qwen3.5:2b', 'details':{'parameter_size':'2.3B'}}]})
        assert request.url.path == '/v1/chat/completions'
        assert json.loads(request.content)['model'] == 'qwen3.5:2b'
        return httpx.Response(200, json={'model':'canonical:2b',
            'choices':[{'message':{'content':'OK'}}],
            'usage':{'prompt_tokens':8, 'completion_tokens':1, 'total_tokens':9}})
    requests = install_http(monkeypatch, respond)
    usage = []
    result = checks.check_service('llm', cfg, usage_sink=usage.append)
    assert result['success'] and result['model'] == 'qwen3.5:2b'
    assert result['model_selection'] == 'auto' and result['response_model'] == 'canonical:2b'
    assert result['parameter_size'] == '2B' and result['parameter_size_source'] == 'model_name'
    # The name tag is not a claim about the inventory's reported exact size.
    assert result['parameter_size'] != '2.3B'
    assert cfg['llm_model'] == 'saved:4b'
    assert result['usage']['model'] == 'canonical:2b' and result['usage']['total_tokens'] == 9
    assert usage == [result['usage']] and len(requests) == 2 and calls == []


@pytest.mark.parametrize('model,expected', [
    ('qwen3.5:4b', '4B'), ('Qwen/Qwen3.5-2B', '2B'), ('fixture:500m', '500M'),
    ('fixture-2.3B-instruct', '2.3B'), ('draft-model', None), ('fixture:latest', None),
    ('fixture-v4', None), ('fixture-prefix4b', None), ('fixture:0b', None),
    ('fixture:1234567b', None), ('fixture:2.1234b', None),
])
def test_explicit_model_tags_are_bounded_and_unknown_sizes_stay_unknown(fixture, monkeypatch, model, expected):
    cfg, _, _ = fixture
    cfg['llm_model'] = model
    requests = install_http(monkeypatch)
    result = checks.check_service('llm', cfg)
    assert result['success'] and result['model'] == model and result['model_selection'] == 'manual'
    assert result['parameter_size'] == expected
    assert result['parameter_size_source'] == ('model_name' if expected is not None else None)
    assert 'response_model' not in result and len(requests) == 1


@pytest.mark.parametrize('reported', [None, False, 4, {}, '', '  ', 'unsafe\nmodel',
                                    '<img src=private-file>', 'x' * 257])
def test_invalid_response_model_is_not_exposed(fixture, monkeypatch, reported):
    cfg, _, _ = fixture
    cfg['llm_model'] = 'requested-model'
    install_http(monkeypatch, lambda request:httpx.Response(200, json={
        'model':reported, 'choices':[{'message':{'content':'OK'}}]}))
    result = checks.check_service('llm', cfg)
    assert result['success'] and result['model'] == 'requested-model'
    assert 'response_model' not in result


def test_a_failed_model_check_does_not_claim_a_verified_identity(fixture, monkeypatch):
    cfg, _, _ = fixture
    cfg['llm_model'] = 'fixture:4b'
    install_http(monkeypatch, lambda request:httpx.Response(401, json={'model':'unverified:4b'}))
    result = checks.check_service('llm', cfg)
    assert not result['success'] and result['summary'] == 'Model request rejected'
    assert not {'model', 'model_selection', 'response_model', 'parameter_size', 'parameter_size_source'} & result.keys()

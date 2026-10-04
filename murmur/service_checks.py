"""Small, cancellable checks against the current unsaved Settings values.

ASR checks negotiate real tasks without opening a microphone or sending audio.
LLM checks send only a fixed test prompt. Draft credentials are never persisted.
Bailian protocol: https://help.aliyun.com/en/model-studio/fun-asr-client-events
NLS protocol: https://help.aliyun.com/zh/isi/user-guide/websocket
"""
import copy
import hashlib
import json
import math
import re
import threading
import time
import uuid
from urllib.parse import urlsplit, urlencode

import httpx
import websocket
from .storage import credential
from . import ali_auth, offline, models
from .usage import publish_usage
from .local_llm import resolve_model,LocalModelError,auto_enabled,request_extensions
from .usage import is_local_endpoint
from .assistant import ask_config, ask_messages, parse_ask_result

_CHECK_SLOTS = threading.BoundedSemaphore(2)
HANDSHAKE_SECONDS = 12.0
MAX_RESPONSE_BYTES = 65536


class _CheckError(RuntimeError):
    def __init__(self, summary, detail):
        self.summary = summary
        self.detail = detail


def _cancelled(cancel):
    if cancel is not None and cancel.is_set():raise InterruptedError()


def _draft(name, secrets):
    value = secrets.get(name, '')
    return str(value).strip() if value else ''


def _secret(name, secrets):
    value = _draft(name, secrets)
    if value:return value
    try:return credential(name)
    except Exception:
        raise _CheckError('Credentials unavailable', 'Windows Credential Manager could not be read. Try again.') from None


def _endpoint(value, schemes):
    parts = urlsplit(value)
    if (parts.scheme not in schemes or not parts.hostname or parts.username or
            parts.password or parts.query or parts.fragment):
        raise _CheckError('Invalid endpoint', 'Choose an endpoint with the correct protocol and no embedded credentials, query, or fragment.')
    return value.rstrip('/')


def _nls_token(secrets, cancel):
    manual = _draft('ali_token', secrets)
    if manual:return manual
    if _draft('ali_access_key_id', secrets) or _draft('ali_access_key_secret', secrets):
        key_id = _secret('ali_access_key_id', secrets)
        secret = _secret('ali_access_key_secret', secrets)
        if not key_id or not secret:
            raise _CheckError('AccessKey pair incomplete', 'Enter both AccessKey ID and AccessKey Secret, or a temporary NLS token.')
        # The request helper signs/validates without performing any Vault writes.
        return ali_auth._request_token(key_id, secret, cancel)[0]
    return ali_auth.obtain_token(cancel)


def _wait_started(sock, task_id, dialect, cancel):
    deadline = time.monotonic() + HANDSHAKE_SECONDS
    for _ in range(128):
        _cancelled(cancel)
        if time.monotonic() >= deadline:
            raise _CheckError('Connection timed out', 'The server did not acknowledge the ASR task. Check credentials, model, endpoint region, and service availability.')
        try:encoded = sock.recv()
        except websocket.WebSocketTimeoutException:continue
        if not encoded:
            raise _CheckError('Connection closed', 'The server closed the connection before acknowledging the ASR task.')
        if len(encoded) > MAX_RESPONSE_BYTES:
            raise _CheckError('Invalid service response', 'The ASR service returned an unexpected response.')
        try:
            data = json.loads(encoded)
            header = data['header']
            if not isinstance(header, dict):raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise _CheckError('Invalid service response', 'The ASR service returned an unexpected response.') from None
        # No event from another task can certify this configuration.
        if header.get('task_id') != task_id:continue
        if dialect == 'nls':
            event = header.get('name')
            status = header.get('status', 20000000)
            if event == 'TaskFailed' or status != 20000000:
                code = f' (code {status})' if type(status) is int else ''
                raise _CheckError('NLS service rejected the task', 'Check the project AppKey, token, service activation and permissions' + code + '.')
            if event == 'TranscriptionStarted':return
        else:
            event = header.get('event')
            if event == 'task-failed':
                raise _CheckError('Bailian service rejected the task', 'Check the ASR model, API key permissions and matching endpoint region.')
            if event == 'task-started':return
    raise _CheckError('Invalid service response', 'No matching ASR startup acknowledgement was received.')


def _cloud_asr(cfg, secrets, cancel, backend):
    _cancelled(cancel)
    task_id = uuid.uuid4().hex
    if backend == 'ali_nls':
        appkey = _secret('ali_appkey', secrets)
        if not appkey:
            raise _CheckError('AppKey missing', 'Enter the Alibaba NLS project AppKey before testing.')
        endpoint = _endpoint(cfg.get('ali_nls_url', 'wss://nls-gateway-cn-shanghai.aliyuncs.com/ws/v1').strip(), ('wss',))
        token = _nls_token(secrets, cancel)
        url = endpoint + '?' + urlencode({'token':token})
        options = {}
        def command(name, payload=None):
            value = {'header':{'appkey':appkey, 'message_id':uuid.uuid4().hex,
                     'task_id':task_id, 'namespace':'SpeechTranscriber', 'name':name}}
            if payload is not None:value['payload'] = payload
            return value
        start = command('StartTranscription', {'format':'pcm', 'sample_rate':16000,
                        'enable_intermediate_result':True, 'enable_punctuation_prediction':True,
                        'enable_inverse_text_normalization':True})
        finish = command('StopTranscription')
        dialect = 'nls'
    else:
        key = _secret('asr', secrets)
        if not key:
            raise _CheckError('API key missing', 'Enter a Bailian ASR API key before testing.')
        endpoint = _endpoint(cfg.get('asr_url', '').strip(), ('wss',))
        model = cfg.get('asr_model', '').strip()
        if not model:
            raise _CheckError('Model missing', 'Enter an ASR model name before testing.')
        url = endpoint
        options = {'header':{'Authorization':'Bearer ' + key}}
        parameters = {'format':'pcm', 'sample_rate':16000}
        if cfg.get('vocabulary_id'):parameters['vocabulary_id'] = cfg['vocabulary_id']
        start = {'header':{'action':'run-task', 'task_id':task_id, 'streaming':'duplex'},
                 'payload':{'task_group':'audio', 'task':'asr', 'function':'recognition',
                            'model':model, 'parameters':parameters, 'input':{}}}
        finish = {'header':{'action':'finish-task', 'task_id':task_id, 'streaming':'duplex'},
                  'payload':{'input':{}}}
        dialect = 'bailian'
    _cancelled(cancel)
    sock = None
    try:
        sock = websocket.create_connection(url, timeout=5, enable_multithread=True, **options)
        sock.settimeout(.5)
        _cancelled(cancel)
        sock.send(json.dumps(start, separators=(',', ':')))
        _wait_started(sock, task_id, dialect, cancel)
        _cancelled(cancel)
        # A real task acknowledgement proves access; completion with an empty
        # audio stream is not an accuracy test. Explicitly terminate the task.
        sock.send(json.dumps(finish, separators=(',', ':')))
        return ('Connected', 'Your credentials were accepted by the speech service. No microphone audio was sent.')
    finally:
        if sock is not None:
            try:sock.close(timeout=1)
            except Exception:pass


def _offline(cfg, cancel):
    try:model, tokens, _, _ = offline.model_files(cfg)
    except RuntimeError as exc:
        raise _CheckError('Offline model unavailable', str(exc)) from None
    except Exception:
        raise _CheckError('Offline model unavailable', 'Choose a complete folder for the selected local speech model and supported language/thread settings.') from None
    engine=cfg.get('offline_engine','sensevoice')
    spec=offline.model_spec(cfg)
    expected_files=spec['files']
    # Downloaded INT8 models use the pinned manifest. Imported FP32 ONNX
    # models are validated by the native loader rather than a different
    # model's hashes; do not claim that they match the pinned download.
    imported=model.name=='model.onnx' and spec['kind']=='sherpa'
    files = [] if imported else offline.model_paths(cfg)
    if spec.get('archive'):
        manifest=model.parent/'murmur-model.json'
        if manifest.is_file():
            expected_files=models.installed_file_hashes(model.parent,engine,cfg.get('offline_acceleration','cpu'))
            if not expected_files:
                raise _CheckError('Model integrity check failed','The installed model record is incomplete or belongs to another model version. Download the complete model again.') from None
        else:
            imported=True;files=[]
    vad = model.parent / 'silero_vad.onnx'
    if vad.exists():files.append(vad)
    for path in files:
        _cancelled(cancel)
        size, expected = expected_files[path.name]
        if not path.is_file() or path.stat().st_size != size:
            raise _CheckError('Model integrity check failed', 'Download the complete official model files before testing.')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024 * 1024), b''):
                _cancelled(cancel)
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise _CheckError('Model integrity check failed', 'Download the complete official model files before testing.')
    try:offline.load_recognizer(cfg, cancel)
    except InterruptedError:raise
    except RuntimeError as exc:
        raise _CheckError('Model could not load',str(exc)) from None
    except Exception:
        raise _CheckError('Model could not load', 'Verified local model files could not be loaded. Check the installed runtime and CPU settings.') from None
    _cancelled(cancel)
    detail = ('The imported local model loaded successfully. Its speech model files were not checked against the pinned download.' if imported
              else 'The model files are valid and the local model loaded successfully.')
    if not imported and spec.get('archive'):
        detail='The model files match their verified installation record and the local model loaded successfully.'
    if not vad.is_file():detail += ' Download Silero VAD to record longer than 30 seconds.'
    return 'Model loaded', detail


def _checked_model_metadata(model, response, automatic):
    """Report the request identity; parameter labels are never measured sizes."""
    result = {'model':model, 'model_selection':'auto' if automatic else 'manual',
              'parameter_size':None, 'parameter_size_source':None}
    reported = response.get('model') if isinstance(response, dict) else None
    if (isinstance(reported, str) and reported.strip() and len(reported) <= 256
            and re.fullmatch(r'[\w./:@+\- ]+', reported)):
        result['response_model'] = reported.strip()
    match = re.search(r'(?:^|[-_: /])(\d{1,6}(?:\.\d{1,3})?)([BM])(?=$|[-_: /])', model, re.I)
    if match:
        size = float(match[1])
        if math.isfinite(size) and size > 0:
            result['parameter_size'] = f'{size:g}{match[2].upper()}'
            result['parameter_size_source'] = 'model_name'
    return result


def _llm(cfg, secrets, cancel, usage_sink=None, kind='llm'):
    if kind=='ask':
        try:cfg=ask_config(cfg)
        except RuntimeError as exc:raise _CheckError('Invalid Ask Anything configuration',str(exc)) from None
    base = _endpoint(cfg.get('llm_url', '').strip(), ('http', 'https'))
    ollama = bool(cfg.get('ollama'))
    if ollama and not base.endswith('/v1'):base += '/v1'
    model = cfg.get('llm_model', '').strip()
    if not model and not auto_enabled(cfg):raise _CheckError('Model missing', 'Enter an LLM model name before testing.')
    key = _secret('ask_llm', secrets) if kind=='ask' else 'local' if is_local_endpoint(base) else 'ollama' if ollama else _secret('llm', secrets)
    if not key:raise _CheckError('API key missing', 'Enter an Ask Anything API key before testing.' if kind=='ask' else 'Enter an LLM API key before testing.')
    request = {'model':model, 'messages':[{'role':'user', 'content':'Reply with only OK.'}],
               'temperature':0, 'max_tokens':8}
    if kind=='ask':
        request.update(messages=ask_messages('Reply with only OK.', ''),max_tokens=64,
                       response_format={'type':'json_object'})
    _cancelled(cancel)
    deadline = time.monotonic() + 35
    automatic = auto_enabled(cfg)
    with httpx.Client(timeout=httpx.Timeout(30, connect=5, write=5, pool=5), follow_redirects=False) as client:
        cfg=dict(cfg,llm_model=resolve_model(client,cfg,cancel));request['model']=cfg['llm_model']
        request.update(request_extensions(client,cfg,cancel))
        with client.stream('POST', base + '/chat/completions',
                           headers={'Authorization':'Bearer ' + key}, json=request) as response:
            if response.status_code != 200:
                status = response.status_code
                raise _CheckError('Model request rejected', f'HTTP {status}. Check the API key, model availability and endpoint.')
            body = bytearray()
            for chunk in response.iter_bytes():
                if time.monotonic() >= deadline:
                    raise _CheckError('Connection timed out', 'The LLM service did not respond within the test timeout.')
                if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise _CheckError('Invalid model response', 'The LLM service returned an unexpected response.')
                body.extend(chunk)
                if cancel is not None and cancel.is_set():
                    # A fully received JSON response can already contain billed
                    # usage. Preserve that metadata before suppressing the text.
                    try:ready = json.loads(body)
                    except (ValueError, UnicodeError):ready = None
                    if isinstance(ready,dict):publish_usage(ready,cfg,usage_sink)
                    _cancelled(cancel)
            try:
                data = json.loads(body)
            except (ValueError, UnicodeError):data={}
            usage = publish_usage(data,cfg,usage_sink)
            _cancelled(cancel)
            try:
                value = data['choices'][0]['message']['content']
                if not isinstance(value, str) or not value.strip():raise ValueError()
                if kind=='ask':
                    parsed=parse_ask_result(value)
                    if parsed.action=='replace':raise ValueError()
            except (ValueError, KeyError, IndexError, TypeError):
                raise _CheckError('Empty or invalid model response', 'The selected model did not return non-empty text for the fixed test prompt.') from None
            except RuntimeError:
                raise _CheckError('Invalid assistant response', 'The selected model did not return the required JSON action and text. Choose a model that supports JSON mode.') from None
    return ('Connected', 'The selected model responded successfully to a short test message.', usage,
            _checked_model_metadata(cfg['llm_model'], data, automatic))


def check_service(kind, cfg, secrets=None, cancel=None, usage_sink=None):
    """Return safe UI-ready status; must run on a background worker.

    Native offline model loading cannot be interrupted mid-call; cancellation
    suppresses its result, and a bounded slot remains held until loading exits.
    """
    started = time.monotonic()
    acquired = False
    captured_usage = None
    def capture_usage(metadata):
        nonlocal captured_usage
        captured_usage = metadata
        if usage_sink is not None:
            try:usage_sink(copy.deepcopy(metadata))
            except Exception:pass
    try:
        _cancelled(cancel)
        if kind not in ('asr', 'llm', 'ask'):
            raise _CheckError('Unknown service', 'Choose ASR, LLM or Ask Anything to test.')
        acquired = _CHECK_SLOTS.acquire(blocking=False)
        if not acquired:
            raise _CheckError('Checks already running', 'Wait for the previous connection checks to finish.')
        usage = None
        model_metadata = None
        if kind in ('llm','ask'):summary, detail, usage, model_metadata = _llm(cfg, secrets or {}, cancel, capture_usage,kind)
        elif cfg.get('asr_backend', 'bailian') == 'offline':summary, detail = _offline(cfg, cancel)
        elif cfg.get('asr_backend', 'bailian') in ('bailian', 'ali_nls'):
            summary, detail = _cloud_asr(cfg, secrets or {}, cancel, cfg.get('asr_backend', 'bailian'))
        else:raise _CheckError('Unknown ASR backend', 'Choose a supported speech recognition provider.')
        _cancelled(cancel)
        elapsed = max(0., time.monotonic() - started)
        result = {'success':True, 'summary':summary, 'detail':detail + f' ({elapsed:.1f}s)', 'elapsed':elapsed}
        if usage is not None:result['usage'] = usage
        if model_metadata is not None:result.update(model_metadata)
        return result
    except InterruptedError:summary, detail = 'Cancelled', 'Connection check cancelled.'
    except _CheckError as exc:summary, detail = exc.summary, exc.detail
    except LocalModelError as exc:summary, detail = 'Local model unavailable', str(exc)
    except ali_auth.AliAuthError as exc:
        if str(exc) == 'Credentials changed. Try again.':
            summary, detail = 'Credentials changed', 'Saved credentials changed during the check. Test again.'
        else:
            summary, detail = 'Token unavailable', 'NLS token could not be obtained. Check AccessKey permissions or enter a valid manual token.'
    except (httpx.TimeoutException, websocket.WebSocketTimeoutException):
        summary, detail = 'Connection timed out', 'The service did not respond before the timeout. Check the endpoint and try again.'
    except Exception:
        summary, detail = 'Connection failed', 'Could not verify this service. Check credentials, endpoint, permissions and installed dependencies.'
    finally:
        if acquired:_CHECK_SLOTS.release()
    if cancel is not None and cancel.is_set():summary, detail = 'Cancelled', 'Connection check cancelled.'
    result = {'success':False, 'summary':summary, 'detail':detail, 'elapsed':max(0., time.monotonic() - started)}
    if captured_usage is not None:result['usage'] = captured_usage
    return result

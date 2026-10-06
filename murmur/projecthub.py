"""ProjectHub's restricted, durable asynchronous text protocol."""
import hashlib
import json
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit, quote

from .paths import data_dir

BASE_URL = 'https://openclaw.icalculate.website/ai'
DEFAULT_MODEL = 'gemini-3-6-flash'  # Example only; authenticated discovery is authoritative.
POLL_SECONDS = 2.0
WAIT_SECONDS = 960.0
_LOCK = threading.Lock()


def is_projecthub(base):
    parsed = urlsplit(base)
    return (parsed.scheme == 'https' and parsed.hostname == 'openclaw.icalculate.website'
            and parsed.path.rstrip('/') in ('/ai', '/ai/v1'))


def root_url(base):
    base = base.rstrip('/')
    return base[:-3] if base.endswith('/v1') else base


def _cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError()


def _json(response):
    if response.status_code >= 400:
        raise RuntimeError(f'ProjectHub request failed (HTTP {response.status_code}). '
                           'Your text and any submitted task are preserved; check the key, model and gateway.')
    try:
        value = response.json()
        if not isinstance(value, dict):raise ValueError()
        return value
    except ValueError:
        raise RuntimeError('ProjectHub returned an invalid response. Your request record is preserved.') from None


def discover(client, base, key, cancel=None):
    headers = {'Authorization': 'Bearer '+key}
    _cancel(cancel)
    models = _json(client.get(root_url(base)+'/v1/models', headers=headers))
    _cancel(cancel)
    capabilities = _json(client.get(root_url(base)+'/v1/capabilities', headers=headers))
    entries = models.get('data')
    if not isinstance(entries, list):
        raise RuntimeError('ProjectHub returned an invalid model list.')
    available = [item for item in entries if isinstance(item, dict) and item.get('available') is True
                 and isinstance(item.get('id'), str) and item['id']
                 and isinstance(item.get('gateway_input'), list) and '文字' in item['gateway_input']
                 and isinstance(item.get('gateway_output'), list) and '文字' in item['gateway_output']
                 and item['id'] not in ('ai-image', 'ai-minute')]
    return available, capabilities


def _store(cfg):
    path = Path(cfg.get('_data_dir') or data_dir())/'projecthub-tasks.sqlite3'
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.execute('CREATE TABLE IF NOT EXISTS tasks (fingerprint TEXT PRIMARY KEY, request_key TEXT, '
               'base TEXT, body TEXT, task_id TEXT, status TEXT)')
    return db


def completion(client, messages, cfg, key, cancel=None):
    """Resume the exact unfinished action, even after restart; never silently regenerate."""
    base = root_url(cfg['llm_url'])
    model = cfg['llm_model'].strip()
    if not key:raise RuntimeError('Enter a ProjectHub API key before starting.')
    if not model:raise RuntimeError('Enter an authorized ProjectHub model ID.')
    if (not 1 <= len(messages) <= 30 or messages[-1].get('role') != 'user'
            or any(set(m) != {'role', 'content'} or m['role'] not in ('system','user','assistant')
                   or not isinstance(m['content'], str) or not m['content'].strip() for m in messages)):
        raise RuntimeError('ProjectHub needs 1–30 text messages ending in a user message.')
    if len(json.dumps(messages, ensure_ascii=False).encode('utf-8')) > 100000:
        raise RuntimeError('ProjectHub text exceeds its 100,000-byte limit. Your original text is preserved.')
    body = {'model': model, 'messages': messages, 'stream': False}
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True)
    fingerprint = hashlib.sha256((base+'\0'+key+'\0'+encoded).encode()).hexdigest()
    headers = {'Authorization': 'Bearer '+key}
    while not _LOCK.acquire(timeout=.05):_cancel(cancel)
    try:
        with closing(_store(cfg)) as db:
            record = db.execute('SELECT request_key, task_id, status FROM tasks WHERE fingerprint=?',
                                (fingerprint,)).fetchone()
            if record:
                request_key, task_id, status = record
                if status in ('failed','indeterminate','cancelled','expired'):
                    raise RuntimeError(f'ProjectHub previous task is {status}; automatic replacement stopped. '
                                       'Resolve the saved task with the gateway owner before requesting a replacement.')
            else:
                _cancel(cancel)
                models, _ = discover(client, base, key, cancel)
                if not any(item['id'] == model for item in models):
                    ids = ', '.join(item['id'] for item in models)
                    raise RuntimeError('ProjectHub model is unavailable or unauthorized. Available text model IDs: '+ids)
                request_key = uuid.uuid4().hex
                task_id = None
                db.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?)',
                           (fingerprint,request_key,base,encoded,None,'submitting'))
                db.commit()  # Durable before a POST can reach the service.
            _cancel(cancel)
            if not task_id:
                accepted = _json(client.post(base+'/jobs', headers=dict(headers, **{'Idempotency-Key':request_key}),
                                             json=json.loads(encoded), timeout=30))
                task_id = accepted.get('id')
                if not isinstance(task_id, str) or not task_id or len(task_id)>200:
                    raise RuntimeError('ProjectHub did not return a task ID. Retry the same action to recover its original submission.')
                db.execute('UPDATE tasks SET task_id=?, status=? WHERE fingerprint=?', (task_id,'queued',fingerprint))
                db.commit()
            deadline = time.monotonic()+WAIT_SECONDS
            while True:
                _cancel(cancel)
                job = _json(client.get(base+'/jobs/'+quote(task_id, safe=''), headers=headers, timeout=30))
                status = job.get('status')
                if status not in ('queued','running','succeeded','failed','indeterminate','cancelled'):
                    raise RuntimeError('ProjectHub returned an unknown task state. The saved task can be queried again.')
                if job.get('result_expired'):status = 'expired'
                db.execute('UPDATE tasks SET status=? WHERE fingerprint=?', (status,fingerprint));db.commit()
                if status == 'succeeded':
                    result = job.get('result')
                    try:
                        content = result['choices'][0]['message']['content']
                        if not isinstance(content,str) or not content.strip():raise ValueError()
                    except (KeyError,IndexError,TypeError,ValueError):
                        raise RuntimeError('ProjectHub returned an invalid completed result. The saved task is preserved.') from None
                    _cancel(cancel)
                    db.execute('DELETE FROM tasks WHERE fingerprint=?',(fingerprint,));db.commit()
                    return result
                if status in ('failed','indeterminate','cancelled','expired'):
                    raise RuntimeError(f'ProjectHub task is {status}. Your text is preserved; '
                                       'automatic replacement stopped. Resolve it with the gateway owner.')
                if time.monotonic()>=deadline:
                    raise RuntimeError('ProjectHub is still processing. Retry the same action to resume the saved task; no new generation will be submitted.')
                if cancel is not None:
                    if cancel.wait(POLL_SECONDS):raise InterruptedError()
                else:time.sleep(POLL_SECONDS)
    finally:
        _LOCK.release()


def main():
    """Explicit recovery after restart using the original Credential Manager slot."""
    import argparse
    import httpx
    from .storage import credential
    parser = argparse.ArgumentParser(description='List or resume preserved ProjectHub text tasks.')
    parser.add_argument('action', choices=('list','resume'))
    parser.add_argument('--request-key', help='Original idempotency key shown by list')
    parser.add_argument('--credential', choices=('llm','ask_llm'), default='llm')
    parser.add_argument('--data-dir', default=str(data_dir()))
    args = parser.parse_args()
    cfg = {'_data_dir':args.data_dir}
    with closing(_store(cfg)) as db:
        records = db.execute('SELECT request_key, base, body, task_id, status FROM tasks').fetchall()
    if args.action=='list':
        for request_key, base, body, task_id, status in records:
            print(json.dumps({'request_key':request_key,'task_id':task_id,'status':status},ensure_ascii=False))
        return
    matches = [r for r in records if r[0]==args.request_key]
    if len(matches)!=1:parser.error('Choose an existing request key from list.')
    request_key, base, encoded, task_id, status = matches[0]
    body = json.loads(encoded)
    key = credential(args.credential)
    if not key:parser.error('The original API key must be saved in the selected Windows credential slot.')
    fingerprint = hashlib.sha256((base+'\0'+key+'\0'+json.dumps(body,ensure_ascii=False,sort_keys=True)).encode()).hexdigest()
    with closing(_store(cfg)) as db:
        if db.execute('SELECT request_key FROM tasks WHERE fingerprint=?',(fingerprint,)).fetchone()!=(request_key,):
            parser.error('Use the original API key; a different key cannot recover this task.')
    cfg.update(llm_url=base,llm_model=body['model'])
    try:
        with httpx.Client(timeout=httpx.Timeout(30,connect=10)) as client:
            result = completion(client,body['messages'],cfg,key)
        print(result['choices'][0]['message']['content'])
    except (RuntimeError,httpx.HTTPError):
        parser.exit(1,'Recovery did not complete. The original task record is preserved; check the gateway status.\n')


if __name__=='__main__':main()

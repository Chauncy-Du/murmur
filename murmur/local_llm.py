"""Resolve local Auto over standard /models or the optional Ollama adapter.

Only list existing server models: never install models or fall back to cloud.
The standard model list does not guarantee a loaded state; do not infer it.
Auto prefers the smallest known 4–8B text model, then uses the existing
small-model fallback. This is a selection policy, not an accuracy guarantee.
"""
import json
import math
import re
import threading
import time
from collections import OrderedDict
from urllib.parse import urlsplit
from .usage import is_local_endpoint, is_cloud_model


class LocalModelError(RuntimeError):pass


AUTO_PREFERRED_MIN_PARAMETERS=4_000_000_000
AUTO_PREFERRED_MAX_PARAMETERS=8_000_000_000


_CAPABILITY_CACHE=OrderedDict()
_CAPABILITY_LOCK=threading.Lock()
_SEMVER=re.compile(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)'
                   r'(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?'
                   r'(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?')


def _semver(value):
    if not isinstance(value,str) or len(value)>128:return False
    match=_SEMVER.fullmatch(value)
    if match is None:return False
    prerelease=match[4]
    return not (prerelease and any(part.isdigit() and len(part)>1 and part.startswith('0')
                                  for part in prerelease.split('.')))


def _cached_capability(endpoint):
    if not _CAPABILITY_LOCK.acquire(timeout=.03):return None
    try:
        entry=_CAPABILITY_CACHE.get(endpoint)
        if entry is None:return None
        expires,known=entry
        if expires<=time.monotonic():
            del _CAPABILITY_CACHE[endpoint];return None
        _CAPABILITY_CACHE.move_to_end(endpoint)
        return known
    finally:_CAPABILITY_LOCK.release()


def _remember_capability(endpoint,known,cancel):
    if not _CAPABILITY_LOCK.acquire(timeout=.03):return
    try:
        _cancel(cancel)
        _CAPABILITY_CACHE[endpoint]=(time.monotonic()+(60 if known else 5),known)
        _CAPABILITY_CACHE.move_to_end(endpoint)
        while len(_CAPABILITY_CACHE)>32:_CAPABILITY_CACHE.popitem(last=False)
    finally:_CAPABILITY_LOCK.release()


def request_extensions(client,cfg,cancel=None):
    """Disable thinking only for an explicit or detected Ollama server.

    Probe the documented version route on loopback only. Failed optional
    detection leaves the generic request standard and does not mask errors
    from the actual model request. No user text, credentials or audio is sent.
    """
    _cancel(cancel)
    if cfg.get('ollama'):return {'reasoning_effort':'none'}
    if not is_local_endpoint(cfg.get('llm_url','')):return {}
    base=api_base(cfg)
    endpoint=(base[:-3] if base.endswith('/v1') else base)+'/api/version'
    known=_cached_capability(endpoint)
    if known is not None:
        _cancel(cancel)
        return {'reasoning_effort':'none'} if known else {}
    import httpx
    cacheable=False;known=False
    deadline=time.monotonic()+.8
    try:
        with client.stream('GET',endpoint,headers={'Authorization':'Bearer local'},
                           timeout=httpx.Timeout(.6,connect=.3,read=.3,write=.3,pool=.2),
                           follow_redirects=False) as response:
            _cancel(cancel)
            if response.status_code==200:
                body=bytearray()
                for chunk in response.iter_bytes():
                    _cancel(cancel)
                    if time.monotonic()>deadline or len(body)+len(chunk)>8192:return {}
                    body.extend(chunk)
                try:data=json.loads(body)
                except (ValueError,UnicodeError):data=None
                known=isinstance(data,dict) and _semver(data.get('version'))
                cacheable=True
            elif response.status_code in (404,405):cacheable=True
        _cancel(cancel)
    except httpx.HTTPError:
        _cancel(cancel)
        return {}
    if time.monotonic()>deadline:return {}
    if cacheable:_remember_capability(endpoint,known,cancel)
    _cancel(cancel)
    return {'reasoning_effort':'none'} if known else {}


def _cancel(cancel):
    if cancel is not None and cancel.is_set():raise InterruptedError()


def auto_enabled(cfg):
    """The legacy flag now enables Auto for either local compatible protocol."""
    return bool(cfg.get('ollama_auto') and (cfg.get('ollama') or is_local_endpoint(cfg.get('llm_url',''))))


def api_base(cfg):
    url=str(cfg.get('llm_url','')).strip().rstrip('/')
    try:parts=urlsplit(url)
    except ValueError:parts=None
    if (parts is None or parts.scheme not in ('http','https') or not parts.hostname
            or parts.username or parts.password or parts.query or parts.fragment):
        raise LocalModelError('Enter a valid model API URL without embedded credentials, a query, or a fragment.')
    if cfg.get('ollama') and not url.endswith('/v1'):url+='/v1'
    return url


def _name(item):
    return item.get('id') or item.get('name') or item.get('model')


def _eligible(item):
    if not isinstance(item,dict):return False
    name=_name(item)
    if not isinstance(name,str) or not name.strip():return False
    details=item.get('details')
    details=details if isinstance(details,dict) else {}
    identity=' '.join([name,str(details.get('family','')),str(item.get('type',''))]).lower()
    return not (item.get('remote_host') or item.get('remote_model') or is_cloud_model(name) or any(
        marker in identity for marker in ('cloud','embed','rerank','bert','clip')))


def _rank(item):
    """Prefer a modest rewriting model before the previous smallest fallback.

    Reported parameter counts and recognized B/M name tags are estimates, not
    proof of capability. File size and Qwen/name tie-breaks stay within that
    ordering; an allegedly loaded or tiny-file model cannot bypass the band.
    """
    details=item.get('details')
    details=details if isinstance(details,dict) else {}
    match=re.fullmatch(r'\s*([\d.]+)\s*([BM])\s*',str(details.get('parameter_size',item.get('parameter_size',''))),re.I)
    name=_name(item).strip()
    if match is None:
        match=re.search(r'(?:^|[-_: /])(\d+(?:\.\d+)?)([BM])(?=$|[-_: /])',name,re.I)
    params=math.inf
    if match:
        try:params=float(match[1])*(1e9 if match[2].upper()=='B' else 1e6)
        except ValueError:pass
        if not math.isfinite(params) or params<=0:params=math.inf
    size=item.get('size')
    size=size if type(size) is int and size>0 else math.inf
    preferred=AUTO_PREFERRED_MIN_PARAMETERS<=params<=AUTO_PREFERRED_MAX_PARAMETERS
    return 0 if preferred else 1,params,size,0 if re.search(r'(?:^|/)qwen',name,re.I) else 1,name.casefold(),name


def resolve_model(client,cfg,cancel=None):
    _cancel(cancel)
    explicit=str(cfg.get('llm_model','')).strip()
    if not auto_enabled(cfg):
        if not explicit:raise LocalModelError('Enter a text model name, or choose Auto for a local server.')
        if (cfg.get('ollama') or is_local_endpoint(cfg.get('llm_url',''))) and is_cloud_model(explicit):
            raise LocalModelError('Choose an installed local model. Cloud models are not used in local mode.')
        return explicit
    base=api_base(cfg)
    ollama=bool(cfg.get('ollama'))
    url=(base[:-3]+'/api/tags') if ollama else base+'/models'
    label='Ollama' if ollama else 'local model server'
    import httpx
    try:
        deadline=time.monotonic()+8
        # A saved external API key must never be forwarded to a local server.
        with client.stream('GET',url,headers={'Authorization':'Bearer local'},
                           timeout=httpx.Timeout(8,connect=3),follow_redirects=False) as response:
            if response.status_code!=200:raise LocalModelError(f'Could not list models from the {label}. Start the server and test again.')
            body=bytearray()
            for chunk in response.iter_bytes():
                _cancel(cancel)
                if time.monotonic()>deadline:raise LocalModelError('Listing local models timed out. Start the server and test again.')
                if len(body)+len(chunk)>1048576:raise LocalModelError('The local model list is too large. Choose a specific model.')
                body.extend(chunk)
        _cancel(cancel)
        try:data=json.loads(body)
        except (ValueError,UnicodeError):data={}
        models=data.get('models' if ollama else 'data') if isinstance(data,dict) else None
        if not isinstance(models,list):raise LocalModelError('The local server returned an invalid model list. Choose a specific model or test again.')
        eligible=[item for item in models if _eligible(item)]
        if not eligible:raise LocalModelError('No installed local text model was found. Install a model in your local server or choose a specific model.')
        return _name(min(eligible,key=_rank)).strip()
    except httpx.HTTPError:
        _cancel(cancel)
        raise LocalModelError('The local model server is unavailable. Start it and test again; no cloud fallback was used.') from None

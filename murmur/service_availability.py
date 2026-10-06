"""Startup availability probes: catalogs and files, never generation or audio."""
import httpx
import json
import time
from .storage import credential
from .usage import is_local_endpoint
from .cloud_asr import normalized_base


def probe(kind,cfg,client=None):
    if cfg.get('demo'):return 'off','Demo mode · no service request'
    try:
        if kind=='asr' and cfg.get('asr_backend')=='offline':
            from .offline import model_paths
            model_paths(cfg)
            return 'warning','Model files found · waiting for the recognizer to load'
        if kind=='asr' and cfg.get('asr_backend') in ('bailian','ali_nls'):
            from .service_checks import check_service
            result=check_service('asr',cfg)
            return ('active' if result['success'] else 'error'),result['summary']+' · No audio was sent'
        if kind=='asr':
            from .cloud_asr import KEY_SLOTS
            base=normalized_base(cfg.get('asr_http_url',''));model=cfg.get('asr_http_model','');slot=KEY_SLOTS[cfg['asr_backend']]
        else:
            prefix='llm' if kind=='llm' else 'ask_llm'
            base=normalized_base(cfg.get(prefix+'_url',''));model=cfg.get(prefix+'_model','');slot=prefix
        local=is_local_endpoint(base)
        # Never forward a cloud credential to a loopback/local server.
        key='local' if local else credential(slot)
        if not key:return 'off','API key missing · configure the service'
        def fetch(session):
            if kind=='llm' and local and cfg.get('ollama_auto'):
                from .local_llm import resolve_model
                selected=resolve_model(session,cfg)
                return 'active','Available · '+selected+' · Catalog check only'
            from .projecthub import is_projecthub,discover
            if is_projecthub(base):items,_=discover(session,base,key)
            else:
                deadline=time.monotonic()+8;body=bytearray()
                with session.stream('GET',base+'/models',headers={'Authorization':'Bearer '+key}) as response:
                    if response.status_code in (401,403):return 'error','Authentication rejected'
                    response.raise_for_status()
                    for chunk in response.iter_bytes():
                        if len(body)+len(chunk)>1048576 or time.monotonic()>deadline:raise ValueError('Catalog limit')
                        body.extend(chunk)
                data=json.loads(body);items=data.get('data',[]) if isinstance(data,dict) else []
            ids={item.get('id') for item in items if isinstance(item,dict)}
            if model in ids:return 'active','Available · model listed · No generation or audio test'
            return 'warning','Server reached · model not listed; availability is unconfirmed'
        if client is not None:return fetch(client)
        with httpx.Client(timeout=5.,follow_redirects=False) as session:return fetch(session)
    except Exception:
        return 'error','Unavailable · open Settings to check configuration'

"""API-reported LLM usage and explicit USD tariff calculations.

No tokenization, text-length estimates, balances, or credentials are retained.
DeepSeek tariff checked 2026-10-04 against its current official pricing page.
Cost is a tariff estimate, not an invoice or account-balance deduction.
"""
import copy
import ipaddress
import math
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

DEEPSEEK_PRICING_SOURCE = 'https://api-docs.deepseek.com/quick_start/pricing/'
DEEPSEEK_PRICING_ASOF = '2026-10-04'
PRICE_KEYS = ('llm_input_price_per_million', 'llm_output_price_per_million', 'llm_cache_price_per_million')
# Cache-miss input / output / cache-hit input, USD per million tokens.
_DEEPSEEK_OFFPEAK = {
    'deepseek-flash': ('0.15', '0.6', '0.003'),
    'deepseek-v4-flash': ('0.15', '0.6', '0.003'),
    'deepseek-v4-flash-vision-exp': ('0.15', '0.6', '0.003'),
    'deepseek-v4-pro': ('0.66', '1.98', '0.022'),
}


class UsageText(str):
    def __new__(cls, value, usage=None):
        obj = super().__new__(cls, value)
        obj.usage = copy.deepcopy(usage) if usage is not None else None
        return obj


def is_local_endpoint(url):
    """Loopback only; remote Ollama is external even if cfg.ollama is true."""
    try:
        host = (urlsplit(url).hostname or '').lower().rstrip('.')
        if host == 'localhost':return True
        return ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):return False


def is_cloud_model(model):
    """Known cloud tags stay external even behind a loopback model gateway."""
    return isinstance(model,str) and 'cloud' in model.casefold()


def _context(cfg):
    local = is_local_endpoint(cfg.get('llm_url', ''))
    try:host = (urlsplit(cfg.get('llm_url', '')).hostname or '').lower()
    except (ValueError, TypeError):host = ''
    provider = 'ollama' if cfg.get('ollama') else 'deepseek' if host == 'api.deepseek.com' else 'openai_compatible'
    return provider, local


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _rate(value):
    if value is None or value == '' or isinstance(value, bool):return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result >= 0 and math.isfinite(float(result)) else None
    except (InvalidOperation, TypeError, ValueError):return None


def _pricing(cfg, metadata, response):
    if metadata['local']:
        return None, 'local', None, None
    raw = [cfg.get(key) for key in PRICE_KEYS]
    if any(value is not None and value != '' for value in raw):
        rates = tuple(_rate(value) for value in raw)
        if rates[0] is None or rates[1] is None or (raw[2] not in (None, '') and rates[2] is None):
            return None, 'invalid_override', 'user_configured', None
        return rates, 'configured', 'user_configured', None
    model = metadata['model']
    if metadata['provider'] != 'deepseek':
        return None, 'unknown', None, None
    if model not in _DEEPSEEK_OFFPEAK:
        return None, 'unknown', DEEPSEEK_PRICING_SOURCE, DEEPSEEK_PRICING_ASOF
    # Creation time must come from the API. Weekday peak hours depend also on
    # Chinese public holidays, which this application cannot certify offline.
    created = response.get('created')
    if type(created) is not int:
        return None, 'time_missing', DEEPSEEK_PRICING_SOURCE, DEEPSEEK_PRICING_ASOF
    try:moment = datetime.fromtimestamp(created, timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None, 'time_missing', DEEPSEEK_PRICING_SOURCE, DEEPSEEK_PRICING_ASOF
    if moment.weekday() < 5 and (1 <= moment.hour < 4 or 6 <= moment.hour < 10):
        return None, 'schedule_unknown', DEEPSEEK_PRICING_SOURCE, DEEPSEEK_PRICING_ASOF
    return tuple(Decimal(value) for value in _DEEPSEEK_OFFPEAK[model]), 'official_offpeak', DEEPSEEK_PRICING_SOURCE, DEEPSEEK_PRICING_ASOF


def usage_metadata(response, cfg, request_id=None):
    """Keep counts only when actually supplied as valid integers by the API."""
    response = response if isinstance(response, dict) else {}
    provider, local = _context(cfg)
    model = response.get('model')
    model = model if isinstance(model, str) and model else cfg.get('llm_model', '')
    if is_cloud_model(model) or response.get('remote_host') or response.get('remote_model'):
        local=False
    usage = response.get('usage')
    usage = usage if isinstance(usage, dict) else {}
    if not usage and cfg.get('ollama') and ('prompt_eval_count' in response or 'eval_count' in response):
        usage = {'prompt_tokens':response.get('prompt_eval_count'), 'completion_tokens':response.get('eval_count')}
    values = {
        'input_tokens': usage.get('prompt_tokens', usage.get('input_tokens')),
        'output_tokens': usage.get('completion_tokens', usage.get('output_tokens')),
        'total_tokens': usage.get('total_tokens'),
    }
    details = usage.get('prompt_tokens_details', usage.get('input_tokens_details'))
    details = details if isinstance(details, dict) else {}
    cached = usage.get('prompt_cache_hit_tokens', details.get('cached_tokens'))
    values['cached_input_tokens'] = cached
    counts = {name:_count(value) for name,value in values.items()}
    invalid = any(value is not None and counts[name] is None for name,value in values.items())
    inp, out, total, hit = (counts[name] for name in ('input_tokens', 'output_tokens', 'total_tokens', 'cached_input_tokens'))
    if hit is not None and inp is not None and hit > inp:
        counts['cached_input_tokens'] = None;invalid = True
    if cached is not None and details.get('cached_tokens') is not None and cached != details['cached_tokens']:
        counts['cached_input_tokens'] = None;invalid = True
    miss = usage.get('prompt_cache_miss_tokens')
    if miss is not None and (_count(miss) is None or (inp is not None and hit is not None and miss + hit != inp)):
        invalid = True
    if inp is not None and out is not None and total is not None and inp + out != total:
        counts['total_tokens'] = None;invalid = True
    status = 'invalid' if invalid else 'reported' if inp is not None and out is not None else 'partial' if any(value is not None for value in counts.values()) else 'missing'
    metadata = {
        'request_id': request_id or uuid.uuid4().hex,
        'provider': provider, 'model': model, 'local': local, 'external': not local,
        **counts, 'status': status,
        'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'currency':'USD', 'cost_usd':None, 'cost':None,
    }
    rates, pricing_status, source, asof = _pricing(cfg, metadata, response)
    metadata.update(pricing_status=pricing_status, pricing_source=source, pricing_asof=asof)
    if local:
        metadata['cost_usd'] = metadata['cost'] = 0.0
    elif rates and inp is not None and out is not None and not invalid:
        input_rate, output_rate, cache_rate = rates
        hit = counts['cached_input_tokens']
        if cache_rate is None or cache_rate == input_rate:
            amount = inp * input_rate + out * output_rate
        elif hit is not None or inp == 0:
            hit = hit or 0
            amount = (inp - hit) * input_rate + hit * cache_rate + out * output_rate
        else:
            amount = None;metadata['pricing_status'] = 'cache_missing'
        if amount is not None:
            cost = float(amount / Decimal(1000000))
            if math.isfinite(cost):metadata['cost_usd'] = metadata['cost'] = cost
    elif rates:
        metadata['pricing_status'] = 'usage_missing' if not invalid else 'usage_invalid'
    if rates:
        metadata['rates_per_million'] = {key:float(rate) if rate is not None else None
                                        for key,rate in zip(('input', 'output', 'cache'), rates)}
    return metadata


def publish_usage(response, cfg, usage_sink=None):
    metadata = usage_metadata(response, cfg)
    if usage_sink is not None:
        try:usage_sink(copy.deepcopy(metadata))
        except Exception:pass
    return metadata


def no_call_text(value, cfg):
    metadata = usage_metadata({}, cfg)
    metadata.update(request_id=None, status='not_called', cost_usd=None, cost=None,
                    pricing_status='not_applicable', pricing_source=None, pricing_asof=None)
    return UsageText(value, metadata)

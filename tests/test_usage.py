"""Reported token counts and tariff arithmetic; never infer from text size."""
import copy
import json
import threading
from datetime import datetime, timezone

import httpx
import pytest
from murmur import providers, service_checks
from murmur.storage import DEFAULTS
from murmur.usage import UsageText, usage_metadata, is_local_endpoint

REAL_HTTP_CLIENT = httpx.Client


def cfg(**values):
    result = copy.deepcopy(DEFAULTS)
    result.update(demo=False, ollama=False,ollama_auto=False,llm_url='https://api.deepseek.com/v1', llm_model='deepseek-chat')
    result.update(values)
    return result


def response(usage=None, model='deepseek-chat', text='Result'):
    result = {'model':model, 'choices':[{'message':{'content':text}}]}
    if usage is not None:result['usage'] = usage
    return result


def counts(**values):
    result = {'prompt_tokens':1000, 'completion_tokens':200, 'total_tokens':1200,
              'prompt_cache_hit_tokens':400, 'prompt_cache_miss_tokens':600}
    result.update(values)
    return result


@pytest.mark.parametrize('url,local', [('http://localhost:11434',True),
    ('http://127.0.0.1:11434/v1',True), ('http://127.1.2.3',True),
    ('http://[::1]:11434',True), ('http://LOCALHOST./v1',True),
    ('http://192.168.1.5:11434',False), ('https://api.deepseek.com',False),
    ('http://localhost.evil.test',False), ('not a URL',False)])
def test_loopback_endpoint_classification(url,local):
    assert is_local_endpoint(url) is local


def test_reported_deepseek_cache_cost_with_explicit_rates():
    usage = usage_metadata(response(counts()),cfg(llm_input_price_per_million=2,
        llm_output_price_per_million=4,llm_cache_price_per_million=.5))
    assert usage['input_tokens']==1000 and usage['output_tokens']==200
    assert usage['cached_input_tokens']==400 and usage['total_tokens']==1200
    assert usage['cost_usd']==pytest.approx((600*2 + 400*.5 + 200*4)/1e6)
    assert usage['status']=='reported' and usage['pricing_source']=='user_configured'
    assert usage['currency']=='USD' and usage['cost']==usage['cost_usd']


def test_missing_usage_is_unknown_even_if_response_text_is_large():
    usage = usage_metadata(response(text='x'*10000), cfg())
    assert all(usage[name] is None for name in ('input_tokens','output_tokens','cached_input_tokens','total_tokens','cost_usd'))
    assert usage['status']=='missing'


def test_partial_fields_are_not_inferred_from_totals_or_missing_cache():
    usage = usage_metadata(response({'total_tokens':200}),cfg())
    assert usage['input_tokens'] is None and usage['output_tokens'] is None and usage['total_tokens']==200
    assert usage['status']=='partial' and usage['cost_usd'] is None
    usage = usage_metadata(response({'prompt_tokens':5,'completion_tokens':3}),cfg())
    assert usage['total_tokens'] is None and usage['cached_input_tokens'] is None


@pytest.mark.parametrize('override', [True,-1,float('nan'),float('inf'),'bad','1e999'])
def test_invalid_rates_never_create_cost(override):
    usage = usage_metadata(response(counts()),cfg(llm_input_price_per_million=override,llm_output_price_per_million=1))
    assert usage['cost_usd'] is None and usage['pricing_status']=='invalid_override'


@pytest.mark.parametrize('data', [counts(prompt_tokens=-1),counts(completion_tokens=True),
    counts(total_tokens=1200.5),counts(prompt_cache_hit_tokens=1100),counts(prompt_cache_miss_tokens=700)])
def test_invalid_or_inconsistent_api_usage_cannot_be_priced(data):
    usage = usage_metadata(response(data),cfg(llm_input_price_per_million=2,llm_output_price_per_million=4))
    assert usage['status']=='invalid' and usage['cost_usd'] is None


def test_cached_tokens_standard_and_responses_api_fields():
    usage = usage_metadata(response({'input_tokens':10,'output_tokens':2,'total_tokens':12,
        'input_tokens_details':{'cached_tokens':3}}),cfg())
    assert (usage['input_tokens'],usage['output_tokens'],usage['cached_input_tokens'],usage['total_tokens'])==(10,2,3,12)
    conflict = counts();conflict['prompt_tokens_details']={'cached_tokens':300}
    usage = usage_metadata(response(conflict),cfg())
    assert usage['cached_input_tokens'] is None and usage['status']=='invalid'


def test_local_and_remote_ollama_never_share_external_fee_classification():
    data = response({'prompt_tokens':15,'completion_tokens':6,'total_tokens':21},model='qwen3.5:2b')
    local = usage_metadata(data,cfg(ollama=True,llm_url='http://127.0.0.1:11434'))
    assert local['provider']=='ollama' and local['local'] and local['cost_usd']==0
    remote = usage_metadata(data,cfg(ollama=True,llm_url='http://192.168.1.2:11434'))
    assert remote['external'] and not remote['local'] and remote['cost_usd'] is None
    assert remote['pricing_status']=='unknown'
    missing = usage_metadata({},cfg(ollama=True,llm_url='http://localhost:11434'))
    assert missing['cost_usd']==0 and missing['total_tokens'] is None and missing['status']=='missing'
    native = usage_metadata({'prompt_eval_count':15,'eval_count':6},cfg(ollama=True,llm_url='http://localhost'))
    assert native['input_tokens']==15 and native['output_tokens']==6 and native['total_tokens'] is None


def test_zero_tariff_and_flat_input_tariff_do_not_require_cache_count():
    data = response({'prompt_tokens':100,'completion_tokens':10,'total_tokens':110})
    usage = usage_metadata(data,cfg(llm_input_price_per_million=0,llm_output_price_per_million=0))
    assert usage['cost_usd']==0 and usage['cached_input_tokens'] is None
    usage = usage_metadata(data,cfg(llm_input_price_per_million=2,llm_output_price_per_million=3))
    assert usage['cost_usd']==pytest.approx(.00023)


def test_current_official_pricing_uses_api_model_and_api_creation_time():
    data = response(counts(),model='deepseek-flash')
    data['created']=int(datetime(2026,10,4,3,0,tzinfo=timezone.utc).timestamp())
    usage = usage_metadata(data,cfg())
    assert usage['model']=='deepseek-flash' and usage['pricing_status']=='official_offpeak'
    assert usage['cost_usd']==pytest.approx((600*.15+400*.003+200*.6)/1e6)
    assert usage['pricing_asof']=='2026-10-04' and 'api-docs.deepseek.com' in usage['pricing_source']
    assert usage_metadata(response(counts(),model='deepseek-chat'),cfg())['cost_usd'] is None
    data['created']=int(datetime(2026,10,5,3,0,tzinfo=timezone.utc).timestamp())
    usage = usage_metadata(data,cfg())
    assert usage['cost_usd'] is None and usage['pricing_status']=='schedule_unknown'
    data.pop('created')
    assert usage_metadata(data,cfg())['pricing_status']=='time_missing'


def install_http(monkeypatch,body,cancel=None):
    def handler(request):
        if cancel is not None:cancel.set()
        return httpx.Response(200,json=body)
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:REAL_HTTP_CLIENT(transport=httpx.MockTransport(handler),**kwargs))
    monkeypatch.setattr(providers,'credential',lambda name:'fixture-key')
    monkeypatch.setattr(service_checks,'credential',lambda name:'fixture-key')


def test_transform_usage_text_is_string_compatible_and_sink_is_same_request(monkeypatch):
    install_http(monkeypatch,response(counts()));seen=[]
    text=providers.transform('Fixture','听写',cfg(),usage_sink=seen.append)
    assert isinstance(text,str) and isinstance(text,UsageText) and text=='Result'
    assert len(seen)==1 and seen[0]==text.usage and seen[0]['request_id']
    assert 'Fixture' not in json.dumps(text.usage) and 'fixture-key' not in json.dumps(text.usage)
    other=providers.transform('Fixture','听写',cfg())
    assert other.usage['request_id']!=text.usage['request_id']


def test_sink_error_does_not_break_text_and_no_call_has_no_sink(monkeypatch):
    install_http(monkeypatch,response(counts()))
    def fail(metadata):raise RuntimeError('fixture storage failure')
    assert providers.transform('Fixture','听写',cfg(),usage_sink=fail)=='Result'
    seen=[];text=providers.transform('Fixture','听写',cfg(polish=False),usage_sink=seen.append)
    assert isinstance(text,UsageText) and text.usage['status']=='not_called' and seen==[]


@pytest.mark.parametrize('check_usage', [None, counts()])
def test_cancel_after_complete_response_preserves_only_real_usage(monkeypatch, check_usage):
    token=threading.Event();seen=[];install_http(monkeypatch,response(counts()),token)
    with pytest.raises(InterruptedError):providers.transform('Fixture','听写',cfg(),cancel=token,usage_sink=seen.append)
    assert len(seen)==1 and seen[0]['total_tokens']==1200
    token.clear();seen.clear();install_http(monkeypatch,response(check_usage),token)
    result=service_checks.check_service('llm',cfg(),cancel=token,usage_sink=seen.append)
    assert not result['success'] and result['summary']=='Cancelled'
    assert len(seen)==1 and seen[0]['status']==('reported' if check_usage else 'missing')
    assert seen[0]['total_tokens']==(1200 if check_usage else None)
    assert result['usage']['request_id']==seen[0]['request_id']


def test_llm_service_check_returns_usage_and_usage_of_empty_result(monkeypatch):
    seen=[];install_http(monkeypatch,response(counts()))
    result=service_checks.check_service('llm',cfg(),usage_sink=seen.append)
    assert result['success'] and result['usage']==seen[0]
    seen.clear();install_http(monkeypatch,response(counts(),text=''))
    result=service_checks.check_service('llm',cfg(),usage_sink=seen.append)
    assert not result['success'] and result['usage']==seen[0] and seen[0]['total_tokens']==1200


def test_service_usage_sink_cannot_mutate_result_or_break_response(monkeypatch):
    install_http(monkeypatch,response(counts()))
    def mutate(metadata):
        metadata['input_tokens']=9999
        metadata['rates_per_million']['input']=9999
        raise RuntimeError('fixture sink failure')
    result=service_checks.check_service('llm',cfg(llm_input_price_per_million=2,
        llm_output_price_per_million=4),usage_sink=mutate)
    assert result['success'] and result['usage']['input_tokens']==1000
    assert result['usage']['rates_per_million']['input']==2

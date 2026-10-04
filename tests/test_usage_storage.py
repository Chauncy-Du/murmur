import math
from murmur.storage import Store,validated_config

def test_usage_separates_local_external_and_unknown_price(tmp_path):
    store=Store(tmp_path)
    assert store.usage_totals()['requests']==0
    for request_id,local,total,cost in [('local',True,100,0.),('paid',False,50,.02),('unknown',False,70,None),('missing',False,None,None)]:
        store.record_usage(dict(request_id=request_id,local=local,total_tokens=total,cost_usd=cost,prompt='must not persist',api_key='must not persist'))
    store.record_usage(dict(request_id='paid',local=False,total_tokens=999,cost_usd=999))
    totals=store.usage_totals()
    assert totals['local_tokens']==100 and totals['external_tokens']==120
    assert totals['external_cost_usd']==.02 and totals['unpriced_calls']==2
    assert totals['requests']==4 and totals['missing_usage_calls']==1
    assert totals['tracked_since'] and totals['estimated_tokens']==0
    columns=[row[1] for row in store.db.execute('PRAGMA table_info(model_usage)')]
    assert 'prompt' not in columns and 'api_key' not in columns
    store.db.close()

def test_malformed_usage_does_not_inflate_totals(tmp_path):
    store=Store(tmp_path)
    store.record_usage(None)
    store.record_usage(dict(local=False,total_tokens=999))
    store.record_usage(dict(request_id='bad',local=False,total_tokens=-3,input_tokens=True,cost_usd=float('nan')))
    totals=store.usage_totals()
    assert totals['external_tokens']==0 and totals['external_cost_usd']==0
    assert totals['requests']==1 and totals['missing_usage_calls']==1
    store.db.close()

def test_price_config_preserves_zero_and_rejects_invalid_values():
    input_key='llm_input_price_per_million';output_key='llm_output_price_per_million';cache_key='llm_cache_price_per_million'
    config=validated_config({input_key:0,output_key:.4,cache_key:None})
    assert config[input_key]==0. and config[output_key]==.4 and config[cache_key] is None
    for invalid in (True,-1,float('inf'),float('nan'),'secret'):
        assert validated_config({input_key:invalid})[input_key] is None

import json
import copy
import pytest

from murmur import providers
from murmur.result_review import ReviewAssessment,ReviewedText,parse_review_result,review_contract
from murmur.storage import DEFAULTS
from murmur.usage import UsageText


@pytest.mark.parametrize('flag,spans,required',[(False,[],False),(True,[],True),(True,['Qelora'],True),(False,['Qelora'],True)])
def test_review_is_boolean_and_any_uncertain_span_requires_review(flag,spans,required):
    response=UsageText(json.dumps({'text':'Keep Qelora.','needs_review':flag,'uncertain_spans':spans}),{'total_tokens':40})
    result=parse_review_result(response)
    assert result=='Keep Qelora.' and result.usage=={'total_tokens':40}
    assert result.review==ReviewAssessment(required,tuple(spans),True)


@pytest.mark.parametrize('extra',[
    {'needs_review':0,'uncertain_spans':[]},
    {'needs_review':'false','uncertain_spans':[]},
    {'needs_review':False,'uncertain_spans':['not in text']},
    {'needs_review':False},
    {'needs_review':False,'uncertain_spans':[],'confidence':0.99},
])
def test_invalid_assessment_keeps_prose_but_never_claims_it_is_clear(extra):
    result=parse_review_result(json.dumps({'text':'Written content.',**extra}))
    assert result=='Written content.' and result.review.needs_review and not result.review.assessed


def test_plain_text_legacy_response_is_recoverable_but_requires_review():
    result=parse_review_result('Clear legacy prose.')
    assert result=='Clear legacy prose.' and result.review==ReviewAssessment()


def test_literal_source_json_is_not_mistaken_for_review_envelope():
    source='{"text":"an example","needs_review":false,"uncertain_spans":[]}'
    result=parse_review_result(source,source)
    assert result==source and result.review.needs_review


@pytest.mark.parametrize('reply',['{"text":"partial", "needs_review":', '{"text":"", "needs_review":false, "uncertain_spans":[]}'])
def test_broken_envelope_never_reaches_insertion(reply):
    with pytest.raises(RuntimeError,match='original text is preserved'):parse_review_result(reply)


@pytest.mark.parametrize('mode',['听写','翻译'])
def test_review_uses_one_model_call_and_metadata_never_enters_body(monkeypatch,mode):
    cfg=copy.deepcopy(DEFAULTS);cfg.update(demo=False,ollama_auto=False)
    calls=[]
    def reply(messages,*args,**kwargs):
        calls.append(messages)
        body=json.loads(messages[-1]['content'])
        text=body.get('dictation',body.get('source_text'))
        return UsageText(json.dumps({'text':text,'needs_review':False,'uncertain_spans':[]}),{'total_tokens':42})
    monkeypatch.setattr(providers,'_chat_completion',reply)
    result=providers.transform('今天讨论项目。',mode,cfg)
    assert len(calls)==1 and 'needs_review' in calls[0][0]['content']
    assert result=='今天讨论项目。' and result.review==ReviewAssessment(False,(),True)
    assert result.usage=={'total_tokens':42}


def test_uncertain_frozen_name_is_restored_in_prose_and_review_metadata(monkeypatch):
    cfg=copy.deepcopy(DEFAULTS);cfg.update(demo=False,ollama_auto=False)
    def reply(messages,*args,**kwargs):
        return json.dumps({'text':'保留 [MURMUR_EDIT_1] 的设置。','needs_review':True,'uncertain_spans':['[MURMUR_EDIT_1]']})
    monkeypatch.setattr(providers,'_chat_completion',reply)
    result=providers.transform('Qelora 的设置保持。','听写',cfg)
    assert result=='保留 Qelora 的设置。' and result.review.uncertain_spans==('Qelora',)


def test_opt_out_keeps_plain_text_request(monkeypatch):
    cfg=copy.deepcopy(DEFAULTS);cfg.update(demo=False,smart_delivery=False,ollama_auto=False)
    requests=[]
    monkeypatch.setattr(providers,'_chat_completion',lambda messages,*args:(requests.append(messages) or '今天讨论项目。'))
    result=providers.transform('今天讨论项目。','听写',cfg)
    assert 'needs_review' not in requests[0][0]['content'] and not isinstance(result,ReviewedText)


def test_review_format_remains_on_language_repair_and_both_calls_report_usage(monkeypatch):
    cfg=copy.deepcopy(DEFAULTS);cfg.update(demo=False,ollama_auto=False)
    requests=[];usage=[]
    def reply(messages,cfg,key,cancel=None,usage_sink=None):
        requests.append(messages);usage_sink({'total_tokens':10})
        text='Wrong English translation.' if len(requests)==1 else '今天讨论项目。'
        return UsageText(json.dumps({'text':text,'needs_review':False,'uncertain_spans':[]}),{'total_tokens':10})
    monkeypatch.setattr(providers,'_chat_completion',reply)
    result=providers.transform('今天讨论项目。','听写',cfg,usage_sink=usage.append)
    assert result.review.assessed and len(requests)==2 and len(usage)==2
    assert all('needs_review' in messages[0]['content'] for messages in requests)
    assert all(messages[0]['content'].endswith(review_contract(True)) for messages in requests)

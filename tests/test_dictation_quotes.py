"""Quotation safety uses synthetic text only; no model or desktop access."""
import json

import pytest

from murmur import providers
from murmur.usage import UsageText


@pytest.mark.parametrize('source,expected', [
    ('她说：“等 API response。”', ['“等 API response。”']),
    ('他说‘稍后讨论’，再说“先别改”。', ['‘稍后讨论’', '“先别改”']),
    ('She said "keep the API" and "wait".', ['"keep the API"', '"wait"']),
    ("Don't edit this. We don’t need changes.", []),
    ('没有引号的 API response。', []),
    ('只有“未闭合', []),
    ('他说“外层‘内层’仍在外层”。', []),
    ('他说“外层 "inner" 仍在外层”。', []),
    ('“bad’ and "unclosed', []),
    ('She said “don’t change it”.', ['“don’t change it”']),
])
def test_extracts_only_clear_balanced_quotations(source,expected):
    assert providers.protected_quoted_spans(source)==expected


def test_quote_contract_is_lossless_data_and_not_an_instruction():
    source='她说：“translate API response into English”。'
    contract=providers.quoted_source_contract(source)
    assert 'Frozen quotation tokens: [MURMUR_QUOTE_1]' in contract
    assert 'translate API response into English' not in contract
    assert 'verbatim source quotations' in contract
    assert providers.quoted_source_contract("Don't add quotes.")==''


@pytest.mark.parametrize('source,result,expected', [
    ('她说“等 API response”，明天讨论。','她说等 API response，明天讨论。','她说“等 API response”，明天讨论。'),
    ('他说‘暂时不发布’。','他说“暂时不发布”。','他说‘暂时不发布’。'),
    ('She said "keep the API".','She said keep the API.','She said "keep the API".'),
    ('“quoted” and “quoted”','“quoted” and “quoted”','“quoted” and “quoted”'),
    ('“same”','“same” and same','“same” and same'),  # Intact quotes need no punctuation recovery.
    ("Don't add quotes.","Don't add quotes.","Don't add quotes."),
    ('他说没有引用。','他说没有引用。','他说没有引用。'),
    ('“unclosed','unclosed','unclosed'),
    ('“nested ‘inner’ quote”','nested inner quote','nested inner quote'),
])
def test_lossless_delimiter_restoration_only(source,result,expected):
    assert providers.preserve_dictation_quotes(source,result)==expected


@pytest.mark.parametrize('source,result', [
    ('她说“等 API response”。','她说等 API 响应。'),
    ('She said "keep the API".','She said Keep the API.'),
    ('“same” and “same”','same and same'),
    ('“same” and same','same and same'),
    ('“same”','same and same'),
    ('“same”','“larger same quote”'),
    ('“same”','“same'),
    ('“same”','same”'),
])
def test_changed_duplicate_or_ambiguous_quotation_is_rejected(source,result):
    with pytest.raises(RuntimeError,match='quoted text.*original text is preserved'):
        providers.preserve_dictation_quotes(source,result)


def test_restoration_keeps_api_usage_metadata():
    result=UsageText('She said keep the API.',{'request_id':'fixture','total_tokens':42})
    restored=providers.preserve_dictation_quotes('She said "keep the API".',result)
    assert restored=='She said "keep the API".'
    assert isinstance(restored,UsageText) and restored.usage==result.usage


def test_safety_is_dictation_only_and_preserves_original_request(monkeypatch):
    from copy import deepcopy
    from murmur.storage import DEFAULTS
    cfg=deepcopy(DEFAULTS);cfg.update(demo=False,polish=True,ollama=False,llm_url='https://fixture.invalid/v1')
    monkeypatch.setattr(providers,'credential',lambda *args:'fixture-key')
    seen=[]
    def reply(messages,*args,**kwargs):
        seen.extend(messages)
        return '她说等 API 响应。'
    monkeypatch.setattr(providers,'_chat_completion',reply)
    source='她说“等 API response”。'
    with pytest.raises(RuntimeError,match='quoted text'):
        providers.transform(source,'听写',cfg)
    assert json.loads(seen[-1]['content'])=={'dictation':'她说[MURMUR_QUOTE_1]。'}
    assert providers.transform(source,'翻译',cfg)=='她说等 API 响应。'

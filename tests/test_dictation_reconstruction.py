"""Synthetic scope, transport and preservation checks; live quality is separate."""
import copy
import json
import threading

import pytest

from murmur import providers
from murmur.dictation_terms import mixed_term_plan
from murmur.prompt_messages import prepare_dictation_messages
from murmur.storage import DEFAULTS
from murmur.usage import UsageText


FRAGMENTED = (
    '呃，页边距保持。上面那段。标题简短一点。不对。下面那段。上面保持原样。'
    '我希望。就是。读者能看到进度略有加快。但提升不大。不要写成大幅提升。'
    '现在说明太短。上一版太啰嗦。在两版之间取折中。说明要完整。'
    '每页格式。现在不同。统一一下。这样便于比较。预算可能还要改。保留这点。'
    '另外。正文的内容都要保留。不要删掉要求。不要遗漏开头的要求。'
)


@pytest.mark.parametrize('prefix,bank', [('', 'zh'), ('保留 DataForge 的名字。', 'mixed')])
def test_fragmented_request_gets_reconstruction_example_without_changing_source(prefix, bank):
    source=prefix+FRAGMENTED
    prepared=prepare_dictation_messages('',source)
    assert prepared.metadata['example_ids'][0]==bank+'-reconstruction'
    assert prepared.metadata['example_count']<=2
    assert prepared.source==source
    assert prepared.restore(json.loads(prepared.messages[-1]['content'])['dictation'])==source
    assert [message['role'] for message in prepared.messages]==['system','user']
    sample=prepared.examples[0].result
    assert '\n\n' in sample and '页边距保持' in sample and '我希望' in sample
    assert '提升不大' in sample and '预算可能' in sample and '当前版本' in sample and '上一版' in sample


def test_fragmented_internal_instruction_keeps_operation_protection_first():
    prepared=prepare_dictation_messages('','请翻译这段话。'+FRAGMENTED)
    assert prepared.metadata['example_ids']==('zh-instruction','zh-reconstruction')


def test_long_quotation_does_not_trigger_reconstruction_of_quoted_fragments():
    prepared=prepare_dictation_messages('','她说“'+FRAGMENTED+'”。')
    assert 'reconstruction' not in prepared.risks
    assert prepared.restore(json.loads(prepared.messages[-1]['content'])['dictation'])=='她说“'+FRAGMENTED+'”。'


def test_long_english_fragmented_request_uses_english_reconstruction():
    source=('Um. The top section. Sorry. The bottom one. Keep the top unchanged. '
            'I want. Well. Readers to see progress is slightly faster. But not much. '
            'Keep that qualification. The budget might change. Keep that too. '
            'The current explanation is too short. The old one too wordy. Somewhere between them.')
    prepared=prepare_dictation_messages('',source)
    assert prepared.metadata['example_ids'][0]=='en-reconstruction'
    assert not providers._HAN.search(''.join(m['content'] for m in prepared.messages))


def test_unfamiliar_named_modifier_is_frozen_but_english_prose_remains_editable():
    source='保持 Qelora 的选项；他说 I am going to review the report，稍后讨论。'
    assert mixed_term_plan(source).required==('Qelora',)
    prepared=prepare_dictation_messages('',source)
    assert prepared.metadata['frozen_term_count']==1
    encoded=json.loads(prepared.messages[-1]['content'])['dictation']
    assert 'Qelora' not in encoded
    assert prepared.restore(encoded)==source


def config():
    cfg=copy.deepcopy(DEFAULTS)
    cfg.update(demo=False,polish=True,ollama_auto=False,llm_model='fixture')
    return cfg


def test_language_repair_reuses_frozen_source_and_reports_both_calls(monkeypatch):
    source='嗯，我希望保留 Qelora 的设置。'
    messages=[];usage=[]
    def response(request,cfg,key,cancel=None,usage_sink=None):
        messages.append(request)
        usage_sink({'total_tokens':10})
        return UsageText('Keep [MURMUR_EDIT_1] settings.' if len(messages)==1 else json.loads(request[-1]['content'])['dictation'],{'total_tokens':10})
    monkeypatch.setattr(providers,'_chat_completion',response)
    result=providers.transform(source,'听写',config(),usage_sink=usage.append)
    assert result==source and result.usage=={'total_tokens':10}
    assert len(messages)==2 and usage==[{'total_tokens':10}]*2
    assert messages[0][-1]==messages[1][-1]
    assert '只输出完整的整理正文。' in messages[1][0]['content']
    from murmur.result_review import review_contract
    assert messages[1][0]['content'].endswith(review_contract(True))
    assert 'Keep [MURMUR_EDIT_1] settings.' not in messages[1][0]['content']


def test_cancel_after_wrong_language_prevents_second_call(monkeypatch):
    cancel=threading.Event();calls=[]
    def response(*args):
        calls.append(args);cancel.set();return 'An English translation.'
    monkeypatch.setattr(providers,'_chat_completion',response)
    with pytest.raises(InterruptedError):providers.transform('这是中文。','听写',config(),cancel=cancel)
    assert len(calls)==1


def test_repair_still_checks_content_fidelity(monkeypatch):
    calls=[]
    def response(*args):
        calls.append(args)
        return 'Keep [MURMUR_EDIT_1] settings.' if len(calls)==1 else '保持设置。'
    monkeypatch.setattr(providers,'_chat_completion',response)
    with pytest.raises(RuntimeError,match='protected terms|frozen'):
        providers.transform('保持 API 设置。','听写',config())
    assert len(calls)==2


def test_transport_failure_is_never_automatically_replaced(monkeypatch):
    calls=[]
    def response(*args):
        calls.append(args);raise RuntimeError('Saved gateway task is still processing.')
    monkeypatch.setattr(providers,'_chat_completion',response)
    with pytest.raises(RuntimeError,match='still processing'):
        providers.transform('这是中文。','听写',config())
    assert len(calls)==1


def test_short_requests_are_advisory_source_fragments_not_frozen_prose():
    contract=providers.dictation_source_contract('页边距保持。说明要完整。她说“标题不要改”。')
    data=json.JSONDecoder().raw_decode(contract.split(': ',1)[1])[0]
    assert data['short_request_fragments']==['页边距保持']
    assert 'unless explicitly superseded' in contract
    assert 'not verbatim output' in contract


def test_uncompleted_or_inline_corrected_request_is_not_anchored():
    for source in ('标题保持，不对，缩短标题。','应力保持跟上一版一致。','保留页边距。'):
        assert 'short_request_fragments' not in providers.dictation_source_contract(source)


def test_language_repair_is_bounded_to_two_completed_responses(monkeypatch):
    calls=[]
    def response(*args):
        calls.append(args);return 'An English translation.'
    monkeypatch.setattr(providers,'_chat_completion',response)
    with pytest.raises(RuntimeError,match='changed the dictation language'):
        providers.transform('这是中文。','听写',config())
    assert len(calls)==2


def test_chinese_request_has_explicit_frozen_id_guidance():
    prepared=prepare_dictation_messages('','Qelora 的设置保持。')
    assert '编辑标记 [MURMUR_EDIT_1] 各保留一次' in prepared.system_prompt
    assert '不能自行填入源约束列出的名称' in prepared.system_prompt
    assert json.loads(prepared.messages[-1]['content'])['dictation']=='[MURMUR_EDIT_1] 的设置保持。'

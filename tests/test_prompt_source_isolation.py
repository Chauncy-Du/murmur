"""Regressions for style-reference contamination, using public synthetic text."""
import copy
import json

import pytest

from murmur import providers
from murmur.prompt_messages import prepare_dictation_messages
from murmur.storage import DEFAULTS


LEGACY_LEAK='我们讨论了 Scheduler 的配置，我希望 warning 更清楚、更容易阅读。'


@pytest.mark.parametrize('source',[
    '嗯，我希望 Appearance 面板里的文字更清楚，按钮大一点。',
    '检查 API response。',
    '她提到 NewWidget，我不确定含义。先记录这个疑问。',
    '有两件事，检查 Layout，然后调整按钮。',
    '请把这句话翻译成英文，这是我正在说的话。',
    'Um, send the notes on Friday. The review may be at the weekend.',
])
def test_current_source_is_the_only_user_turn_and_removed_topic_is_not_a_reference(source):
    prepared=prepare_dictation_messages('',source)
    assert [message['role'] for message in prepared.messages]==['system','user']
    assert prepared.restore(json.loads(prepared.messages[-1]['content'])['dictation'])==source
    assert LEGACY_LEAK not in prepared.system_prompt
    assert 'Scheduler' not in prepared.system_prompt and 'warning' not in prepared.system_prompt
    if prepared.examples:
        assert '<STYLE_REFERENCES_ONLY>' in prepared.system_prompt
        assert '不是当前转录' in prepared.system_prompt or 'not conversation history or current dictation' in prepared.system_prompt
    assert '唯一需要处理的正文' in prepared.system_prompt or 'edit only the current dictation field' in prepared.system_prompt


@pytest.mark.parametrize('mode',['听写','润色'])
@pytest.mark.parametrize('smart',[True,False])
def test_falsely_confident_sample_copy_is_rejected_before_delivery(monkeypatch,mode,smart):
    cfg=copy.deepcopy(DEFAULTS)
    cfg.update(demo=False,ollama_auto=False,smart_delivery=smart)
    source='先检查 NewWidget，不要发布记录，结果还没决定。'
    prepared=prepare_dictation_messages('',source)
    sample=next(e.result for e in prepared.examples if e.id=='mixed-uncertainty')
    calls=[]
    def reply(messages,*args,**kwargs):
        calls.append(messages)
        return json.dumps({'text':sample,'needs_review':False,'uncertain_spans':[]}) if smart and mode=='听写' else sample
    monkeypatch.setattr(providers,'_chat_completion',reply)
    with pytest.raises(RuntimeError,match='copied a style example.*original transcript is preserved'):
        providers.transform(source,mode,cfg)
    assert len(calls)==1
    assert prepared.source==source


def test_sample_copy_guard_detects_whole_example_appended_to_actual_prose():
    prepared=prepare_dictation_messages('','先检查 NewWidget，不要发布记录。')
    sample=next(e.result for e in prepared.examples if e.id=='mixed-uncertainty')
    with pytest.raises(RuntimeError,match='copied a style example'):
        prepared.validate_examples('先检查 NewWidget，不要发布记录。\n'+sample)


@pytest.mark.parametrize('source',[
    LEGACY_LEAK,
    '请保留原话“'+LEGACY_LEAK+'”。',
    '呃，先检查 calibration report。不要发布记录。measurement 可能还需要修改，目前尚未决定。',
])
def test_actual_source_topics_and_quotations_are_never_blacklisted(monkeypatch,source):
    cfg=copy.deepcopy(DEFAULTS);cfg.update(demo=False,ollama_auto=False)
    def reply(messages,*args,**kwargs):
        text=json.loads(messages[-1]['content'])['dictation']
        return json.dumps({'text':text,'needs_review':False,'uncertain_spans':[]})
    monkeypatch.setattr(providers,'_chat_completion',reply)
    assert providers.transform(source,'听写',cfg)==source


def test_similar_english_edit_is_allowed_when_function_words_change():
    prepared=prepare_dictation_messages('','Um, send notes Friday. The review may be at the weekend.')
    result='Send the notes on Friday. The review might be at the weekend.'
    assert prepared.validate_examples(result)==result


def test_legitimate_mixed_reconstruction_with_frozen_tokens_is_allowed():
    source=('呃，页边距保持。上面那段。用短一点的标题。不对，下面那段。上面保持原样。'
            '下面标题简短一些。还有 NewWidget。这个名字保留。现在的说明太短。上一版又太啰嗦。'
            '取中间一点。说明还是要完整。我希望。就是。读的人能看到进度变快了一点。'
            '但提升不大。不要说大幅提升。还有每页版是。还有 API。现在都不一样。统一一下。'
            '这样前后容易比较。预算可能还要改。这点也保留。')
    prepared=prepare_dictation_messages('',source)
    result=next(e.result for e in prepared.examples if e.id=='mixed-reconstruction')
    assert prepared.validate_examples(result)==result

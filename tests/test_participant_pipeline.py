"""Original-language request/recovery boundaries for explicit participant scope."""
import copy
import json

import httpx
import pytest

from murmur import providers
from murmur.prompt_messages import prepare_dictation_messages
from murmur.storage import DEFAULTS


@pytest.fixture
def cfg():
    value=copy.deepcopy(DEFAULTS)
    value.update(demo=False,polish=True,ollama=False,ollama_auto=False,
                 llm_url='https://fixture.invalid/v1',llm_model='fixture')
    return value


def transport(monkeypatch,reply):
    bodies=[];original=httpx.Client
    def handle(request):
        assert request.url=='https://fixture.invalid/v1/chat/completions'
        body=json.loads(request.content);bodies.append(body)
        encoded=json.loads(body['messages'][-1]['content'])
        result=reply(encoded)
        return httpx.Response(200,json={'model':'fixture',
            'choices':[{'message':{'content':result}}],
            'usage':{'prompt_tokens':126,'completion_tokens':22,'total_tokens':148}})
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handle),**kw))
    monkeypatch.setattr(providers,'credential',lambda *a:'synthetic-key')
    return bodies


@pytest.mark.parametrize('mode',['听写','润色'])
@pytest.mark.parametrize('source,reply',[
    ('她说已经确认。我们尚未确认结果。','她说已经确认。目前尚未确认结果。'),
    ('她提到这个名字。我不确定含义。','她提到了这个名字，但她不确定含义。'),
    ('We have not confirmed the result.','The result has not been confirmed.'),
])
def test_missing_or_reassigned_participant_rejects_once_after_actual_reported_usage(monkeypatch,cfg,mode,source,reply):
    before=copy.deepcopy(cfg);usage=[]
    bodies=transport(monkeypatch,lambda data:reply)
    with pytest.raises(RuntimeError,match='participant perspective.*original text is preserved'):
        providers.transform(source,mode,cfg,usage_sink=usage.append)
    assert len(bodies)==len(usage)==1
    assert usage[0]['total_tokens']==148 and cfg==before


@pytest.mark.parametrize('source,reply',[
    ('嗯，她说已经确认。我们还没确认结果。','她说已经确认。我们尚未确认结果。'),
    ('呃，我不确定是不是同一个样品。','我尚不确定是否为同一个样品。'),
    ('Um, we have not confirmed the result.','The result has not been confirmed by us.'),
    ('嗯，我检查了两份记录。','我查看了两份记录。'),
])
def test_clear_written_rephrasing_remains_editable_and_keeps_usage(monkeypatch,cfg,source,reply):
    bodies=transport(monkeypatch,lambda data:reply)
    result=providers.transform(source,'润色',cfg)
    assert result==reply and result.usage['total_tokens']==148 and len(bodies)==1


def test_source_bound_scope_is_sent_as_data_but_not_recorded_in_metadata():
    source='她说已经确认。我们尚未确认结果。'
    prepared=prepare_dictation_messages('Keep concise sentences.',source)
    system=prepared.messages[0]['content']
    assert '原文明确的立场范围（数据）' in system
    assert json.dumps({'participant':'我们','stance':'未确认'},ensure_ascii=False) in system
    assert source not in system
    assert prepared.source==source
    assert json.loads(prepared.messages[-1]['content'])=={'dictation':source}
    metadata=json.dumps(prepared.metadata,ensure_ascii=False)
    assert '我们' not in metadata and '未确认' not in metadata and source not in metadata
    assert prepared.metadata['participant_claim_count']==1
    assert prepared.metadata['example_count']<=2


def test_ordinary_mixed_dictation_has_no_generic_sample_topic():
    prepared=prepare_dictation_messages('', '我们讨论了 TaskRunner 的配置，我希望说明更清楚。')
    assert prepared.examples==()
    assert 'Scheduler' not in prepared.system_prompt and 'warning' not in prepared.system_prompt
    assert prepared.restore(json.loads(prepared.messages[-1]['content'])['dictation'])==prepared.source


def test_translation_has_its_own_semantics_without_participant_plan(monkeypatch,cfg):
    bodies=transport(monkeypatch,lambda data:'Our result has not yet been confirmed.')
    result=providers.transform('我们尚未确认结果。','翻译',cfg)
    assert result=='Our result has not yet been confirmed.'
    body=bodies[0]
    assert json.loads(body['messages'][-1]['content'])=={'source_text':'我们尚未确认结果。'}
    assert 'Explicit source perspectives' not in body['messages'][0]['content']
    assert '原文明确的立场范围' not in body['messages'][0]['content']


def test_raw_dictation_does_not_run_participant_plan_or_call_a_model(monkeypatch,cfg):
    cfg['polish']=False
    monkeypatch.setattr(providers,'_chat_completion',lambda *a,**kw:pytest.fail('Unexpected model call'))
    source='呃，我们尚未确认结果。'
    assert providers.transform(source,'听写',cfg)==source

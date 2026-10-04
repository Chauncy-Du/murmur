"""Outgoing HTTP and recovery boundaries for original-language editorial spans."""
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
        text=reply(encoded)
        return httpx.Response(200,json={'model':'fixture',
            'choices':[{'message':{'content':text}}],
            'usage':{'prompt_tokens':123,'completion_tokens':20,'total_tokens':143}})
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handle),**kw))
    monkeypatch.setattr(providers,'credential',lambda *a:'synthetic-key')
    return bodies


@pytest.mark.parametrize('mode',['听写','润色'])
def test_model_edits_surrounding_prose_while_exact_technical_names_and_usage_return(monkeypatch,cfg,mode):
    source='嗯，今天 review 了这个 interface，希望 bubble 更小，Settings 保留 Auto model selection。'
    before=copy.deepcopy(cfg);usage=[]
    bodies=transport(monkeypatch,lambda data:data['dictation'].removeprefix('嗯，').replace('希望','想让'))
    result=providers.transform(source,mode,cfg,usage_sink=usage.append)
    assert result=='今天 review 了这个 interface，想让 bubble 更小，Settings 保留 Auto model selection。'
    encoded=json.loads(bodies[0]['messages'][-1]['content'])['dictation']
    assert all(term not in encoded for term in ('interface','bubble','Settings','Auto model selection'))
    assert 'review' in encoded and '今天' in encoded
    assert result.usage['total_tokens']==143 and len(usage)==1
    assert cfg==before and source.startswith('嗯，')


def test_weekday_phrase_restores_after_real_request_edit_and_keeps_usage(monkeypatch,cfg):
    bodies=transport(monkeypatch,lambda data:data['dictation'].removeprefix('Um, ').replace('Send','Please send'))
    result=providers.transform('Um, Send the notes on Friday. Keep the result private.','听写',cfg)
    assert result=='Please send the notes on Friday. Keep the result private.'
    assert 'on Friday' not in json.loads(bodies[0]['messages'][-1]['content'])['dictation']
    assert result.usage['total_tokens']==143


@pytest.mark.parametrize('mode',['听写','润色'])
def test_extra_deadline_relation_is_rejected_without_discarding_reported_usage(monkeypatch,cfg,mode):
    source='Send the notes on Friday.';usage=[]
    transport(monkeypatch,lambda data:data['dictation'].replace('[MURMUR_EDIT_', 'by [MURMUR_EDIT_'))
    with pytest.raises(RuntimeError,match='original text is preserved'):
        providers.transform(source,mode,cfg,usage_sink=usage.append)
    assert usage[0]['total_tokens']==143 and source=='Send the notes on Friday.'


def test_quote_and_term_layers_restore_in_the_correct_order(monkeypatch,cfg):
    source='呃，她说“等 API response”，先看 Settings，不要发布。'
    bodies=transport(monkeypatch,lambda data:data['dictation'].removeprefix('呃，'))
    result=providers.transform(source,'润色',cfg)
    assert result=='她说“等 API response”，先看 Settings，不要发布。'
    encoded=json.loads(bodies[0]['messages'][-1]['content'])['dictation']
    assert '[MURMUR_QUOTE_' in encoded and '[MURMUR_EDIT_' in encoded
    assert 'API response' not in encoded and 'Settings' not in encoded
    assert result.usage['total_tokens']==143


def test_plain_english_and_raw_dictation_do_not_freeze_ordinary_words(monkeypatch,cfg):
    source='Um, review the interface and both alternatives.'
    bodies=transport(monkeypatch,lambda data:data['dictation'].removeprefix('Um, '))
    assert providers.transform(source,'听写',cfg)=='review the interface and both alternatives.'
    assert '[MURMUR_EDIT_' not in json.loads(bodies[0]['messages'][-1]['content'])['dictation']
    cfg['polish']=False
    monkeypatch.setattr(providers,'_chat_completion',lambda *a,**k:pytest.fail('Raw dictation called a model'))
    assert providers.transform('嗯，先看 Settings。','听写',cfg)=='嗯，先看 Settings。'


def test_explicit_translation_uses_plain_source_and_its_own_operation(monkeypatch,cfg):
    source='她说“等 API response”，星期五看 Settings。'
    bodies=transport(monkeypatch,lambda data:'She said “wait for the API response”; review Settings on Friday.')
    result=providers.transform(source,'翻译',cfg)
    assert result.startswith('She said')
    assert json.loads(bodies[0]['messages'][-1]['content'])=={'source_text':source}
    assert 'Frozen editing tokens' not in bodies[0]['messages'][0]['content']


def test_prepared_snapshot_restores_without_leaking_named_contents_in_metadata():
    source='今天先检查 MyPanel 和 Settings，on Friday 再测 API。'
    prepared=prepare_dictation_messages('Keep my style.',source)
    assert prepared.restore(json.loads(prepared.messages[-1]['content'])['dictation'])==source
    metadata=json.dumps(prepared.metadata,ensure_ascii=False)
    assert 'MyPanel' not in metadata and source not in metadata and 'on Friday' not in metadata
    assert prepared.metadata['frozen_term_count']>0 and prepared.metadata['frozen_time_count']==1


@pytest.mark.parametrize('mode',['听写','润色'])
@pytest.mark.parametrize('source,reply,diagnostic',[
    ('Today we reviewed the screen. Send the notes. Do not publish the result.',
     'We reviewed the screen today and sent the notes, but did not publish the result.',
     'instruction into a completed action'),
    ('Keep the notes private. Approval has not been given.',
     'Keep the notes private, as approval has not been given.', 'causal relationship'),
    ('不要公开记录。尚未验证。','不要公开记录，因为尚未验证。','causal relationship'),
    ('他提到 Zorvex，我不确定是不是这个名字。先记录这个不确定性，暂时不要改成别的词。',
     '他提到了 Zorvex，但不确定是否为正确名称。已记录此不确定性，暂不更改该术语。',
     'instruction into a completed action'),
])
def test_semantic_rejection_publishes_actual_usage_once_without_retry(monkeypatch,cfg,mode,source,reply,diagnostic):
    usage=[];before=copy.deepcopy(cfg)
    bodies=transport(monkeypatch,lambda data:reply)
    with pytest.raises(RuntimeError,match=diagnostic+'.*original text is preserved'):
        providers.transform(source,mode,cfg,usage_sink=usage.append)
    assert len(bodies)==len(usage)==1 and usage[0]['total_tokens']==143
    assert cfg==before


@pytest.mark.parametrize('source,reply',[
    ('Please send the notes. Do not publish them.',
     'You should send the notes. You must not publish them.'),
    ('Wait because approval is pending.', 'Approval is pending; therefore wait.'),
    ('As a reviewer, keep both alternatives.', 'As a reviewer, retain both alternatives.'),
])
def test_guard_does_not_disable_legitimate_rewriting(monkeypatch,cfg,source,reply):
    bodies=transport(monkeypatch,lambda data:reply)
    result=providers.transform(source,'润色',cfg)
    assert result==reply and result.usage['total_tokens']==143 and len(bodies)==1


@pytest.mark.parametrize('mode',['听写','润色'])
def test_invented_internal_id_is_rejected_at_http_boundary(monkeypatch,cfg,mode):
    usage=[]
    bodies=transport(monkeypatch,lambda data:data['dictation']+' [MURMUR_QUOTE_999]')
    with pytest.raises(RuntimeError,match='original text is preserved'):
        providers.transform('Review the notes.',mode,cfg,usage_sink=usage.append)
    assert len(bodies)==len(usage)==1 and usage[0]['total_tokens']==143

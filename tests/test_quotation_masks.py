"""Lossless quoted material survives an editorial model without being rewritten."""
import copy
import json

import pytest

from murmur import providers
from murmur.quotations import mask_quotations
from murmur.storage import DEFAULTS
from murmur.usage import UsageText


def test_freeze_restores_exact_delimiters_interior_punctuation_and_duplicate_spans():
    source='她说“等 API response。”然后又说“等 API response。”'
    plan=mask_quotations(source)
    assert plan.source=='她说[MURMUR_QUOTE_1]然后又说[MURMUR_QUOTE_2]'
    assert plan.restore('她说[MURMUR_QUOTE_1]，然后又说[MURMUR_QUOTE_2]。')==(
        '她说“等 API response。”，然后又说“等 API response。”。')
    assert 'API response' not in plan.contract


@pytest.mark.parametrize('result',[
    'She said [MURMUR_QUOTE_1].',
    '[MURMUR_QUOTE_1] [MURMUR_QUOTE_1] [MURMUR_QUOTE_2]',
    '[MURMUR_QUOTE_2] then [MURMUR_QUOTE_1]',
    '“[MURMUR_QUOTE_1]” then [MURMUR_QUOTE_2]',
    '[MURMUR_quote_1] [MURMUR_QUOTE_2]',
    'No quotation survived.',
])
def test_dropped_duplicate_reordered_wrapped_or_changed_tokens_are_rejected(result):
    plan=mask_quotations('She said "alpha" then “beta”.')
    with pytest.raises(RuntimeError,match='quoted text.*original text is preserved'):
        plan.restore(result)


def test_user_literal_marker_cannot_collide_with_generated_quotation_token():
    source='Keep [MURMUR_QUOTE_1] literal. She said “wait”.'
    plan=mask_quotations(source)
    assert plan.source=='Keep [MURMUR_QUOTE_1] literal. She said [MURMUR_QUOTE_2].'
    assert plan.restore(plan.source)==source


@pytest.mark.parametrize('source',['“今天开会。”','"Keep the API."'])
def test_quote_restoration_precedes_language_guard_and_keeps_real_usage(monkeypatch,source):
    cfg=copy.deepcopy(DEFAULTS)
    cfg.update(demo=False,polish=True,ollama=False,ollama_auto=False,llm_url='http://127.0.0.1:11434/v1')
    usage={'total_tokens':42}
    def echo(messages,*a,**k):
        return UsageText(json.loads(messages[-1]['content'])['dictation'],usage)
    monkeypatch.setattr(providers,'_chat_completion',echo)
    result=providers.transform(source,'听写',cfg)
    assert result==source and result.usage==usage


def test_no_token_fallback_accepts_only_the_complete_unchanged_source():
    source='Alice said "yes". Bob said "no".'
    plan=mask_quotations(source)
    assert plan.restore(source)==source
    for rewritten in ('Alice said "no". Bob said "yes".',
                      'Alice said "yes". Bob said "no". Therefore cancel the meeting.'):
        with pytest.raises(RuntimeError,match='original text is preserved'):
            plan.restore(rewritten)


@pytest.mark.parametrize('source',['"alpha" "beta"','她说“是”“不是”。'])
def test_adjacent_clear_quotations_restore_without_false_wrapper_detection(source):
    plan=mask_quotations(source)
    assert len(plan.replacements)==2
    assert plan.restore(plan.source)==source


@pytest.mark.parametrize('source',['"" "alpha"','她保留“”和“原话”。'])
def test_unchanged_tokenized_source_keeps_original_empty_quote_delimiters(source):
    plan=mask_quotations(source)
    assert plan.replacements
    assert plan.restore(plan.source)==source


@pytest.mark.parametrize('result',[
    'Alice said " [MURMUR_QUOTE_1] ". Bob said [MURMUR_QUOTE_2].',
    'Alice said “\n[MURMUR_QUOTE_1]\t”. Bob said [MURMUR_QUOTE_2].',
])
def test_whitespace_does_not_hide_added_quote_wrappers(result):
    with pytest.raises(RuntimeError,match='original text is preserved'):
        mask_quotations('Alice said "yes". Bob said "no".').restore(result)


@pytest.mark.parametrize('mode',['听写','润色'])
@pytest.mark.parametrize('source,reply',[
    ('她说“您好”。我今天要开会。','She said [MURMUR_QUOTE_1]. I have a meeting today.'),
    ('She said "hello". I have a meeting today.','她说 [MURMUR_QUOTE_1]。我今天要开会。'),
])
def test_original_language_quote_cannot_hide_translated_surrounding_prose(monkeypatch,mode,source,reply):
    cfg=copy.deepcopy(DEFAULTS)
    cfg.update(demo=False,polish=True,ollama=False,ollama_auto=False,llm_url='http://127.0.0.1:11434/v1')
    monkeypatch.setattr(providers,'_chat_completion',lambda *a,**k:reply)
    with pytest.raises(RuntimeError,match='changed the dictation language.*original text is preserved'):
        providers.transform(source,mode,cfg)
@pytest.mark.parametrize('source', ['Review the notes.', 'She said “keep the notes”.'])
def test_invented_unassigned_quote_marker_cannot_escape_into_output(source):
    mask=mask_quotations(source)
    with pytest.raises(RuntimeError,match='original text is preserved'):
        mask.restore(mask.source+' [MURMUR_QUOTE_999]')


def test_existing_literal_quote_marker_is_collision_safe_but_cannot_be_duplicated():
    source='Keep [MURMUR_QUOTE_1] as text. She said “hold”.'
    mask=mask_quotations(source)
    assert mask.replacements[0][0]=='[MURMUR_QUOTE_2]'
    assert mask.restore(mask.source)==source
    with pytest.raises(RuntimeError,match='original text is preserved'):
        mask.restore(mask.source+' [MURMUR_QUOTE_1]')


def test_literal_quote_id_inside_frozen_quote_cannot_be_duplicated_outside_it():
    source='She said “keep [MURMUR_QUOTE_1]”. Review the notes.'
    mask=mask_quotations(source)
    assert mask.restore(mask.source)==source
    with pytest.raises(RuntimeError,match='original text is preserved'):
        mask.restore(mask.source+' [MURMUR_QUOTE_1]')

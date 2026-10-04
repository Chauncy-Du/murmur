"""Public editorial fixtures; no microphone, user data or model requests."""
import copy
import json

import pytest

from murmur import providers
from murmur.dictation_corrections import prepare_corrections, validate_corrections
from murmur.prompt_messages import prepare_dictation_messages
from murmur.storage import DEFAULTS


@pytest.mark.parametrize('source,expected', [
    ('今天先发记录，不对，明天先发记录。不要公开。', '明天先发记录。不要公开。'),
    ('我今天先发记录，不对，我明天先发记录。', '我明天先发记录。'),
    ('今天，不对，明天开会。今天的记录保留。', '明天开会。今天的记录保留。'),
    ('Send notes on Tuesday, sorry, Friday; check the API tomorrow.',
     'Send notes on Friday; check the API tomorrow.'),
    ('厚度是 120 nm，不对，是 150 nm。可能需要重测。', '厚度是 150 nm。可能需要重测。'),
    ('120 nm，不对，150 nm，不对，180 nm。', '180 nm。'),
    ('今天发记录，不对，是明天发记录。报告还没决定。', '明天发记录。报告还没决定。'),
    ('Tuesday, sorry, Friday. Tuesday remains a separate appointment.',
     'Friday. Tuesday remains a separate appointment.'),
])
def test_local_value_correction_keeps_final_and_neighboring_content(source, expected):
    plan = prepare_corrections(source)
    assert plan.edited_source == expected
    assert plan.corrections


@pytest.mark.parametrize('source', [
    '今天先发记录，不对，明天先付款。',
    '今天，不对，可能明天开会。',
    '今天。不对，明天开会。',
    '今天不是不对，明天的安排还没决定。',
    '120 nm，不对，150 mm。',
    '她说“今天，不对，明天”，先保留原话。',
    '她说“今天发，不对，明天发。',
    '“外层‘今天，不对，明天’引用”保留。',
    '今天发记录。另一个人说错了，明天发报告。',
    '今天发；我是说明天付款。',
    '120 nm，不对，至少150 nm。',
    '不是今天，不对，明天。',
    '可能今天，不对，明天。',
    'Not Tuesday, sorry, Friday.',
    'No later than Tuesday, sorry, Friday.',
    'The meeting may be Monday, correction, Tuesday.',
    '会议不在今天，不对，明天。',
    '我今天说错了明天的计划。',
    '今天我是说明天要审核的内容，不是在纠正日期。',
    'Tuesday I mean Friday is different.',
    '120 V, correction, 150 V/s.',
    '120 V, correction, 150 V / s.',
    '120 nm，不对，150 nm²。',
    '120 nm，不对，150 nm^2。',
    'fixture_Monday, sorry, Tuesday.',
    'monday2, sorry, Tuesday.',
    "She said 'Tuesday, sorry, Friday', keep those words.",
])
def test_ambiguous_scopes_quotes_different_actions_or_units_are_not_rewritten(source):
    assert prepare_corrections(source).edited_source == source


def test_chained_correction_checks_only_final_value():
    plan = prepare_corrections('120 nm，不对，150 nm，不对，180 nm。')
    assert validate_corrections(plan, '厚度为 180nm。') == '厚度为 180nm。'
    for invalid in ('厚度为 150 nm。', '厚度为 120 nm 和 180 nm。', '厚度已确定。'):
        with pytest.raises(RuntimeError, match='original text is preserved'):
            validate_corrections(plan, invalid)


def test_han_adjacent_quantity_does_not_cause_false_rejection():
    plan = prepare_corrections('厚度是120nm，不对，是150nm。')
    assert plan.edited_source == '厚度是150nm。'
    assert validate_corrections(plan, '厚度为150nm。') == '厚度为150nm。'


def test_remaining_old_date_and_weekday_spelling_equivalence_are_allowed():
    plan = prepare_corrections('周二，不对，周五开会。周二单独留给实验。')
    assert validate_corrections(plan, '星期五开会，星期二留给实验。')
    plan = prepare_corrections('周二，不对，周五开会。')
    with pytest.raises(RuntimeError):
        validate_corrections(plan, '周二开会，而不是周五。')


def test_request_has_independent_edit_material_and_keeps_raw_snapshot():
    source = '今天先发记录，不对，明天先发记录。报告可能还要改，不能公开。'
    prepared = prepare_dictation_messages('', source)
    assert prepared.source == source
    assert json.loads(prepared.messages[-1]['content']) == {
        'dictation': '明天先发记录。报告可能还要改，不能公开。'}
    assert prepared.metadata['resolved_correction_count'] == 1
    assert source not in json.dumps(prepared.metadata, ensure_ascii=False)


def test_transform_guards_draft_without_mutating_source_configuration_or_usage(monkeypatch):
    cfg = copy.deepcopy(DEFAULTS)
    cfg.update(demo=False, polish=True, ollama=False, ollama_auto=False,
               llm_url='http://127.0.0.1:11434/v1', llm_model='fixture-model')
    original = copy.deepcopy(cfg)
    source = '今天先发记录，不对，明天先发记录。'
    sent = []
    monkeypatch.setattr(providers, '_chat_completion', lambda messages, *a, **k:
        sent.extend(messages) or '今天和明天都发记录。')
    with pytest.raises(RuntimeError, match='explicit correction'):
        providers.transform(source, '听写', cfg)
    assert json.loads(sent[-1]['content']) == {'dictation': '明天先发记录。'}
    assert source == '今天先发记录，不对，明天先发记录。'
    assert cfg == original
    cfg['polish'] = False
    assert providers.transform(source, '听写', cfg) == source

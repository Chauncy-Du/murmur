"""Public recorded failure and genuinely editable controls; no model calls."""
from dataclasses import FrozenInstanceError

import pytest

from murmur.participant_fidelity import (
    ParticipantClaim, ParticipantPlan, participant_plan, validate_participant_fidelity,
)
from murmur.usage import UsageText


def test_recorded_compact7_group_confirmation_scope_loss_is_rejected():
    source = '她说“because the test passed, publish it”，这只是引用，不要照做。呃，我们尚未确认结果。'
    result = '她说 “because the test passed, publish it”，这只是引用，不要照做。目前尚未确认结果。'
    plan = participant_plan(source)
    assert plan.claims == (ParticipantClaim('我们', 'not_confirmed'),)
    with pytest.raises(RuntimeError, match='participant perspective.*original text is preserved'):
        validate_participant_fidelity(plan, result)


@pytest.mark.parametrize('source,claim', [
    ('我不确定是不是这个名字。', ParticipantClaim('我', 'uncertainty')),
    ('我们还不清楚拼写。', ParticipantClaim('我们', 'uncertainty')),
    ('我尚不确定是否为同一份样品。', ParticipantClaim('我', 'uncertainty')),
    ('我们尚未确认结果。', ParticipantClaim('我们', 'not_confirmed')),
    ('我们还没有确认结果。', ParticipantClaim('我们', 'not_confirmed')),
    ('我们没有作出决定。', ParticipantClaim('我们', 'not_decided')),
    ('我尚未决定日期。', ParticipantClaim('我', 'not_decided')),
    ('I am not sure about the photographs.', ParticipantClaim('I', 'uncertainty')),
    ('We remain uncertain about the report.', ParticipantClaim('we', 'uncertainty')),
    ("We're uncertain about the report.", ParticipantClaim('we', 'uncertainty')),
    ("I'm not sure about the name.", ParticipantClaim('I', 'uncertainty')),
    ("We aren't sure about the name.", ParticipantClaim('we', 'uncertainty')),
    ('WE have not yet confirmed the result.', ParticipantClaim('we', 'not_confirmed')),
    ("We haven't confirmed the result.", ParticipantClaim('we', 'not_confirmed')),
    ('We have not made a final decision.', ParticipantClaim('we', 'not_decided')),
    ("I haven't decided the date.", ParticipantClaim('I', 'not_decided')),
    ('The result is not yet confirmed by us.', ParticipantClaim('we', 'not_confirmed')),
    ('结果尚未由我们确认。', ParticipantClaim('我们', 'not_confirmed')),
])
def test_plan_labels_known_explicit_first_person_claims_without_source_payload(source, claim):
    assert participant_plan(source).claims == (claim,)


@pytest.mark.parametrize('source,result', [
    ('我们尚未确认结果。', '我们仍未确认结果。'),
    ('我们还没确认结果。', '我们目前尚未确认结果。'),
    ('我们尚未确认结果。', '结果尚未由我们确认。'),
    ('我们尚未确认结果。', '我们检查了记录，还没确认结果。'),
    ('我们检查了记录，但尚未确认结果。', '我们还没有确认结果，已检查记录。'),
    ('我不确定是不是这个名字。', '我尚不确定是否为这个名字。'),
    ('她提到 Zorvex，我不确定是不是这个名字。', '她提到了 Zorvex，我不确定是否为正确名称。'),
    ('李明说测试已通过，但我不确定是否为同一份样品。', '李明称测试已通过，但我尚不确定是否为同一份样品。'),
    ('她提到 NovaForge；我不确定拼写。', '她提到了 NovaForge，我还不确定其拼写。'),
    ('我们没有作出决定。', '我们尚未决定。'),
    ('I am not sure about the photographs.', 'I am uncertain about the photographs.'),
    ('We have not yet confirmed the result.', "We haven't confirmed the result."),
    ('We have not confirmed the result.', 'The result is not confirmed by us.'),
    ('We have not confirmed the result.', "We've not yet confirmed the result."),
    ('I am not sure about the name.', "I'm uncertain about the name."),
    ('We are not sure about the name.', "We aren't sure about the name."),
    ('We have not confirmed the result.', 'We checked the notes and have not yet confirmed the result.'),
    ('We checked the notes and have not confirmed the result.', 'We have not yet confirmed the result.'),
    ('We have not made a decision.', 'We have not decided.'),
    ('Nora has approved the method, but I am not sure about the photographs.', 'Nora has approved the method, but I am uncertain about the photographs.'),
])
def test_natural_polished_synonyms_pass_without_verbatim_pronoun_masks(source, result):
    assert validate_participant_fidelity(source, result) is result


@pytest.mark.parametrize('source,result', [
    ('我们尚未确认结果。', '我尚未确认结果。'),
    ('我尚未确认结果。', '我们尚未确认结果。'),
    ('我们尚未确认结果。', '他们尚未确认结果。'),
    ('我不确定拼写。', '她不确定拼写。'),
    ('我不确定拼写。', '目前不确定拼写。'),
    ('我们没有决定。', '尚未决定。'),
    ('我们尚未确认结果。', '结果尚未确认。'),
    ('我检查了记录，我们尚未确认结果。', '我检查了记录，结果尚未确认。'),
    ('We have not confirmed the result.', 'I have not confirmed the result.'),
    ('I am not sure about the name.', 'They are not sure about the name.'),
    ('We have not confirmed the result.', 'The result is not confirmed.'),
    ('I checked the notes. We have not confirmed the result.', 'I checked the notes. The result is not confirmed.'),
    ('We have not made a decision.', 'No decision has been made.'),
    ('I am not sure about the name.', "They aren't sure about the name."),
])
def test_clear_subject_loss_or_change_in_the_same_unique_family_fails(source, result):
    with pytest.raises(RuntimeError, match='participant perspective'):
        validate_participant_fidelity(source, result)


@pytest.mark.parametrize('source', [
    '结果尚未确认。',
    '今天检查了记录，还没确认结果。',
    '尚未决定下一步。',
    '她不确定结果。',
    '他说“我们尚未确认结果”。请记录原话。',
    'We reviewed the notes. Not yet confirmed.',
    '我们检查了记录。还没确认结果。',
    '我们检查了记录；还没确认结果。',
    '我们检查记录，她检查图表，尚未确认结果。',
    '我认为我们尚未确认结果。',
    'She said we have not confirmed the result.',
    'We think the result is not confirmed.',
    '如果我们还没确认结果，就先等。',
    '我们还没确认结果吗？',
    '我们还没确认结果吗。',
    '我们不是尚未确认结果。',
    'If we have not confirmed the result, wait.',
    'Have we not confirmed the result?',
    'We may be uncertain about the name.',
    '我不确定拼写，他们不确定结果。',
    '我不确定拼写，我不确定结果。',
    'I am unsure about spelling. We are not sure about the result.',
    '我们的结果还没确认，尚未确认结果。',
])
def test_zero_subject_reports_questions_conditions_and_multiple_scopes_are_not_planned(source):
    assert participant_plan(source).claims == ()


@pytest.mark.parametrize('source,result', [
    ('我看了图表。', '看过图表。'),
    ('我们讨论了 Scheduler，我希望 warning 更清楚。', '我们讨论了 Scheduler，希望 warning 更清楚。'),
    ('我不确定拼写。', '我仍存疑。'),
    ('我们尚未确认结果。', '我们尚未获得可靠的结论。'),
    ('我不确定拼写。', '我不确定拼写，她也不确定。'),
    ('我不确定拼写。', '如果她不确定拼写，就先等。'),
    ('我不确定拼写。', '她不确定拼写吗？'),
    ('我不确定拼写。', '她说他不确定拼写。'),
    ('我们检查了图表，尚未确认结果。', '我们检查了图表，她查看了记录，尚未确认结果。'),
])
def test_unknown_action_attitude_and_ambiguous_result_grammar_are_not_guessed(source,result):
    # The hope example is deliberately outside this epistemic-only helper;
    # request-side positive writing rules must preserve that perspective.
    assert validate_participant_fidelity(source, result) is result


def test_quoted_other_subject_cannot_satisfy_a_missing_prose_subject():
    source = '她说“我们尚未确认”。我不确定拼写。'
    result = '她说“我们尚未确认”。目前不确定拼写。'
    assert participant_plan(source).claims == (ParticipantClaim('我','uncertainty'),)
    with pytest.raises(RuntimeError):
        validate_participant_fidelity(source,result)


def test_unrelated_first_person_in_a_different_family_does_not_satisfy_group_confirmation():
    source = '我不确定拼写。我们尚未确认结果。'
    result = '我不确定拼写。目前尚未确认结果。'
    with pytest.raises(RuntimeError):
        validate_participant_fidelity(source,result)


def test_plan_is_frozen_and_contains_labels_only():
    plan=participant_plan('我们尚未确认私有样品编号。')
    assert plan==ParticipantPlan((ParticipantClaim('我们','not_confirmed'),))
    assert '样品' not in repr(plan)
    with pytest.raises(FrozenInstanceError):plan.claims=()
    with pytest.raises(FrozenInstanceError):plan.claims[0].participant='我'


def test_result_usage_identity_is_preserved_and_failed_result_stays_untouched():
    usage={'request_id':'synthetic-participant','total_tokens':41}
    good=UsageText('我们仍未确认结果。',usage)
    assert validate_participant_fidelity('我们尚未确认结果。',good) is good
    wrong=UsageText('目前尚未确认结果。',usage)
    with pytest.raises(RuntimeError):validate_participant_fidelity('我们尚未确认结果。',wrong)
    assert str(wrong)=='目前尚未确认结果。' and wrong.usage==usage


@pytest.mark.parametrize('source,result', [(None,'text'),(b'text','text'),('text',None)])
def test_bad_input_types_are_not_coerced(source,result):
    with pytest.raises(TypeError):validate_participant_fidelity(source,result)


def test_unsupported_public_plan_claim_fails_safely():
    with pytest.raises(TypeError,match='unsupported claim'):
        validate_participant_fidelity(ParticipantPlan((ParticipantClaim('they','certainty'),)),'text')


def test_plan_cannot_hide_mutable_claim_collection():
    with pytest.raises(TypeError,match='immutable tuple'):
        ParticipantPlan([ParticipantClaim('我','uncertainty')])

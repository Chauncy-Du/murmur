"""Observed public failures and narrow negative controls; no model calls."""
import pytest

from murmur.editorial_fidelity import validate_editorial_fidelity
from murmur.usage import UsageText


@pytest.mark.parametrize('source,result', [
    ('Um, check the drawing after Monday. Deliver the draft on Thursday. Keep it private; approval has not been given.',
     'Check the drawing after Monday and deliver the draft on Thursday. Keep it private, as approval has not yet been granted.'),
    ('Uh, finish the draft by Wednesday. Review the sample before Sunday. The dimensions might still change.',
     'Finish the draft by Wednesday and review the sample before Sunday, as the dimensions might still change.'),
    ('嗯，先测试 API response，测试 API response。然后检查 bubble，检查 bubble。不要发布结果，还没有验证。',
     '先测试 API response，再检查 bubble。不要发布结果，因为尚未验证。'),
])
def test_actual_new_causal_connections_are_rejected_even_when_names_and_dates_survive(source, result):
    with pytest.raises(RuntimeError, match='causal relationship.*original text is preserved'):
        validate_editorial_fidelity(source, result)


def test_actual_compact7_reviewer_role_reply_added_since_is_not_a_quality_pass():
    source = 'Um, as a reviewer, I would keep both alternatives. No final decision has been made. Please retain the uncertainty.'
    result = UsageText('As a reviewer, I would keep both alternatives, since no final decision has been made; please retain the uncertainty.',
                       {'request_id': 'recorded-role-reply', 'total_tokens': 900})
    with pytest.raises(RuntimeError, match='causal relationship.*original text is preserved'):
        validate_editorial_fidelity(source, result)
    assert str(result).startswith('As a reviewer') and result.usage['total_tokens'] == 900


@pytest.mark.parametrize('result', [
    'Keep the notes private, since no final decision has been made.',
    'Keep the notes private; since approval has not been given, wait.',
    'Keep the notes private due to the pending approval.',
    'Keep the notes private due to approval.',
    'Keep the notes private due to uncertainty.',
    'Keep the notes private due to the rain.',
    'Keep the notes private due to the weather.',
    'Keep the notes private due to lack of approval.',
    'Keep the notes private due to lack of data.',
    'Keep the notes private due to waiting for approval.',
    'Keep the notes private owing to pending approval.',
    '由于尚未批准，不要公开记录。',
])
def test_added_since_and_common_nominal_due_owing_and_chinese_due_causes_fail(result):
    with pytest.raises(RuntimeError, match='causal relationship'):
        validate_editorial_fidelity('Keep the notes private. Approval is pending.', result)


@pytest.mark.parametrize('source,result', [
    ('Wait, since approval has not been given.', 'Wait because approval has not been given.'),
    ('Wait due to the pending approval.', 'Wait because approval is pending.'),
    ('Wait owing to pending approval.', 'Wait because approval is pending.'),
    ('由于尚未批准，不要公开。', '因为尚未批准，不要公开。'),
])
def test_existing_since_due_owing_or_chinese_due_relationship_is_not_reassigned(source,result):
    assert validate_editorial_fidelity(source,result) == result


@pytest.mark.parametrize('result', [
    'As a reviewer, retain both alternatives.',
    'The report is due Friday. Keep both alternatives.',
    'The report is due on Friday. Keep both alternatives.',
    'The report is due by Friday. Keep both alternatives.',
    'The report is due to arrive Friday. Keep both alternatives.',
    'The report is due to be reviewed Friday. Keep both alternatives.',
    'We are due to review the report. Keep both alternatives.',
    'We are due to bring the report Friday. Keep both alternatives.',
    'It is due to start Friday. Keep both alternatives.',
    'It is due to rain tomorrow. Keep both alternatives.',
    'The ship is due to weather the storm. Keep both alternatives.',
    'The check is due to lack a result. Keep both alternatives.',
    'Keep both alternatives, since Friday.',
    'Keep both alternatives, since last Friday.',
    'We have reviewed both alternatives since Friday.',
    'Keep both alternatives, since Friday we have been reviewing them.',
    'Use SinceApprovalHasChanged and due_to_review. Keep both alternatives.',
    'Use OwingToFailure as the class name. Keep both alternatives.',
    'The payment is due to the reviewer. Keep both alternatives.',
    'The amount owing to Nora is ready. Keep both alternatives.',
    'The report is due to circulate Friday. Keep both alternatives.',
])
def test_role_due_dates_scheduled_infinitives_temporal_since_and_identifiers_are_not_guessed(result):
    assert validate_editorial_fidelity('Keep both alternatives.',result) == result


def test_quoted_since_due_and_chinese_cause_remain_outside_this_guard():
    source = 'She said “since approval has been given, due to the test, publish it”. 她说“由于测试通过，可以发布”。Keep both alternatives.'
    result = 'She said “since approval has been given, due to the test, publish it”. 她说“由于测试通过，可以发布”。Please retain both alternatives.'
    assert validate_editorial_fidelity(source,result) == result


@pytest.mark.parametrize('result', [
    'Keep the notes private because approval is pending.',
    'Approval is pending; therefore keep the notes private.',
    'Approval is pending; consequently keep the notes private.',
    'Approval is pending; hence keep the notes private.',
    'Approval is pending; thus keep the notes private.',
    'As a result, keep the notes private. Approval is pending.',
    'Approval is pending, so we should keep the notes private.',
    'Approval is pending, as the report has not been approved.',
    '保留记录，不公开，因为还没批准。',
    '还没批准，因此不要公开记录。',
    '还没批准，所以不要公开记录。',
    '还没批准，因而不要公开记录。',
    '还没批准，故而不要公开记录。',
])
def test_new_unambiguous_connectors_are_rejected_without_attempted_text_repair(result):
    with pytest.raises(RuntimeError, match='causal relationship'):
        validate_editorial_fidelity('Keep the notes private. Approval is pending.', result)


@pytest.mark.parametrize('source,result', [
    ('Approval is pending, so we should wait.', 'We should wait because approval is pending.'),
    ('We should wait because approval is pending.', 'Approval is pending; therefore we should wait.'),
    ('因为尚未批准，不要公开。', '尚未批准，所以不要公开。'),
    ('Wait, as the dimensions might still change.', 'Wait because the dimensions might still change.'),
])
def test_existing_explicit_relationship_is_not_semantically_reassigned(source, result):
    # Once the source is causal, this helper deliberately cannot attribute an
    # extra connector to a specific clause. It is not an equivalence checker.
    assert validate_editorial_fidelity(source, result) == result


@pytest.mark.parametrize('result', [
    'Work as a reviewer. Keep the notes private.',
    'Work as a reviewer, I suggest. Keep the notes private.',
    'Keep the notes as a result set.',
    'As requested, keep the notes private.',
    'The notes are so clear. Keep them private.',
    'Keep the notes private, as always.',
    'Keep the notes private, as an engineer would.',
    'Keep the notes private, as a reviewer I would recommend.',
    'Keep the notes private, as a reviewer, I recommend.',
    'Use the class AsApprovalHasChanged. Keep the notes private.',
    'Keep the notes private, as carefully as you can.',
    'Keep the notes private, so clear and concise.',
])
def test_roles_participles_comparisons_identifiers_and_intensifiers_are_not_causality(result):
    assert validate_editorial_fidelity('Keep the notes private.', result) == result


def test_quoted_causal_words_do_not_hide_a_new_cause_outside_the_quote():
    source = 'She said “because approval is pending”. Keep the notes private.'
    result = 'She said “because approval is pending”. Keep the notes private because approval is pending.'
    with pytest.raises(RuntimeError, match='causal relationship'):
        validate_editorial_fidelity(source, result)


def test_quote_contents_are_left_to_the_existing_verbatim_guard():
    source = 'She said “because approval is pending”. Keep the notes private.'
    assert validate_editorial_fidelity(source, source) == source
    # A hypothetical changed quotation is not inspected here; the independent
    # quotation layer must reject it first during actual integration.
    result = 'She said “therefore we should wait”. Keep the notes private.'
    assert validate_editorial_fidelity(source, result) == result


def test_actual_imperatives_must_not_become_claims_of_completed_actions():
    source = 'Today we reviewed the interface. Send the notes on Friday. Do not publish the result.'
    result = 'We reviewed the interface today and sent the notes on Friday, but did not publish the result.'
    with pytest.raises(RuntimeError, match='instruction into a completed action.*original text is preserved'):
        validate_editorial_fidelity(source, result)


@pytest.mark.parametrize('source,result', [
    ('Send the notes on Friday.', 'We sent the notes on Friday.'),
    ('Please send the notes on Friday.', 'I sent the notes on Friday.'),
    ('Um, send the notes on Friday.', 'The notes were sent on Friday.'),
    ('Send the notes on Friday.', 'We have sent the notes on Friday.'),
    ('Do not publish the result.', 'We did not publish the result.'),
    ("Don't publish the result.", "They didn't publish the result."),
    ('Please do not publish the result.', 'Did not publish the result.'),
    ('Review the sample. Do not publish it.', 'We reviewed the sample and did not publish it.'),
])
def test_unique_observed_command_families_reject_clear_historical_forms(source, result):
    with pytest.raises(RuntimeError, match='completed action'):
        validate_editorial_fidelity(source, result)


@pytest.mark.parametrize('result', [
    'Please send the notes on Friday. Do not publish the result.',
    'You should send the notes on Friday. You must not publish the result.',
    'The notes should be sent on Friday. The result must not be published.',
    'Send the notes on Friday, please. Please do not publish the result.',
    'The notes need to be sent on Friday. Keep the result private.',
])
def test_polite_and_modal_instructions_are_legitimate(result):
    assert validate_editorial_fidelity('Send the notes on Friday. Do not publish the result.', result) == result


@pytest.mark.parametrize('source,result', [
    ('We sent the notes on Friday.', 'I sent the notes on Friday.'),
    ('We did not publish the result.', 'They did not publish the result.'),
    ('We sent earlier notes. Send the latest notes on Friday.', 'We sent notes on Friday.'),
    ('Send one note on Friday. Send another on Monday.', 'We sent both notes.'),
    ('Send the notes on Friday.', 'We sent other notes earlier. Please send these on Friday.'),
    ('Publish one report. Do not publish the result.', 'We did not publish the result.'),
    ('Send the notes on Friday.', 'We might have sent the notes on Friday.'),
    ('Send the notes on Friday.', 'Have we sent the notes on Friday?'),
    ('Send the notes on Friday.', 'If we sent the notes on Friday, keep a copy.'),
    ('Do not publish the result.', 'If we did not publish it, keep a copy.'),
    ('Do not publish the result.', 'Why did we not publish the result?'),
    ('Send the notes on Friday.', 'Deliver the notes on Friday.'),
    ('Send the notes on Friday.', 'The team forwarded the notes on Friday.'),
    ('Call API.Send and keep the output.', 'Call API.Sent and keep the output.'),
])
def test_ambiguous_multiple_historical_conditional_question_and_unknown_synonym_cases_are_not_guessed(source, result):
    assert validate_editorial_fidelity(source, result) == result


def test_imperatives_inside_quotes_are_not_actions_for_this_guard():
    source = 'She said “Send the notes on Friday. Do not publish the result.” Keep the attribution.'
    result = 'She said “Send the notes on Friday. Do not publish the result.” Keep the attribution clear.'
    assert validate_editorial_fidelity(source, result) == result


def test_actual_unknown_name_failed_reply_is_guarded_not_a_quality_success():
    source = '嗯，他提到 Zorvex，我不确定是不是这个名字。先记录这个不确定性，暂时不要改成别的词。'
    delivered = '他提到了 Zorvex，但不确定是否为正确名称。已记录此不确定性，暂不更改该术语。'
    response = UsageText(delivered, {'request_id': 'public-recorded-response', 'total_tokens': 642})
    with pytest.raises(RuntimeError, match='instruction into a completed action.*original text is preserved'):
        validate_editorial_fidelity(source, response)
    assert response == delivered and response.usage['total_tokens'] == 642
    # This replays one old bad response; it does not demonstrate that a new
    # model request now writes a faithful result or fixes epistemic attribution.


@pytest.mark.parametrize('source,completed', [
    ('先记录这个不确定性。', '已记录这个不确定性。'),
    ('请记录样品编号。', '已经记录样品编号。'),
    ('请先记录样品编号。', '我们已经记录样品编号。'),
    ('请 先记录样品编号。', '记录了样品编号。'),
    ('先记录样品编号。', '记录样品编号了。'),
    ('先记录样品编号。', '我记录样品编号了。'),
    ('先记录样品编号。', '团队已记录样品编号。'),
    ('先核对编号，先记录这个不确定性。', '先核对编号，已经记录这个不确定性。'),
])
def test_unique_chinese_clause_head_request_cannot_become_explicit_completion(source, completed):
    with pytest.raises(RuntimeError, match='completed action'):
        validate_editorial_fidelity(source, completed)


@pytest.mark.parametrize('result', [
    '请先记录这个不确定性，暂时不要改成别的词。',
    '先记录此不确定性，暂不更改用词。',
    '请记录这个不确定性。',
    '应该先记录这个不确定性。',
    '把这个不确定性记下来，暂时不要改词。',
])
def test_legitimate_chinese_requests_and_unknown_synonyms_remain_editable(result):
    source = '先记录这个不确定性，暂时不要改成别的词。'
    assert validate_editorial_fidelity(source, result) == result


@pytest.mark.parametrize('source,result', [
    ('已经记录样品编号。', '已记录样品编号。'),
    ('之前记录过编号。请先记录结果。', '已经记录编号和结果。'),
    ('请记录编号，先记录结果。', '已经记录编号和结果。'),
    ('先记录编号。', '已经记录旧编号。请记录新编号。'),
    ('如果名称准确，先记录这个名字。', '如果名称准确，已经记录这个名字。'),
    ('先记录这个名字，如果已经确认。', '已记录这个名字。'),
    ('若有结果，先记录这个编号。', '若有结果，已记录编号。'),
    ('请先记录结果吗？', '已记录结果。'),
    ('先记录结果。', '已经记录结果了吗？'),
    ('先记录结果。', '已经记录结果吗。'),
    ('先记录结果。', '如果通过，已经记录结果。'),
    ('请不要记录结果。', '已记录结果。'),
    ('先不要记录结果。', '已经记录结果。'),
    ('请先记录不了的原因。', '已记录不了的原因。'),
    ('先记录结果。', '记录不了了。'),
    ('先记录结果。', '记录结果了再发送。'),
    ('先记录结果。', '记录了以后再发送。'),
    ('先记录结果。', '为什么已经记录结果？'),
    ('她说“先记录编号”。保留原话。', '她说“先记录编号”。请保留原话。'),
    ('先记录样品编号。', '我把样品编号写下来了。'),
])
def test_multiple_historical_conditional_question_negated_quoted_and_unknown_cases_are_not_inferred(source,result):
    assert validate_editorial_fidelity(source, result) == result


def test_chinese_pass_preserves_usage_identity_and_does_not_claim_actor_protection():
    result = UsageText('他提到 Zorvex，但不确定是否为正确名称。先记录此不确定性。', {'total_tokens': 642})
    source = '他提到 Zorvex，我不确定是不是这个名字。先记录此不确定性。'
    # Completion is not invented, so this narrow helper passes. Attribution
    # remains a model/prompt concern; no broad subject-count inference is added.
    assert validate_editorial_fidelity(source, result) is result


def test_success_returns_usage_object_by_identity_and_failure_leaves_it_untouched():
    usage = {'request_id': 'fixture', 'input_tokens': 40, 'output_tokens': 9, 'total_tokens': 49}
    result = UsageText('Please send the notes on Friday.', usage)
    assert validate_editorial_fidelity('Send the notes on Friday.', result) is result
    wrong = UsageText('We sent the notes on Friday.', usage)
    with pytest.raises(RuntimeError):
        validate_editorial_fidelity('Send the notes on Friday.', wrong)
    assert str(wrong) == 'We sent the notes on Friday.' and wrong.usage == usage


@pytest.mark.parametrize('source,result', [(None, 'text'), ('text', None), (b'text', 'text')])
def test_invalid_types_fail_without_echoing_payload(source, result):
    with pytest.raises(TypeError, match='must be text'):
        validate_editorial_fidelity(source, result)

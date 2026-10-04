"""Public timing fixtures; pure functions only, no speech/model requests."""
from itertools import permutations

import pytest

from murmur.dictation_corrections import prepare_corrections
from murmur.dictation_time import validate_dictation_time
from murmur.usage import UsageText


@pytest.mark.parametrize('old,new', list(permutations(('on', 'by', 'before', 'after'), 2)))
def test_known_unique_weekday_relation_changes_fail_in_both_directions(old, new):
    source = f'Send the notes {old} Friday. Keep the API private.'
    result = f'Send the notes {new} Friday. Keep the API private.'
    with pytest.raises(RuntimeError, match='schedule or deadline.*original text is preserved'):
        validate_dictation_time(source, result)


def test_observed_asr_exact_but_polish_deadline_drift_is_rejected():
    source = 'Today we reviewed the interface. Send the notes on Friday. Do not publish the result.'
    result = 'We reviewed the interface today. Please send the notes by Friday and do not publish the results.'
    with pytest.raises(RuntimeError, match='schedule or deadline'):
        validate_dictation_time(source, result)


@pytest.mark.parametrize('source,result', [
    ('Send notes ON Friday.', 'On FRIDAY, send the notes.'),
    ('Before Monday, test the API. Send notes by Friday.',
     'Send the notes by Friday; test the API before Monday.'),
    ('Send the notes on Friday. Keep the result private.',
     'Keep the result private. Please send the notes on Friday.'),
    ('Finish by Friday.', 'Finish\nby\nFriday!'),
    ('Please review on Sunday.', 'On Sunday: review, please.'),
])
def test_reordering_punctuation_case_and_sentence_style_are_allowed(source, result):
    assert validate_dictation_time(source, result) == result


@pytest.mark.parametrize('source,result', [
    ('Send the notes Friday.', 'Send the notes by Friday.'),
    ('Send the notes near Friday.', 'Send the notes on Friday.'),
    ('Send the notes around Friday.', 'Send the notes by Friday.'),
    ('No later than Friday, send notes.', 'Send the notes by Friday.'),
    ('Send the notes by next Friday.', 'Send the notes on next Friday.'),
    ('Send the notes on Fri.', 'Send the notes by Fri.'),
    ('Send the notes on Friday.', 'Send the notes tomorrow.'),
    ('Send the notes by Friday.', 'Send the notes Friday.'),
    ('Send the notes on Friday or Saturday.', 'Send the notes by Friday or Saturday.'),
    ('Send the notes on or before Friday.', 'Send the notes by Friday.'),
    ('Send the notes not on Friday.', 'Send the notes before Friday.'),
    ('Do this instead of on Friday.', 'Do this before Friday.'),
    ('Meet on Friday; send notes by Friday.', 'Send notes by Friday; meet on Friday.'),
    ('Send notes on Friday. Friday is also a separate appointment.',
     'Send notes by Friday. Friday is also a separate appointment.'),
    ('Run the routine on Friday.py.', 'Run the routine by Friday.py.'),
    ('Run the routine on Friday_check.', 'Run the routine by Friday_check.'),
    ('Run the routine on Friday2.', 'Run the routine by Friday2.'),
    ('Run the routine on Friday-check.', 'Run the routine by Friday-check.'),
])
def test_unknown_ambiguous_repeated_and_identifier_contexts_are_not_inferred(source, result):
    assert validate_dictation_time(source, result) == result


@pytest.mark.parametrize('source,result', [
    ('She said "send on Friday".', 'She said "send by Friday".'),
    ('她说“on Friday”，请保留原话。', '她说“by Friday”，请保留原话。'),
    ('She said ‘on Friday’.', 'She said ‘by Friday’.'),
])
def test_quotation_contents_are_left_to_the_separate_verbatim_guard(source, result):
    assert validate_dictation_time(source, result) == result


def test_quoted_weekday_does_not_hide_a_unique_external_time_change():
    source = 'The label is "Friday". Send the notes on Friday.'
    with pytest.raises(RuntimeError, match='schedule or deadline'):
        validate_dictation_time(source, 'The label is "Friday". Send the notes by Friday.')


def test_prepared_final_weekday_is_the_source_of_the_check():
    raw = 'Send the notes on Tuesday, sorry, Friday. Check the API tomorrow.'
    prepared = prepare_corrections(raw)
    assert prepared.edited_source == 'Send the notes on Friday. Check the API tomorrow.'
    assert validate_dictation_time(prepared.edited_source,
        'Check the API tomorrow. Send the notes on Friday.')
    with pytest.raises(RuntimeError, match='schedule or deadline'):
        validate_dictation_time(prepared.edited_source,
            'Check the API tomorrow. Send the notes by Friday.')
    assert raw == 'Send the notes on Tuesday, sorry, Friday. Check the API tomorrow.'


def test_usage_object_identity_and_metadata_survive_an_unchanged_result():
    usage = {'input_tokens': 90, 'output_tokens': 12, 'total_tokens': 102}
    result = UsageText('Please send the notes on Friday.', usage)
    assert validate_dictation_time('Send the notes on Friday.', result) is result
    assert result.usage == usage


def test_failure_does_not_rewrite_result_or_its_reported_usage():
    result = UsageText('Send the notes by Friday.', {'total_tokens': 42})
    with pytest.raises(RuntimeError):
        validate_dictation_time('Send the notes on Friday.', result)
    assert str(result) == 'Send the notes by Friday.' and result.usage == {'total_tokens': 42}


@pytest.mark.parametrize('source,result', [(None, 'text'), ('text', None), (b'text', 'text')])
def test_invalid_values_fail_without_echoing_data(source, result):
    with pytest.raises(TypeError, match='source and result must be text'):
        validate_dictation_time(source, result)

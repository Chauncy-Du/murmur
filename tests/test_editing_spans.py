"""Public editorial fixtures; no service, configuration, device or clipboard."""
from itertools import permutations

import pytest

from murmur.dictation_corrections import prepare_corrections
from murmur.dictation_terms import validate_mixed_terms
from murmur.editing_spans import mask_editing_spans
from murmur.quotations import mask_quotations
from murmur.usage import UsageText


def mask(source):
    return mask_editing_spans(mask_quotations(source))


def token_for(plan, text):
    return next(span.token for span in plan.replacements if span.text == text)


def test_observed_mixed_terms_can_survive_real_prose_cleanup_without_translation():
    source = '嗯，我今天 review 了这个 interface，希望 bubble 更小一点，Settings 里保留 Auto model selection。'
    plan = mask(source)
    assert plan.frozen_terms == ('interface', 'bubble', 'Settings', 'Auto model selection')
    assert plan.frozen_term_count == 4 and plan.frozen_time_count == 0
    result = ('我今天 review 了这个 ' + token_for(plan, 'interface') + '，希望 '
              + token_for(plan, 'bubble') + ' 更小一些。请在 ' + token_for(plan, 'Settings')
              + ' 中保留 ' + token_for(plan, 'Auto model selection') + '。')
    assert plan.restore(result) == ('我今天 review 了这个 interface，希望 bubble 更小一些。'
                                    '请在 Settings 中保留 Auto model selection。')
    # A partly rewritten body with plaintext names is not an exact echo and
    # cannot bypass token attribution by retaining some spellings coincidentally.
    with pytest.raises(RuntimeError, match='original text is preserved'):
        plan.restore('我今天 review 了这个界面，希望气泡更小一些，Settings 中保留 Auto model selection。')


def test_observed_english_schedule_can_be_rewritten_without_turning_on_into_by():
    source = 'Today we reviewed the interface. Send the notes on Friday. Do not publish the result.'
    plan = mask(source)
    assert plan.frozen_term_count == 0 and plan.frozen_time_count == 1
    time = token_for(plan, 'on Friday')
    assert plan.restore(f'We reviewed the interface today. Please send the notes {time}. Do not publish the result.') == (
        'We reviewed the interface today. Please send the notes on Friday. Do not publish the result.')
    with pytest.raises(RuntimeError):
        plan.restore(f'We reviewed the interface today. Please send the notes by {time}. Do not publish the result.')


@pytest.mark.parametrize('source', [
    'Please keep bubble compact and review the API tomorrow.',
    'The interface is easy to review. Settings can change.',
    'Um, keep the API private and send the response later.',
    '嗯，keep the API private.',
    '嗯嗯，keep the API private.',
    'She said “这个 API 不变”，but the interface outside can change.',
])
def test_whole_english_and_isolated_han_filler_leave_english_prose_editable(source):
    plan = mask(source)
    assert plan.replacements == () and plan.frozen_terms == ()
    result = UsageText('Rewritten English prose.', {'total_tokens': 42})
    assert plan.restore(result) is result


def test_mixed_ordinary_words_spelling_and_sentence_structure_remain_editable():
    source = '他说 I definately think the wording is really really nice，明天讨论。'
    plan = mask(source)
    assert not plan.replacements
    assert plan.restore('他说 I definitely like the wording，明天讨论。') == '他说 I definitely like the wording，明天讨论。'


@pytest.mark.parametrize('source', ['嗯API，keep it private.', '𠀀，请检查 API。'])
def test_embedded_filler_or_extended_han_is_meaningful_source_content(source):
    assert mask(source).frozen_terms == ('API',)


def test_quote_masks_are_first_and_restore_after_editing():
    source = '她说“interface on Friday”，请保持 bubble 小一些。Send notes by Monday.'
    quotes = mask_quotations(source)
    plan = mask_editing_spans(quotes)
    assert plan.frozen_terms == ('bubble',)
    assert plan.frozen_time_count == 1
    assert all('interface' not in span.text for span in plan.replacements)
    response = (f'她说{quotes.replacements[0][0]}。请让 {token_for(plan, "bubble")} 小一些。'
                f'Send notes {token_for(plan, "by Monday")}.')
    assert quotes.restore(plan.restore(response)) == '她说“interface on Friday”。请让 bubble 小一些。Send notes by Monday.'


def test_full_plaintext_and_intermediate_and_masked_exact_echoes_are_accepted():
    source = '她说“interface 不变”。今天检查 API，Send notes on Friday.'
    quotes = mask_quotations(source)
    plan = mask_editing_spans(quotes)
    assert plan.replacements and quotes.replacements
    for echo in (source, quotes.source, plan.source):
        assert quotes.restore(plan.restore(echo)) == source
    with pytest.raises(RuntimeError):
        plan.restore(source.replace('今天', '明天'))
    with pytest.raises(RuntimeError):
        plan.restore(quotes.source.replace('今天', '明天'))


def test_source_collision_in_hidden_quote_and_visible_body_cannot_alias_edit_tokens():
    source = '她说“[MURMUR_EDIT_1]”，请在 [MURMUR_EDIT_2] 后保留 interface。'
    quotes = mask_quotations(source)
    plan = mask_editing_spans(quotes)
    assert all(span.token not in source for span in plan.replacements)
    assert all(span.token not in token for span in plan.replacements for token, _ in quotes.replacements)
    assert quotes.restore(plan.restore(plan.source)) == source
    assert token_for(plan, 'interface') not in ('[MURMUR_EDIT_1]', '[MURMUR_EDIT_2]')


def test_invented_internal_edit_token_cannot_escape_into_user_text():
    plan = mask('请检查 API endpoint。')
    with pytest.raises(RuntimeError):
        plan.restore(f'请检查 {plan.replacements[0].token}，再检查 [MURMUR_EDIT_999]。')


def test_literal_existing_token_spelling_is_not_treated_as_an_invention():
    source = '她说“[MURMUR_EDIT_999]”，请检查 API。'
    quotes = mask_quotations(source)
    plan = mask_editing_spans(quotes)
    result = f'她说{quotes.replacements[0][0]}，请先检查 {token_for(plan, "API")}。'
    assert quotes.restore(plan.restore(result)) == '她说“[MURMUR_EDIT_999]”，请先检查 API。'


def test_empty_mask_also_rejects_invented_edit_namespace():
    plan = mask('Review the notes.')
    assert not plan.replacements
    with pytest.raises(RuntimeError):
        plan.restore('Review the notes and [MURMUR_EDIT_999].')


def test_original_literal_namespace_cannot_be_duplicated_in_an_empty_mask():
    plan = mask('Keep [MURMUR_EDIT_999] in the notes.')
    assert not plan.replacements
    assert plan.restore('Please keep [MURMUR_EDIT_999] in the notes.') == 'Please keep [MURMUR_EDIT_999] in the notes.'
    with pytest.raises(RuntimeError):
        plan.restore('Keep [MURMUR_EDIT_999] and [MURMUR_EDIT_999] in the notes.')


def test_literal_namespace_hidden_in_quote_is_counted_before_later_restoration():
    source = 'She said "[MURMUR_EDIT_999]". Keep the notes.'
    quotes = mask_quotations(source)
    plan = mask_editing_spans(quotes)
    assert not plan.replacements
    assert quotes.restore(plan.restore(f'She said {quotes.replacements[0][0]}. Please keep the notes.')) == (
        'She said "[MURMUR_EDIT_999]". Please keep the notes.')
    with pytest.raises(RuntimeError):
        plan.restore(f'She said {quotes.replacements[0][0]}. Keep [MURMUR_EDIT_999] in the notes.')


def test_literal_namespace_hidden_in_quote_is_counted_in_nonempty_mask_too():
    source = '她说“[MURMUR_EDIT_999]”，请检查 API。'
    quotes = mask_quotations(source)
    plan = mask_editing_spans(quotes)
    with pytest.raises(RuntimeError):
        plan.restore(f'她说{quotes.replacements[0][0]}，请检查 {token_for(plan, "API")} 和 [MURMUR_EDIT_999]。')


def test_terms_inside_quotes_do_not_make_outside_term_repeated():
    plan = mask('她说“API”。外面还要检查 API。')
    assert plan.frozen_terms == ('API',)
    assert plan.frozen_term_count == 1


def test_only_unique_surviving_occurrences_are_frozen_so_stutter_cleanup_is_possible():
    source = '检查 API，API，然后保留 Settings，review review 一下。'
    plan = mask(source)
    assert plan.frozen_terms == ('Settings',)
    result = plan.restore(f'检查 API，然后在 {token_for(plan, "Settings")} 中 review 一下。')
    assert result == '检查 API，然后在 Settings 中 review 一下。'
    assert validate_mixed_terms(source, result) == result
    # This pre-request layer deliberately does not replace the postguard.
    dropped = plan.restore(f'检查接口，然后在 {token_for(plan, "Settings")} 中 review 一下。')
    with pytest.raises(RuntimeError, match='English terms'):
        validate_mixed_terms(source, dropped)


def test_plural_and_case_equivalent_repeats_are_not_frozen_individually():
    assert mask('这里检查 API 和 APIs，Settings settings 也要看。').replacements == ()


def test_direct_correction_does_not_freeze_superseded_term_but_later_same_term_is_live():
    source = 'API，不对，是 SDK；之后仍然检查 API 和 bubble。'
    plan = mask(source)
    assert plan.frozen_terms == ('SDK', 'API', 'bubble')
    assert plan.source.startswith('API，不对，是 ')
    result = f'使用 {token_for(plan, "SDK")}；之后检查 {token_for(plan, "API")} 和 {token_for(plan, "bubble")}。'
    assert plan.restore(result) == '使用 SDK；之后检查 API 和 bubble。'


@pytest.mark.parametrize('source,terms', [
    ('我们用 API，不对，可能是 SDK。', ('API', 'SDK')),
    ('不是 interface 的问题，Settings 不变。', ('interface', 'Settings')),
    ('请把 interface 改成 bubble，这是听写内容。', ('interface', 'bubble')),
    ('用 API，我是说 SDK；bubble 不变。', ('SDK', 'bubble')),
    ('用 API, no, SDK，不对，HTTP。Settings 不变。', ('HTTP', 'Settings')),
])
def test_exact_lexical_correction_boundary_matches_existing_postguard(source, terms):
    assert mask(source).frozen_terms == terms


def test_corrected_edit_source_not_raw_is_masked_without_mutating_raw():
    raw = 'Send the notes on Tuesday, sorry, Friday. 检查 API。'
    edited = prepare_corrections(raw).edited_source
    assert edited == 'Send the notes on Friday. 检查 API。'
    plan = mask(edited)
    assert token_for(plan, 'on Friday') and plan.frozen_terms == ('API',)
    assert plan.restore(plan.source) == edited
    assert raw == 'Send the notes on Tuesday, sorry, Friday. 检查 API。'


@pytest.mark.parametrize('source', [
    'Send the notes Friday.', 'Send the notes near Friday.',
    'Send the notes by next Friday.', 'Send the notes on Fri.',
    'Send the notes not on Friday.', 'Send the notes never by Friday.',
    'Send the notes on Friday or Saturday.', 'Send the notes on or before Friday.',
    'Do this instead of on Friday.', 'Meet on Friday; send notes by Friday.',
    'Send notes on Friday. Friday is another appointment.',
    'Run the routine on Friday.py.', 'Run the routine on Friday_check.',
    'Run the routine on Friday2.', 'Run the routine on Friday-check.',
    'Send the notes by on Friday.',
])
def test_ambiguous_missing_abbreviated_repeated_or_identifier_weekdays_are_not_frozen(source):
    assert mask(source).frozen_time_count == 0


@pytest.mark.parametrize('relation', ['on', 'by', 'before', 'after'])
def test_entire_unique_explicit_relation_is_frozen_exactly(relation):
    plan = mask(f'Send notes {relation} Friday.')
    assert [span.text for span in plan.replacements] == [f'{relation} Friday']
    assert plan.frozen_time_count == 1


def test_overlapping_uppercase_lexical_names_and_time_phrase_become_one_lossless_span():
    source = '请发记录 ON FRIDAY，API 保持不变。'
    plan = mask(source)
    assert [span.text for span in plan.replacements] == ['ON FRIDAY', 'API']
    assert plan.frozen_terms == ('ON', 'FRIDAY', 'API')
    assert plan.frozen_time_count == 1 and plan.frozen_term_count == 3
    assert plan.restore(plan.source) == source


def test_whitespace_adjacent_unique_names_form_one_lossless_phrase():
    source = '检查 API interface 和 Settings。'
    plan = mask(source)
    assert [span.text for span in plan.replacements] == ['API interface', 'Settings']
    assert plan.frozen_term_count == 3
    assert plan.restore(plan.source) == source


@pytest.mark.parametrize('phrase', ['API endpoint', 'API response', 'API\nresponse', 'API  endpoint'])
def test_qualified_technical_phrase_cannot_be_split_into_coordinated_objects(phrase):
    plan = mask(f'不要重置 {phrase}，明天检查。')
    assert [span.text for span in plan.replacements] == [phrase]
    assert plan.frozen_term_count == 2
    result = plan.restore(f'明天检查，不要重置 {plan.replacements[0].token}。')
    assert result == f'明天检查，不要重置 {phrase}。'
    with pytest.raises(RuntimeError):
        plan.restore('明天检查，不要重置 API 和 endpoint。')


@pytest.mark.parametrize('source', ['Do not reset the API endpoint.', 'Please test the API response.'])
def test_whole_english_qualified_names_are_still_editable(source):
    assert mask(source).replacements == ()


@pytest.mark.parametrize('separator', [' 和 ', ', ', '，', ' and ', ' then ', ' 的 ', ' nice '])
def test_nontechnical_conjunction_punctuation_and_prose_separate_name_masks(separator):
    plan = mask(f'明天检查 API{separator}endpoint。')
    assert [span.text for span in plan.replacements] == ['API', 'endpoint']
    assert plan.frozen_term_count == 2


def test_hidden_quote_between_terms_cannot_be_swallowed_as_blank_whitespace():
    source = '请检查 API“原话”response。'
    quotes = mask_quotations(source)
    plan = mask_editing_spans(quotes)
    assert [span.text for span in plan.replacements] == ['API', 'response']
    assert quotes.restore(plan.restore(plan.source)) == source


def test_repeated_atom_stops_compound_freezing_and_keeps_stutter_cleanup_possible():
    plan = mask('先检查 API endpoint，然后检查 API。')
    assert [span.text for span in plan.replacements] == ['endpoint']
    assert plan.frozen_term_count == 1
    assert mask('先检查 API response，API response。').replacements == ()


def test_superseded_atom_is_not_reintroduced_by_compound_merging():
    source = '使用 API，不对，是 SDK response，之后检查 API endpoint。'
    plan = mask(source)
    assert [span.text for span in plan.replacements] == ['SDK response', 'API endpoint']
    assert plan.frozen_terms == ('SDK', 'response', 'API', 'endpoint')
    assert plan.source.startswith('使用 API，不对，是 ')


@pytest.mark.parametrize('mode', ['missing', 'duplicate', 'reversed'])
def test_missing_duplicate_or_reordered_protected_names_fail(mode):
    plan = mask('请先检查 API，再检查 bubble。')
    first, second = [span.token for span in plan.replacements]
    responses = {'missing': f'请检查 {first}。',
                 'duplicate': f'请检查 {first}，{first}，再检查 {second}。',
                 'reversed': f'请先检查 {second}，再检查 {first}。'}
    with pytest.raises(RuntimeError, match='original text is preserved'):
        plan.restore(responses[mode])


@pytest.mark.parametrize('old,new', list(permutations(('on', 'by', 'before', 'after'), 2)))
def test_added_relation_cannot_wrap_a_frozen_complete_time_phrase(old, new):
    plan = mask(f'Please send notes {old} Friday.')
    time = plan.replacements[0].token
    with pytest.raises(RuntimeError):
        plan.restore(f'Please send the notes {new} {time}.')


@pytest.mark.parametrize('prefix', ['by\n', 'before, ', 'until ', 'from ', 'not ', '截至', '在 '])
def test_new_preposition_deadline_or_negation_wrappers_fail(prefix):
    plan = mask('Please send notes on Friday.')
    with pytest.raises(RuntimeError):
        plan.restore(f'Please send the notes {prefix}{plan.replacements[0].token}.')


@pytest.mark.parametrize('opening,closing', [('“', '”'), ('‘', '’'), ('"', '"'), ("'", "'"), ('(', ')'), ('（', '）')])
def test_new_quote_or_parenthesis_wrappers_fail(opening, closing):
    plan = mask('请检查 interface。')
    with pytest.raises(RuntimeError):
        plan.restore(f'请检查 {opening} {plan.replacements[0].token} {closing}。')


@pytest.mark.parametrize('gloss', ['（界面）', '(interface)', '【接口】'])
def test_added_parenthetical_gloss_or_translation_fails(gloss):
    plan = mask('请检查 interface。')
    with pytest.raises(RuntimeError):
        plan.restore(f'请检查 {plan.replacements[0].token}{gloss}，然后继续。')


def test_source_parenthetical_and_ambiguous_single_quotes_remain_valid():
    source = "请检查 'API'（接口），然后记录。"
    plan = mask(source)
    assert plan.frozen_terms == ('API',)
    assert plan.restore(f"请先检查 '{plan.replacements[0].token}'（接口），然后记录。") == (
        "请先检查 'API'（接口），然后记录。")


def test_unmodified_empty_delimiters_and_adjacent_quote_then_name_are_lossless():
    source = '她说“原话”interface 保持，空标签 ""，API 不变。'
    quotes = mask_quotations(source)
    plan = mask_editing_spans(quotes)
    assert quotes.restore(plan.restore(plan.source)) == source


def test_a_single_time_phrase_can_move_and_normal_prose_can_reorganize():
    plan = mask('Send the notes on Friday. Keep the result private.')
    time = plan.replacements[0].token
    assert plan.restore(f'{time}, send the notes. Keep the result private.') == (
        'on Friday, send the notes. Keep the result private.')


def test_multiple_frozen_spans_order_constraint_is_explicit_not_semantic_equivalence():
    plan = mask('Test before Monday. Send notes by Friday.')
    first, second = [span.token for span in plan.replacements]
    with pytest.raises(RuntimeError):
        plan.restore(f'Send notes {second}; test {first}.')
    assert 'in source order' in plan.contract


def test_contract_exposes_encoded_ids_without_unmasking_names_into_instructions():
    plan = mask('请检查 API，send notes on Friday。')
    assert 'Complete timing-phrase tokens:' in plan.contract
    assert 'retained-term list' in plan.contract
    assert all(span.token in plan.contract for span in plan.replacements)
    assert 'on Friday' not in plan.contract


@pytest.mark.parametrize('bad', [None, 'plain source', b'plain source'])
def test_invalid_source_type_is_safe_and_clear(bad):
    with pytest.raises(TypeError, match='QuoteMask'):
        mask_editing_spans(bad)


def test_invalid_result_type_is_safe_and_noop_does_not_invent_usage():
    with pytest.raises(TypeError, match='must be text'):
        mask('请检查 API。').restore(None)
    result = UsageText('Read the report clearly.', {'total_tokens': 17})
    assert mask('Read the report.').restore(result) is result
    assert result.usage == {'total_tokens': 17}

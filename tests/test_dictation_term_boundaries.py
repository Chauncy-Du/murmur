"""Synthetic editorial cases: names stay names, prose can be rewritten."""
import copy

import pytest

from murmur import providers
from murmur.dictation_terms import mixed_term_plan
from murmur.storage import DEFAULTS
from murmur.usage import UsageText


@pytest.mark.parametrize('source,result', [
    ('我们保留英文 I definately think the wording is really nice。','我们保留英文 I definitely think the wording is nice。'),
    ('他说 I am going to take a look at the report，明天讨论。','他说 I will review the report，明天讨论。'),
    ('我们先 review the API，再看 interface。','我们先 reviewed the API，再看 interface。'),
    ('它提供两个 API，Settings 不变。','它提供两个 APIs，Settings 不变。'),
    ('我们要先做 calibration，检查 drift。','我们要先做 calibration，检查 drift。'),
    ('设置 Auto model selection，然后看 API。','设置 auto  model selection，然后看 api。'),
    ('他说 It is well-written and straightforward，明天再读。','他说 It reads clearly，明天再读。'),
    ('这句英语 It applies to e.g. simple reports，我们再讨论。','这句英语 It applies to simple reports for example，我们再讨论。'),
])
def test_ordinary_prose_spelling_inflection_and_structure_can_change(source,result):
    assert providers.preserve_mixed_dictation_terms(source,result)==result


@pytest.mark.parametrize('source,result', [
    ('bubble 不要变大，明天，不对，后天检查 API。','气泡不要变大，后天检查 API。'),
    ('不是 interface 的问题，Settings 中保留 API。','不是界面的问题，Settings 中保留 API。'),
    ('请把 interface 改成 bubble，这是听写内容。','请把界面改成 bubble，这是听写内容。'),
    ('我们将 API，不对，先处理报告。Settings 不变。','我们先处理报告。Settings 不变。'),
    ('我们用 API，不对，可能是 SDK。','我们用 SDK。'),
    ('这里是 SDK API，不对，是 UI。','这里是 UI。'),
    ('先检查 MyWidget 和 db.read，后天讨论。','先检查组件和读取函数，后天讨论。'),
    ('我们检查 calibration，再看 drift。','我们检查校准，再看漂移。'),
    ('Settings 中使用 Auto model selection。','Settings 中使用 Auto selection。'),
    ('保留 API，不是删除 API。','保留接口。'),
])
def test_negation_unrelated_or_ambiguous_corrections_never_waive_other_names(source,result):
    with pytest.raises(RuntimeError,match='English terms.*original text is preserved'):
        providers.preserve_mixed_dictation_terms(source,result)


@pytest.mark.parametrize('source,result', [
    ('材料用 SiO2，不对，是 SiNx；API 不变。','材料用 SiNx；API 不变。'),
    ('界面用 bubble，不对，interface，Settings 保持。','界面用 interface，Settings 保持。'),
    ('用 API, sorry, SDK；bubble 保持小一些。','用 SDK；bubble 保持小一些。'),
    ('用 API, no, SDK，不对，HTTP。Settings 不变。','用 HTTP。Settings 不变。'),
    ('先用 API，我是说 SDK，interface 不变。','先用 SDK，interface 不变。'),
    ('先用 API，不是，是 SDK，interface 不变。','先用 SDK，interface 不变。'),
])
def test_only_direct_replacement_allows_old_name_to_be_removed(source,result):
    assert providers.preserve_mixed_dictation_terms(source,result)==result


@pytest.mark.parametrize('source,result', [
    ('用 API，不对，是 SDK，后面的 API 还要检查。','用 SDK。'),
    ('bubble，不对，interface。Settings 还是不变。','interface。'),
    ('材料用 SiO2，不对，SiNx；bubble 保持小一些。','材料用 SiNx；气泡保持小一些。'),
])
def test_other_occurrences_and_neighboring_tasks_remain_protected(source,result):
    with pytest.raises(RuntimeError,match='English terms'):
        providers.preserve_mixed_dictation_terms(source,result)


def test_plan_keeps_repeated_name_required_if_only_one_occurrence_is_corrected():
    plan=mixed_term_plan('API，不对，是 SDK；之后仍然检查 API 和 bubble。')
    assert plan.superseded==('API',)
    assert plan.required==('SDK','API','bubble')


def test_identifiers_and_short_code_switch_names_are_covered_but_plain_prose_is_not():
    plan=mixed_term_plan('在 MyWidget 调用 db.read，用 SiNx，检查 calibration 和 drift；英文 I definitely think it reads well。')
    assert plan.required==('MyWidget','db.read','SiNx','calibration','drift')
    assert mixed_term_plan('英文 We will calibrate the equipment tomorrow；明天讨论。').required==()
    assert mixed_term_plan('使用 fun-asr-realtime 和 sensevoice-small，明天讨论。').required==('fun-asr-realtime','sensevoice-small')


def test_validator_does_not_claim_semantics_of_unknown_plain_lowercase_terms():
    # Unknown names still have prompt protection. Lexical code must not invent
    # a dictionary or refuse ordinary English synonyms as if they were names.
    assert mixed_term_plan('我们说 straightforward wording，稍后修改。').required==()


def test_success_preserves_usage_object_without_synthetic_tokens():
    result=UsageText('保留 API 和 interface。',{'request_id':'fixture','total_tokens':42})
    assert providers.preserve_mixed_dictation_terms('保留 API 和 interface。',result) is result


def test_rejected_term_loss_still_publishes_real_usage_and_does_not_retry(monkeypatch):
    cfg=copy.deepcopy(DEFAULTS);cfg.update(demo=False,polish=True)
    calls=[];usage=[]
    def reply(messages,cfg,key,cancel=None,usage_sink=None,*args,**kwargs):
        calls.append(messages)
        metadata={'request_id':'fixture','total_tokens':42}
        usage_sink(metadata)
        return UsageText('这个 API 气泡需要更小。',metadata)
    monkeypatch.setattr(providers,'_chat_completion',reply)
    with pytest.raises(RuntimeError,match='protected terms.*original text is preserved'):
        providers.transform('这个 API bubble 需要更小，明天，不对，后天讨论。','听写',cfg,usage_sink=usage.append)
    assert len(calls)==1 and usage==[{'request_id':'fixture','total_tokens':42}]

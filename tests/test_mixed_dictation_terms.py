import copy
import pytest
from murmur import providers
from murmur.storage import DEFAULTS
from murmur.usage import UsageText


def test_mixed_technical_term_translation_is_rejected_before_final_result():
    source='我 review 了 interface，希望 bubble 更小。'
    with pytest.raises(RuntimeError,match='English terms.*original text is preserved'):
        providers.preserve_mixed_dictation_terms(source,'我 review 了 interface，希望气泡更小。')


def test_repeated_terms_case_and_function_words_do_not_force_original_syntax():
    source='嗯，在 Settings 里面，里面 please review the API，API 然后 Auto model selection。'
    result=UsageText('在 Settings 中 review API，再使用 auto model selection。',{'total_tokens':12})
    assert providers.preserve_mixed_dictation_terms(source,result) is result


def test_explicit_correction_can_remove_superseded_terms():
    source='材料是 SiO2，不对，是 SiNx。'
    assert providers.preserve_mixed_dictation_terms(source,'材料是 SiNx。')=='材料是 SiNx。'


@pytest.mark.parametrize('source,result',[
    ('Please keep the bubble compact.','Keep the bubble compact.'),
    ('今天开会。','今天开会。'),
])
def test_lexical_guard_only_applies_to_mixed_dictation(source,result):
    assert providers.preserve_mixed_dictation_terms(source,result)==result


def test_dictation_pipeline_blocks_term_loss_but_explicit_translation_allows_it(monkeypatch):
    cfg=copy.deepcopy(DEFAULTS);cfg.update(demo=False,polish=True)
    monkeypatch.setattr(providers,'_chat_completion',lambda *a,**k:'我希望 API 气泡更小。')
    with pytest.raises(RuntimeError,match='protected terms.*original text is preserved'):
        providers.transform('我希望 API bubble 更小。','听写',cfg)
    cfg['language']='Chinese'
    assert providers.transform('I want a smaller API bubble.','翻译',cfg)=='我希望 API 气泡更小。'

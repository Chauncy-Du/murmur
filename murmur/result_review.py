"""One-call editorial review metadata; no claimed ASR accuracy percentage."""
from dataclasses import dataclass
import json

from .usage import UsageText


@dataclass(frozen=True)
class ReviewAssessment:
    needs_review: bool = True
    uncertain_spans: tuple[str, ...] = ()
    assessed: bool = False


class ReviewedText(UsageText):
    def __new__(cls, value, usage=None, review=None):
        obj=super().__new__(cls,value,usage)
        obj.review=review or ReviewAssessment()
        return obj


def review_contract(chinese=False):
    if chinese:
        return ('最终输出格式（覆盖前面的“只输出正文”格式要求，编辑和保真规则仍适用）：'
                '返回一个 JSON 对象，只有 text、needs_review、uncertain_spans 三个字段，不加代码围栏。'
                'text 是完整整理正文；needs_review 是布尔值；uncertain_spans 是正文中拿不准的词或片段组成的字符串数组。'
                '判断的是你是否拿不准识别措辞、词义、纠错范围或指代，而不是原文事实是否确定。'
                '有无法确认的识别词、含混指代、冲突要求或缺失信息时 needs_review=true，并保留原词。'
                '没有这些疑点才返回 false 和空数组。普通语气词、明确更正、正常问题及原文“可能”等事实上的不确定性本身不算识别疑点。'
                'uncertain_spans 只填 text 中实际保留的片段，冻结标记仍用标记本身。不要为给出 false 而猜测、删除疑点或简化正文。')
    return ('Final output format (overrides earlier text-only format rules; all editing and fidelity rules still apply): '
            'Return one JSON object with exactly text, needs_review, uncertain_spans; no code fence. '
            'text is the complete edited prose; needs_review is a boolean; uncertain_spans is an array of uncertain words or spans retained in text. '
            'Assess ambiguity in recognized wording, meaning, correction scope or references, not whether the source facts are certain. '
            'Use true for unresolved recognition, unclear references, conflicting requests or missing information; retain the uncertain wording. '
            'Use false and an empty array only when there is no such ambiguity. Fillers, clear corrections, ordinary questions and factual uncertainty such as may do not themselves require review. '
            'Each uncertain span must occur in text; retain frozen IDs as IDs. Never guess, omit ambiguity or shorten content to justify false.')


def parse_review_result(result, source=''):
    value=str(result).strip()
    usage=getattr(result,'usage',None)
    # Older endpoints/plain-text responses remain recoverable, but cannot
    # assert that a review assessment was performed.
    if value==source.strip():return ReviewedText(value,usage)
    if value.startswith('```') and value.endswith('```'):
        value=value.split('\n',1)[-1].rsplit('```',1)[0].strip()
    try:data=json.loads(value)
    except (ValueError,TypeError):
        if value.startswith('{') and '"needs_review"' in value:
            raise RuntimeError('The model returned an invalid review result. Your original text is preserved.') from None
        return ReviewedText(str(result),usage)
    if not isinstance(data,dict) or not {'text','needs_review'}.issubset(data):
        return ReviewedText(str(result),usage)
    text=data.get('text')
    if not isinstance(text,str) or not text.strip():
        raise RuntimeError('The model returned an empty review result. Your original text is preserved.')
    spans=data.get('uncertain_spans')
    valid=(set(data)=={'text','needs_review','uncertain_spans'} and type(data['needs_review']) is bool
           and isinstance(spans,list) and len(spans)<=8
           and all(isinstance(span,str) and 0<len(span)<=120 and span in text for span in spans))
    review=(ReviewAssessment(data['needs_review'] or bool(spans),tuple(spans),True)
            if valid else ReviewAssessment())
    return ReviewedText(text,usage,review)


def restore_review(review,prepared):
    spans=[]
    for original in review.uncertain_spans:
        span=original
        for item in prepared.editing_mask.replacements:
            span=span.replace(item.token,item.text)
        for token,text in prepared.quote_mask.replacements:
            span=span.replace(token,text)
        spans.append(span)
    return ReviewAssessment(review.needs_review,tuple(spans),review.assessed)

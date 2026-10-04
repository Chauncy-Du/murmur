"""Bounded first-person perspective checks for original-language editing.

Extract only a unique, explicitly scoped first-person epistemic statement in
each known family. Clear quoted spans are excluded using the existing parser.
This is neither global pronoun counting nor a general attribution parser:
ordinary actions, unknown synonyms, questions, conditions, reported/nested
claims and multiple same-family statements are not inferred. Source must be
the independently corrected editing material, never a modified raw snapshot.

Natural predicate paraphrases and a shared subject in adjacent coordinated
clauses remain editable. Subject inheritance stops at a sentence/semicolon,
an unknown intervening clause or a new/reported participant. No text is fixed
and no missing clause or arbitrary semantic drift can be detected reliably.
The plan contains labels only, suitable for request-side positive guidance;
successful validation returns the exact caller-owned result object.
"""
from dataclasses import dataclass
import re

from .quotations import outside_quotations


_FAMILIES = frozenset(('uncertainty', 'not_confirmed', 'not_decided'))
_PARTICIPANTS = frozenset(('我', '我们', 'I', 'we'))
_ERROR = ('The model changed the participant perspective. Your original text is preserved; '
          'copy it or retry with cleanup off.')
_SENTENCES = re.compile(r'[。！？.!?；;\n]')
_CLAUSES = re.compile(r'[,，]|\b(?:but|and|however)\b|但是|不过|但', re.I)
_CONDITIONAL = re.compile(r'如果|假如|要是|一旦|只要|除非|\b(?:if|unless|suppose|provided)\b', re.I)
_REPORT = re.compile(r'说|表示|声称|认为|觉得|告诉|提到|\b(?:said|says|say|told|think|believe|reported|according)\b', re.I)
_CN_ACTOR = r'我们|我|你们|他们|她们|你|他|她|大家|团队'
_CN_ADVERBS = r'(?:目前|现在|仍然|暂时|确实|其实|尚|仍|还|也|并|都|\s)*'
_CN_DIRECT = re.compile(r'\A\s*(?P<actor>' + _CN_ACTOR + r')' + _CN_ADVERBS + r'\Z')
_CN_HEAD = re.compile(r'\A\s*(?P<actor>' + _CN_ACTOR + r')(?!的|方|国|与|和)')
_CN_EMPTY = re.compile(r'\A' + _CN_ADVERBS + r'\Z')
_CN_NEUTRAL = re.compile(r'\A\s*(?:这个|该|此)?(?:结果|状态|结论|决定|情况)' + _CN_ADVERBS + r'\Z')
_CN_NEGATIVE = r'(?:尚未|仍未|还没(?:有)?|没有|未)\s*'
_CN_PASSIVE = r'(?:(?:由|被)(?P<cn_passive>我们|我|你们|他们|她们|你|他|她)\s*)?'
_PATTERNS = (
    ('uncertainty', 'zh', re.compile(r'(?:尚不|仍不|还不|不(?:太|很)?)(?:确定|清楚|确信)')),
    ('not_confirmed', 'zh', re.compile(_CN_NEGATIVE + _CN_PASSIVE + r'确认')),
    ('not_decided', 'zh', re.compile(_CN_NEGATIVE + r'(?:(?:做出|作出)\s*)?决定')),
    ('uncertainty', 'en', re.compile(r"\b(?:not\s+(?:yet\s+)?(?:sure|certain)|(?:isn|aren|wasn|weren)['’]t\s+(?:yet\s+)?(?:sure|certain)|uncertain|unsure)\b", re.I)),
    ('not_confirmed', 'en', re.compile(r"\b(?:not\s+(?:yet\s+)?(?:been\s+)?confirmed|(?:haven|hasn|hadn)['’]t\s+(?:yet\s+)?confirmed|unconfirmed)\b", re.I)),
    ('not_decided', 'en', re.compile(r"\b(?:(?:not\s+(?:yet\s+)?|(?:haven|hasn|hadn)['’]t\s+(?:yet\s+)?)(?:decided|made\s+(?:a|any)\s+(?:final\s+)?decision)|no\s+(?:final\s+)?decision\s+has\s+been\s+made)\b", re.I)),
)
_EN_ACTOR = r'I|we|you|he|she|they|it'
_EN_AUX = r'(?:(?:am|are|is|was|were|have|has|had|remain|remains|still|also|currently|now)\s+)*'
_EN_DIRECT = re.compile(r'\A\s*(?P<actor>' + _EN_ACTOR + r")(?:(?:['’](?:m|re|ve|s))\s+|\s+)" + _EN_AUX + r'\Z', re.I)
_EN_HEAD = re.compile(r'\A\s*(?P<actor>' + _EN_ACTOR + r')\b', re.I)
_EN_EMPTY = re.compile(r'\A\s*' + _EN_AUX + r'\Z', re.I)
_EN_NEUTRAL = re.compile(r'\A\s*(?:(?:the|a|this|that)\s+)?(?:result|decision|outcome|status|test|report)\s+' + _EN_AUX + r'\Z', re.I)
_EN_PASSIVE = re.compile(r'\A\s+by\s+(?P<actor>us|me|you|them|him|her)\b', re.I)
_CN_AMBIGUOUS = re.compile(r'并非|不是|未必|吗|么|呢')
_EN_AMBIGUOUS = re.compile(r'\b(?:not\s+that|never\s+said|might|may|could|would|should)\b', re.I)


@dataclass(frozen=True)
class ParticipantClaim:
    participant: str
    family: str

    def __post_init__(self):
        if self.participant not in _PARTICIPANTS or self.family not in _FAMILIES:
            raise TypeError('Participant plan contains an unsupported claim.')


@dataclass(frozen=True)
class ParticipantPlan:
    claims: tuple[ParticipantClaim, ...] = ()

    def __post_init__(self):
        if not isinstance(self.claims, tuple) or not all(isinstance(claim, ParticipantClaim) for claim in self.claims):
            raise TypeError('Participant claims must be an immutable tuple of ParticipantClaim values.')


@dataclass(frozen=True)
class _Occurrence:
    family: str
    participant: str | None
    reliable: bool


def _canonical(actor):
    if actor.casefold() == 'i':
        return 'I'
    if actor.casefold() == 'we':
        return 'we'
    return actor


def _occurrences(text):
    occurrences = []
    prose = outside_quotations(text)
    cursor = 0
    for boundary in list(_SENTENCES.finditer(prose)) + [None]:
        end = boundary.start() if boundary else len(prose)
        sentence = prose[cursor:end]
        question = bool(boundary and boundary.group() in ('?', '？')) or bool(re.search(r'(?:吗|么|呢)\s*\Z', sentence))
        conditional = bool(_CONDITIONAL.search(sentence))
        inherited = None
        prior_clause = False
        for chunk in _CLAUSES.split(sentence):
            chunk = chunk.strip()
            if not chunk:
                continue
            matches = sorted((match.start(), family, locale, match)
                for family, locale, pattern in _PATTERNS for match in pattern.finditer(chunk))
            head = _CN_HEAD.match(chunk) or _EN_HEAD.match(chunk)
            next_inherited = _canonical(head['actor']) if head and not _REPORT.search(chunk) else None
            if next_inherited not in _PARTICIPANTS:
                next_inherited = None
            for _, family, locale, match in matches:
                left = chunk[:match.start()]
                ambiguous = question or conditional or bool(_REPORT.search(left))
                ambiguous = ambiguous or bool((_CN_AMBIGUOUS if locale == 'zh' else _EN_AMBIGUOUS).search(left))
                actor = None
                reliable = False
                if not ambiguous:
                    if locale == 'zh' and match.groupdict().get('cn_passive'):
                        actor = match['cn_passive']
                        reliable = bool(_CN_NEUTRAL.fullmatch(left) or _CN_EMPTY.fullmatch(left))
                    else:
                        direct = (_CN_DIRECT if locale == 'zh' else _EN_DIRECT).fullmatch(left)
                        empty = (_CN_EMPTY if locale == 'zh' else _EN_EMPTY).fullmatch(left)
                        neutral = (_CN_NEUTRAL if locale == 'zh' else _EN_NEUTRAL).fullmatch(left)
                        if direct:
                            actor = _canonical(direct['actor']); reliable = True
                        elif empty:
                            actor = inherited
                            reliable = inherited is not None or not prior_clause
                        elif neutral:
                            reliable = True
                        if locale == 'en':
                            passive = _EN_PASSIVE.match(chunk[match.end():])
                            if passive and (reliable or not left.strip()):
                                actor = {'us':'we', 'me':'I'}.get(passive['actor'].casefold(), passive['actor'].casefold())
                                reliable = True
                occurrences.append(_Occurrence(family, actor, reliable))
            inherited = next_inherited
            prior_clause = True
        cursor = boundary.end() if boundary else end
    return tuple(occurrences)


def participant_plan(corrected_source):
    """Extract only unique, clear first-person epistemic labels, never raw text."""
    if not isinstance(corrected_source, str):
        raise TypeError('Participant source must be text.')
    occurrences = _occurrences(corrected_source)
    claims = []
    for family in ('uncertainty', 'not_confirmed', 'not_decided'):
        candidates = [item for item in occurrences if item.family == family]
        if len(candidates) == 1 and candidates[0].reliable and candidates[0].participant in _PARTICIPANTS:
            claims.append(ParticipantClaim(candidates[0].participant, family))
    return ParticipantPlan(tuple(claims))


def validate_participant_fidelity(plan_or_source, result):
    """Reject clear perspective loss; unknown/multiple scopes remain unclassified."""
    if not isinstance(result, str):
        raise TypeError('Participant result must be text.')
    plan = participant_plan(plan_or_source) if isinstance(plan_or_source, str) else plan_or_source
    if not isinstance(plan, ParticipantPlan):
        raise TypeError('Participant source must be text or a ParticipantPlan.')
    occurrences = _occurrences(result)
    for claim in plan.claims:
        if claim.participant not in _PARTICIPANTS or claim.family not in _FAMILIES:
            raise TypeError('Participant plan contains an unsupported claim.')
        candidates = [item for item in occurrences if item.family == claim.family]
        if len(candidates) == 1 and candidates[0].reliable and candidates[0].participant != claim.participant:
            raise RuntimeError(_ERROR)
    return result

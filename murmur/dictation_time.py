"""A narrow timing check for original-language editorial output.

Compare only explicit on/by/before/after + full English weekday phrases when
that weekday occurs once in each text. The caller supplies the independently
prepared correction_plan.edited_source, never overwrites the raw transcript,
and enables this guard only for dictation/refinement, not translation.

Unknown phrasing, missing relations, alternatives, negated relations and
repeated weekdays are deliberately left alone. This is not a semantic parser
or a guarantee that all dates, chronology or causal relations are preserved.
"""
from collections import Counter
import re

from .quotations import outside_quotations


_DAYS = r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)'
_LEFT = r'(?<![A-Za-z0-9_./])'
_RIGHT = r'(?![A-Za-z0-9_]|\.[A-Za-z0-9_]|-[A-Za-z0-9_])'
_DAY = re.compile(_LEFT + _DAYS + _RIGHT, re.I)
_RELATION = re.compile(_LEFT + r'(?P<relation>on|by|before|after)\s+'
                       r'(?P<day>' + _DAYS + ')' + _RIGHT, re.I)
_AMBIGUOUS_PREFIX = re.compile(
    r'\b(?:not|never|no|without|unless|or|and|rather\s+than|instead\s+of)\s*\Z', re.I)
_AMBIGUOUS_SUFFIX = re.compile(
    r'\A\s*(?:,\s*)?(?:or|and)\s+(?:on\b|by\b|before\b|after\b|earlier\b|later\b|'
    + _DAYS + r'\b)', re.I)


def _unique_relations(text):
    text = outside_quotations(text)
    counts = Counter(match.group().casefold() for match in _DAY.finditer(text))
    relations = {}
    for match in _RELATION.finditer(text):
        day = match['day'].casefold()
        if counts[day] != 1:
            continue
        if (_AMBIGUOUS_PREFIX.search(text[max(0, match.start()-40):match.start()])
                or _AMBIGUOUS_SUFFIX.search(text[match.end():match.end()+60])):
            continue
        relations[day] = match['relation'].casefold()
    return relations


def validate_dictation_time(source, result):
    """Return the original result object, or fail without guessing a correction.

    ``source`` must be the prepared edited source after explicit value repair.
    Quote spans use the existing parser's conservative policy. Result metadata,
    including API-reported usage, is never modified or manufactured.
    """
    if not isinstance(source, str) or not isinstance(result, str):
        raise TypeError('Dictation source and result must be text.')
    expected = _unique_relations(source)
    actual = _unique_relations(result)
    if any(actual[day] != relation for day, relation in expected.items() if day in actual):
        raise RuntimeError('The model changed a schedule or deadline. Your original text is preserved; copy it or retry with cleanup off.')
    return result

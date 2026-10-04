"""Resolve explicit, local value corrections before editorial rewriting.

This is not a semantic parser. Only adjacent values of the same type/unit,
or an identical clause restarted with a different value, are resolved. The
original transcript is never modified. Ambiguous wording remains for the LLM.
"""
from dataclasses import dataclass
import re


_VALUE = re.compile(
    r'星期[一二三四五六日天]|周[一二三四五六日天]|今天|明天|昨天|前天|后天|'
    r'(?<![A-Za-z0-9_.])(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|'
    r'today|tomorrow|yesterday)(?![A-Za-z0-9_]|\.[A-Za-z0-9_])|'
    r'(?<![A-Za-z0-9_.])[+-]?(?:\d+(?:\.\d+)?|\.\d+)\s*'
    r'(?:nm|μm|µm|um|mm|cm|km|ms|ns|μs|µs|us|mV|kV|V|mA|μA|µA|uA|A|'
    r'kHz|MHz|GHz|Hz|mW|W|°C|℃|%)(?![A-Za-z0-9_]|\s*[/^²³⁰¹⁴⁵⁶⁷⁸⁹⁻⁺·*]|\s*[-−]\d)', re.I)
_MARKER = re.compile(
    r'不对|我?说错了|我是说|\b(?:sorry|correction|I\s+mean|I\s+meant)\b|[,，]\s*no\b', re.I)
_BEFORE = re.compile(r'[\s,，]*\Z')
_AFTER = re.compile(r'[\s,，:：]*(?:(?:应该是|应为|是)\s*)?\Z')
_BOUNDARY = re.compile(r'[，,;；。.!?！？\n]')
_QUANTITY = re.compile(r'([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*(.+)')
_QUALIFIER = re.compile(r'不|没|未|并非|可能|也许|大概|别|至少|至多|最多|最少|'
                        r'\b(?:not|no|never|maybe|perhaps|possibly|may|might|could|'
                        r'if|unless|before|after|at least|at most)\b', re.I)
_DAYS = {'一': 'monday', '二': 'tuesday', '三': 'wednesday', '四': 'thursday',
         '五': 'friday', '六': 'saturday', '日': 'sunday', '天': 'sunday'}
_RELATIVE = {'今天': 'today', '明天': 'tomorrow', '昨天': 'yesterday',
             '前天': 'day-before-yesterday', '后天': 'day-after-tomorrow'}


@dataclass(frozen=True)
class _Value:
    start: int
    end: int
    spelling: str
    kind: str
    key: str


@dataclass(frozen=True)
class CorrectionPlan:
    edited_source: str
    corrections: tuple[tuple[str, str], ...]


def _quote_ranges(source):
    # Protect nested and unfinished quotations too; no guessed scope inside.
    ranges = []
    stack = []
    closing = {'”': '“', '’': '‘'}
    for index, char in enumerate(source):
        if char in "‘’'" and index and index+1 < len(source) and all(
                c.isascii() and c.isalnum() for c in (source[index-1], source[index+1])):
            continue
        if char in '“‘' or char in "\"'" and (not stack or stack[-1][0] != char):
            stack.append((char, index))
        elif char in "”’\"'" and stack and stack[-1][0] == closing.get(char, char):
            _, start = stack.pop()
            if not stack:
                ranges.append((start, index+1))
    if stack:
        ranges.append((stack[0][1], len(source)))
    return ranges


def _values(source):
    quotes = _quote_ranges(source)
    result = []
    for match in _VALUE.finditer(source):
        if any(start <= match.start() < end for start, end in quotes):
            continue
        word = match.group()
        if word.startswith(('周', '星期')):
            kind, key = 'weekday', _DAYS[word[-1]]
        elif word in _RELATIVE:
            kind, key = 'relative-day', _RELATIVE[word]
        elif word[0].isalpha() and word.isascii():
            key = word.casefold()
            kind = 'relative-day' if key in ('today', 'tomorrow', 'yesterday') else 'weekday'
        else:
            number, unit = _QUANTITY.fullmatch(word).groups()
            # Preserve precision and signs; only normalize whitespace/unit spelling.
            unit = unit.replace('µ', 'μ').replace('um', 'μm').replace('us', 'μs').replace('uA', 'μA')
            kind, key = 'quantity:'+unit, number
        result.append(_Value(match.start(), match.end(), word, kind, key))
    return result


def _one_edit(source):
    values = _values(source)
    quotes = _quote_ranges(source)
    for marker in _MARKER.finditer(source):
        if any(start <= marker.start() < end for start, end in quotes):
            continue
        # The verb "said it wrong" / "I mean" can be ordinary dictated prose.
        # A comma-separated repair cue is required, never just adjacency.
        if not (source[:marker.start()].rstrip().endswith((',', '，'))
                or marker.group().lstrip().startswith((',', '，'))):
            continue
        before = [v for v in values if v.end <= marker.start() and marker.start()-v.end <= 120]
        after = [v for v in values if v.start >= marker.end() and v.start-marker.end() <= 120]
        if not before or not after:
            continue
        old, new = before[-1], after[0]
        if old.kind != new.kind or old.key == new.key:
            continue
        left_bounds = list(_BOUNDARY.finditer(source, 0, old.start))
        start = left_bounds[-1].end() if left_bounds else 0
        if _QUALIFIER.search(source[start:old.start]):
            continue
        left_gap, right_gap = source[old.end:marker.start()], source[marker.end():new.start]
        if _BEFORE.fullmatch(left_gap) and _AFTER.fullmatch(right_gap):
            return old.start, new.end, new.spelling, (old.spelling, new.spelling)
        # A repeated clause must match both sides of its value verbatim. An
        # unrelated action, extra qualifier or uncertain replacement is untouched.
        old_prefix = source[start:old.start].strip()
        old_suffix = left_gap.rstrip(' ,，\t')
        right_start = marker.end()
        while right_start < new.start and source[right_start] in ' ,，\t':
            right_start += 1
        new_prefix = source[right_start:new.start].strip()
        if not old_prefix and new_prefix in ('是', '应该是', '应为'):
            right_start = new.start
            new_prefix = ''
        right_end_match = _BOUNDARY.search(source, new.end)
        end = right_end_match.start() if right_end_match else len(source)
        new_suffix = source[new.end:end].rstrip()
        if (old_prefix == new_prefix and old_suffix.strip() == new_suffix.strip()
                and (old_prefix or old_suffix.strip())
                and not _BOUNDARY.search(old_suffix)
                and marker.start()-start <= 240):
            return start, end, source[right_start:end], (old.spelling, new.spelling)
    return None


def prepare_corrections(source):
    if not isinstance(source, str):
        raise TypeError('Dictation source must be text.')
    edited = source
    corrections = []
    # Bounded work even for a transcript containing many correction markers.
    for _ in range(32):
        edit = _one_edit(edited)
        if edit is None:
            break
        start, end, replacement, pair = edit
        edited = edited[:start]+replacement+edited[end:]
        corrections.append(pair)
    return CorrectionPlan(edited, tuple(corrections))


def validate_corrections(plan, result):
    if not plan.corrections:
        return result
    expected = {(value.kind, value.key) for value in _values(plan.edited_source)}
    actual = {(value.kind, value.key) for value in _values(result)}
    for old, new in plan.corrections:
        old_value, new_value = _values(old)[0], _values(new)[0]
        old_key, new_key = (old_value.kind, old_value.key), (new_value.kind, new_value.key)
        if ((new_key in expected and new_key not in actual)
                or (old_key not in expected and old_key in actual)):
            raise RuntimeError('The model lost an explicit correction. Your original text is preserved; copy it or retry with cleanup off.')
    return result

"""Freeze narrow factual spans while leaving written prose editable.

Apply after quotations have been masked, to the independently corrected edit
source. Restore these spans BEFORE restoring quotations. This module shares
the existing private pure lexical/time helpers deliberately: selection must
not disagree with the post-response guards about correction scopes or known
weekday relations. It does not infer semantic equivalence, mask translations,
or judge whether arbitrary nouns are technical names.

Only unique surviving mixed-language terms are masked. Repeated terms remain
editable so stutter cleanup can remove redundancy; the existing lexical guard
still checks their retention. Token order is strict, so reorganizing passages
across multiple frozen spans may fail safely even if a human would accept it.
Whitespace-contiguous unique technical atoms are frozen as one phrase, keeping
their qualification intact (API endpoint must not become API and endpoint).
"""
from collections import Counter
from dataclasses import dataclass
import re

from .dictation_terms import _AFTER, _BEFORE, _CORRECTION, _terms
from .dictation_time import _RELATION, _unique_relations
from .quotations import QuoteMask


_HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\U00020000-\U0002ebef]+')
_HAN_FILLERS = frozenset('嗯啊呃哦唔额呀哎诶欸喔噢')
_LEADING_RELATION = re.compile(
    r'(?<![A-Za-z0-9_])(?:on|by|before|after|at|in|until|from|to|during|since|'
    r'through|around|near|within|not|never|without)\s*(?:,\s*)?\Z', re.I)
_LEADING_HAN_RELATION = re.compile(r'(?:截至|截止|直到|之前|之后|在|于|到)\s*\Z')
_ATTACHED_LABEL = re.compile(r'\A\s*(?:\([^()\n]{1,80}\)|（[^（）\n]{1,80}）|【[^【】\n]{1,80}】)')
_EDIT_TOKEN = re.compile(r'\[MURMUR_EDIT_\d+\]')
_ERROR = ('The model changed or ambiguously moved protected terms or timing. '
          'Your original text is preserved; copy it or retry with cleanup off.')


@dataclass(frozen=True)
class ProtectedEditingSpan:
    token: str
    text: str
    terms: tuple[str, ...] = ()
    temporal: bool = False


@dataclass(frozen=True)
class EditingSpanMask:
    source: str
    replacements: tuple[ProtectedEditingSpan, ...]
    original_source: str
    quote_source: str
    quote_replacements: tuple[tuple[str, str], ...] = ()

    @property
    def frozen_terms(self):
        return tuple(term for span in self.replacements for term in span.terms)

    @property
    def frozen_term_count(self):
        return len(self.frozen_terms)

    @property
    def frozen_time_count(self):
        return sum(span.temporal for span in self.replacements)

    @property
    def contract(self):
        if not self.replacements:
            return ''
        tokens = ', '.join(span.token for span in self.replacements)
        temporal = ', '.join(span.token for span in self.replacements if span.temporal)
        result = ('Frozen editing tokens: ' + tokens + '. Keep each exactly once and in source order. '
                  'They encode original technical/UI names or complete timing phrases and will be restored. '
                  'Keep the encoded IDs, even when a retained-term list names their contents; do not replace '
                  'IDs with those names. Edit surrounding prose freely, removing filler and redundant restarts. '
                  'Do not quote tokens or attach new parenthetical translations or glosses.')
        if temporal:
            result += (' Complete timing-phrase tokens: ' + temporal + '. Each includes its original '
                       'on/by/before/after relation; do not add another preposition, deadline relation '
                       'or negation immediately before it.')
        return result

    def restore(self, result):
        if not isinstance(result, str):
            raise TypeError('Edited result must be text.')
        # Validate even an empty mask. Count the eventual restored namespace,
        # including original literal IDs hidden in quotes, so a new duplicate
        # outside a quotation cannot sneak past before quotation restoration.
        projected = result
        for span in self.replacements:
            projected = projected.replace(span.token, span.text)
        for token, quoted in self.quote_replacements:
            projected = projected.replace(token, quoted)
        original_ids = Counter(_EDIT_TOKEN.findall(self.original_source))
        if any(count > original_ids[token] for token, count in Counter(_EDIT_TOKEN.findall(projected)).items()):
            raise RuntimeError(_ERROR)
        if not self.replacements:
            return result
        # Complete unchanged echoes are safe, including a fully decoded echo.
        # Never accept a partially edited unencoded body by guessing its spans.
        if result == self.original_source or result == self.quote_source:
            return result
        if result == self.source:
            return self.quote_source
        if any(result.count(span.token) != 1 for span in self.replacements):
            raise RuntimeError(_ERROR)
        positions = [result.index(span.token) for span in self.replacements]
        if positions != sorted(positions):
            raise RuntimeError(_ERROR)
        # Validate all boundaries before restoration: adjacent restored quotes
        # or names must not be mistaken for wrappers introduced by the model.
        for span in self.replacements:
            start = result.index(span.token)
            end = start + len(span.token)
            left, right = result[:start].rstrip(), result[end:].lstrip()
            original_start = self.source.index(span.token)
            original_end = original_start + len(span.token)
            old_left = self.source[:original_start].rstrip()
            old_right = self.source[original_end:].lstrip()
            for boundary, original_boundary, from_left in (
                    (left, old_left, True), (right, old_right, False)):
                char = boundary[-1:] if from_left else boundary[:1]
                old_char = original_boundary[-1:] if from_left else original_boundary[:1]
                if char in ('“', '”', '‘', '’', '"', "'") and char != old_char:
                    raise RuntimeError(_ERROR)
            for opening, closing in (('(', ')'), ('（', '）'), ('【', '】')):
                if (left.endswith(opening) and right.startswith(closing)
                        and not (old_left.endswith(opening) and old_right.startswith(closing))):
                    raise RuntimeError(_ERROR)
            label = _ATTACHED_LABEL.match(right)
            old_label = _ATTACHED_LABEL.match(old_right)
            if label and (not old_label or label.group().strip() != old_label.group().strip()):
                raise RuntimeError(_ERROR)
            if span.temporal and (_leading_relation(left) != _leading_relation(old_left)):
                if _leading_relation(left):
                    raise RuntimeError(_ERROR)
        for span in self.replacements:
            result = result.replace(span.token, span.text, 1)
        return result


def _leading_relation(left):
    match = _LEADING_RELATION.search(left) or _LEADING_HAN_RELATION.search(left)
    return match.group().strip().casefold() if match else ''


def _meaningful_han(text):
    for match in _HAN.finditer(text):
        if not set(match.group()).issubset(_HAN_FILLERS):
            return True
        # Isolated fillers do not turn an English sentence into mixed prose.
        start, end = match.span()
        if ((start and text[start-1].isalnum())
                or (end < len(text) and text[end].isalnum())):
            return True
    return False


def _retained_terms(text):
    """Reuse the exact existing adjacent-correction scope, by occurrence."""
    terms = _terms(text)
    removed = set()
    for marker in _CORRECTION.finditer(text):
        left = [term for term in terms if term.end <= marker.start()
                and marker.start()-term.end <= 12
                and _BEFORE.fullmatch(text[term.end:marker.start()])]
        right = [term for term in terms if term.start >= marker.end()
                 and term.start-marker.end() <= 12
                 and _AFTER.fullmatch(text[marker.end():term.start])]
        if len(left) == len(right) == 1:
            removed.add((left[0].start, left[0].end))
    return [term for term in terms if (term.start, term.end) not in removed]


def mask_editing_spans(quote_mask):
    """Accept a QuoteMask of corrected source; no raw/config mutation or I/O.

    Consumers enable this only for original-language dictation/refinement.
    Counts describe selected unique spans, not model capability or accuracy.
    """
    if not isinstance(quote_mask, QuoteMask):
        raise TypeError('Editing source must be a QuoteMask.')
    text = quote_mask.source
    original = text
    visible = text
    for token, quoted in quote_mask.replacements:
        original = original.replace(token, quoted, 1)
        visible = visible.replace(token, ' ' * len(token), 1)
    candidates = []
    if _meaningful_han(visible):
        terms = _retained_terms(visible)
        counts = Counter(term.key for term in terms)
        for term in terms:
            if counts[term.key] != 1:
                continue
            # Use actual quote-masked text, not the blanked detection view:
            # a hidden quotation must remain a boundary, not apparent spaces.
            if candidates and text[candidates[-1][1]:term.start].isspace():
                start, _, names, _ = candidates[-1]
                candidates[-1] = (start, term.end, names + (term.spelling,), False)
            else:
                candidates.append((term.start, term.end, (term.spelling,), False))
    relations = _unique_relations(visible)
    for match in _RELATION.finditer(visible):
        if relations.get(match['day'].casefold()) != match['relation'].casefold():
            continue
        # Already compounded/negated relations are ambiguous, not a known
        # clean phrase; do not make their wording appear guaranteed safe.
        if _leading_relation(visible[:match.start()].rstrip()):
            continue
        candidates.append((match.start(), match.end(), (), True))
    merged = []
    for start, end, terms, temporal in sorted(candidates):
        if merged and start < merged[-1][1]:
            old_start, old_end, old_terms, old_time = merged[-1]
            merged[-1] = (old_start, max(old_end, end), old_terms+terms, old_time or temporal)
        else:
            merged.append((start, end, terms, temporal))
    replacements = []
    parts = []
    cursor = 0
    number = 1
    for start, end, terms, temporal in merged:
        token = f'[MURMUR_EDIT_{number}]'
        while token in original or token in text:
            number += 1
            token = f'[MURMUR_EDIT_{number}]'
        number += 1
        parts.extend((text[cursor:start], token))
        cursor = end
        replacements.append(ProtectedEditingSpan(token, text[start:end], terms, temporal))
    parts.append(text[cursor:])
    return EditingSpanMask(''.join(parts), tuple(replacements), original, text, quote_mask.replacements)

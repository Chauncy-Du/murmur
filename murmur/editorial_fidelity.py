"""Narrow rejection of observed editorial semantic regressions.

Use only for original-language dictation/refinement after span restoration,
with the independently prepared corrected edit source. Quoted content uses
the existing conservative quotation parser; its ambiguity policy is unchanged.

This is NOT a general semantic parser. It rejects a newly explicit causal
connector only when the source has none. A comma-led finite ``as``/``so``/``since`` clause
is treated as an added explicit relationship, without claiming to disambiguate
all causal versus temporal uses. Role/participial ``as`` stays editable.
Nominal due-to reasons are distinguished conservatively from scheduled
infinitives and due dates; unknown bare due-to heads are not classified.
If source already has explicit causality, attribution of added links to clauses
is not inferred. Two observed English imperative families have unique-action
checks: Send -> sent and Do not publish -> did not publish. One explicit Chinese
family checks 先/请/请先记录 -> 已/已经记录 or 记录…了. Multiple actions,
synonyms, conditional/question contexts and unknown subject grammar are left
alone. Actor/uncertainty attribution is not inferred. No text is corrected,
no meaning/accuracy guarantee is made, and passing
returns the exact result object including any caller-owned usage metadata.
"""
import re

from .quotations import outside_quotations


_CAUSAL = re.compile(r'\b(?:because|therefore|consequently|hence|thus)\b|因为|因此|所以|因而|故而|由于', re.I)
_CLAUSE_LINK = re.compile(r'[,;]\s*(?:as|so|since)\b', re.I)
_DUE_LINK = re.compile(r'\b(?P<kind>due|owing)\s+to\b', re.I)
_DETERMINERS = frozenset(('the', 'a', 'an', 'this', 'that', 'these', 'those', 'my',
                          'our', 'your', 'his', 'her', 'its', 'their'))
_DUE_NOMINALS = frozenset(('approval', 'uncertainty', 'temperature',
                          'latency', 'absence', 'noise', 'timing'))
_DUE_INFINITIVES = frozenset(('be', 'arrive', 'start', 'begin', 'end', 'finish', 'complete',
                             'return', 'open', 'close', 'run', 'meet', 'take', 'send',
                             'record', 'publish', 'review', 'test', 'check', 'bring',
                             'sing', 'ring', 'spring', 'swing', 'sting'))
_OWED_PREFIX = re.compile(r'\b(?:payment|payments|money|amount|balance|sum|debt|fee|fees|royalties)'
                          r'\s*(?:(?:is|was|are|were)\s*)?\Z', re.I)
_RESULT_LINK = re.compile(r'(?:\A|[.!?;:,]\s*)as\s+a\s+result\b', re.I)
_WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?")
_AUXILIARIES = frozenset(('am', 'is', 'are', 'was', 'were', 'has', 'have', 'had',
                         'will', 'would', 'can', 'could', 'may', 'might', 'must',
                         'should', 'do', 'does', 'did'))
_PERSON = frozenset(('i', 'we', 'you', 'he', 'she', 'it', 'they'))
_SUBJECT_BLOCKERS = _PERSON | frozenset(('as', 'so', 'and', 'or', 'but', 'if', 'unless',
                                        'whether', 'to', 'for', 'with', 'at', 'in', 'on',
                                        'by', 'before', 'after', 'not', 'never'))
_CLAUSE_END = re.compile(r'[.!?;:\n，。！？；]')
_SEND = re.compile(r'(?<![A-Za-z0-9_./])(?:send|sends|sending|sent)(?![A-Za-z0-9_.])', re.I)
_PUBLISH = re.compile(r'(?<![A-Za-z0-9_./])(?:publish|publishes|publishing|published)(?![A-Za-z0-9_.])', re.I)
_IMPERATIVE_PREFIX = r'(?:\A|[.!?;:\n])\s*(?:(?:um|uh|erm)\s*,\s*)?(?:please\s+)?'
_SEND_COMMAND = re.compile(_IMPERATIVE_PREFIX + r'send\b', re.I)
_PUBLISH_COMMAND = re.compile(_IMPERATIVE_PREFIX + r'(?:do\s+not|don[\'’]t)\s+publish\b', re.I)
_DID_NOT_PUBLISH = re.compile(r'\b(?:did\s+not|didn[\'’]t)\s+publish\b', re.I)
_UNCERTAIN_PREFIX = re.compile(r'\b(?:if|unless|whether|suppose|imagine|may|might|could|should|would|can|will|must)\b', re.I)
_CN_RECORD = re.compile('记录')
_CN_CHUNK_END = re.compile(r'[，,。！？；;!?\n]')
_CN_SENTENCE_END = re.compile(r'[。！？；;!?\n]')
_CN_REQUEST_PREFIX = re.compile(r'\A\s*(?:先|请\s*(?:先)?)\s*\Z')
_CN_HISTORY_PREFIX = re.compile(r'\A\s*(?:(?:我们|你们|他们|她们|我|你|他|她|团队|本组)\s*)?(?P<already>已(?:经)?)?\s*\Z')
_CN_CONDITIONAL = re.compile(r'如果|假如|要是|只要|一旦|除非|若|如有')
_CN_CAPABILITY = re.compile(r'\A\s*(?:不(?:了|下|到|得)|不能|无法)')
_CN_SEQUENCE_AFTER = re.compile(r'再|才|就|以后|之后|的时候')
_CN_QUESTION_TAIL = re.compile(r'(?:吗|么|呢|好吗|好么)\s*\Z')
_ERROR_CAUSE = ('The model added a causal relationship not stated in your dictation. '
                'Your original text is preserved; copy it or retry with cleanup off.')
_ERROR_ACTION = ('The model changed an instruction into a completed action. '
                 'Your original text is preserved; copy it or retry with cleanup off.')


def _finite_clause(after):
    """Bounded subject + finite auxiliary; not an arbitrary occurrence of as."""
    clause = _CLAUSE_END.split(after, maxsplit=1)[0][:120]
    matches = list(_WORD.finditer(clause))[:10]
    if not matches or clause[:matches[0].start()].strip():
        return False
    words = [match.group().casefold() for match in matches]
    # Restrict the subject to an uninterrupted, short word sequence. A comma
    # after a role (as a reviewer, I...) prevents treating the role as a clause.
    for index, word in enumerate(words[:7]):
        if word not in _AUXILIARIES or not index:
            continue
        subject = words[:index]
        if any(clause[matches[n-1].end():matches[n].start()].strip() for n in range(1, index+1)):
            return False
        if subject[0] in _PERSON:
            return len(subject) == 1
        # Indefinite role/comparison phrases are ambiguous, even if a later
        # auxiliary appears: as an engineer would... must not be called causal.
        if subject[0] in ('a', 'an'):
            return False
        return not any(token in _SUBJECT_BLOCKERS for token in subject)
    return False


def _has_explicit_relationship(text):
    if _CAUSAL.search(text) or _RESULT_LINK.search(text):
        return True
    if any(_finite_clause(text[match.end():]) for match in _CLAUSE_LINK.finditer(text)):
        return True
    for match in _DUE_LINK.finditer(text):
        if _OWED_PREFIX.search(text[max(0, match.start()-60):match.start()]):
            continue  # an amount due/owing to someone is a beneficiary role.
        if match['kind'].casefold() == 'owing':
            return True
        after = text[match.end():]
        first = _WORD.search(after)
        if first is None or after[:first.start()].strip():
            continue
        head = first.group().casefold()
        if head in _DUE_INFINITIVES:
            continue  # due to arrive/be reviewed is scheduling, not a cause.
        # Bare rain/weather/lack can also be scheduled infinitives. Only the
        # explicitly nominal "lack of" form is recognized without a determiner.
        if (head in _DETERMINERS or head in _DUE_NOMINALS
                or re.match(r'\s*lack\s+of\b', after, re.I)
                or len(head) > 4 and head.endswith('ing')):
            return True
    return False


def _clause_context(text, start, end):
    previous = list(_CLAUSE_END.finditer(text[:start]))
    left = text[previous[-1].end() if previous else 0:start][-160:]
    following = _CLAUSE_END.search(text, end)
    right = text[end:following.start() if following else len(text)]
    question = bool(following and following.group() in ('?', '？'))
    return left, right, question


def _historical_context(text, start, end, *, fragment=False):
    left, _, question = _clause_context(text, start, end)
    if question or _UNCERTAIN_PREFIX.search(left):
        return False
    words = [match.group().casefold() for match in _WORD.finditer(left)]
    if not words:
        return fragment
    # These are narrow finite-subject/passive anchors, not guessed noun roles.
    if any(word in _PERSON for word in words):
        return True
    return bool(re.search(r'\b(?:was|were|has\s+been|have\s+been|had\s+been)\s*\Z', left, re.I))


def _instruction_became_history(source, result):
    source_sends = list(_SEND.finditer(source))
    result_sends = list(_SEND.finditer(result))
    if (len(source_sends) == len(result_sends) == 1 and _SEND_COMMAND.search(source)
            and result_sends[0].group().casefold() == 'sent'
            and _historical_context(result, result_sends[0].start(), result_sends[0].end())):
        return True
    source_publishes = list(_PUBLISH.finditer(source))
    result_publishes = list(_PUBLISH.finditer(result))
    if len(source_publishes) == len(result_publishes) == 1 and _PUBLISH_COMMAND.search(source):
        past = _DID_NOT_PUBLISH.search(result)
        if past and _historical_context(result, past.start(), past.end(), fragment=True):
            return True
    return False


def _chinese_context(text, action):
    """One punctuation-delimited chunk, with same-sentence condition context."""
    before = list(_CN_CHUNK_END.finditer(text[:action.start()]))
    start = before[-1].end() if before else 0
    after = _CN_CHUNK_END.search(text, action.end())
    end = after.start() if after else len(text)
    sentence = list(_CN_SENTENCE_END.finditer(text[:start]))
    context = text[sentence[-1].end() if sentence else 0:start]
    following_sentence_end = _CN_SENTENCE_END.search(text, end)
    tail = text[end:following_sentence_end.start() if following_sentence_end else len(text)]
    suffix = text[action.end():end].strip()
    question = bool(after and after.group() in ('?', '？')) or bool(_CN_QUESTION_TAIL.search(suffix))
    ambiguous = (question or bool(_CN_CONDITIONAL.search(context + suffix + tail))
                 or bool(_CN_CAPABILITY.search(suffix)))
    return text[start:action.start()], suffix, ambiguous


def _chinese_instruction_became_history(source, result):
    source_actions = list(_CN_RECORD.finditer(source))
    result_actions = list(_CN_RECORD.finditer(result))
    if len(source_actions) != 1 or len(result_actions) != 1:
        return False
    prefix, _, ambiguous = _chinese_context(source, source_actions[0])
    if ambiguous or not _CN_REQUEST_PREFIX.fullmatch(prefix):
        return False
    prefix, suffix, ambiguous = _chinese_context(result, result_actions[0])
    history = _CN_HISTORY_PREFIX.fullmatch(prefix)
    if ambiguous or not history:
        return False
    if history['already']:
        return True
    # 记录了... / 记录...了 are clear completion only at a chunk head.
    # A subsequent 再/才/就 can be an instruction conditional on completing it,
    # not a factual assertion that completion already occurred.
    if _CN_SEQUENCE_AFTER.search(suffix):
        return False
    return bool(suffix.startswith('了') or suffix.endswith('了'))


def validate_editorial_fidelity(source, result):
    """Return result unchanged, or reject without inferring a replacement.

    No provider import or I/O. The caller retains raw text and decides recovery;
    this helper neither inserts partial text nor mutates API usage metadata.
    """
    if not isinstance(source, str) or not isinstance(result, str):
        raise TypeError('Editorial source and result must be text.')
    source_prose = outside_quotations(source)
    result_prose = outside_quotations(result)
    if not _has_explicit_relationship(source_prose) and _has_explicit_relationship(result_prose):
        raise RuntimeError(_ERROR_CAUSE)
    if (_instruction_became_history(source_prose, result_prose)
            or _chinese_instruction_became_history(source_prose, result_prose)):
        raise RuntimeError(_ERROR_ACTION)
    return result

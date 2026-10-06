"""Conservative lexical checks, not a semantic judge of English prose.

Protect established UI/technical names and recognizable identifiers. Plain
English words outside these classes remain editable; unfamiliar lowercase
terms still rely on the writing contract rather than guessed terminology.
"""
from dataclasses import dataclass
import re


_WORD=re.compile(r'(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9]*(?:[-_.:+][A-Za-z0-9]+)*[+#]*(?![A-Za-z0-9_])')
_CORE=frozenset(('bubble','interface','settings','api','sdk','ui','gui','http','https',
                 'json','xml','csv','sqlite','sql','websocket','onnx','gguf','llm','asr',
                 'pcm','cpu','gpu','cuda','ollama','murmur','dashscope','deepseek',
                 'fun-asr-realtime','sensevoice-small'))
_SHORT_TECH=frozenset(('response','calibration','drift','benchmark','token','clipboard',
                       'latency','timeout','endpoint','hotword','dataset','waveform'))
_PLURALS={word+'s':word for word in ('bubble','interface','api','sdk','response','benchmark',
                                   'token','endpoint','hotword','dataset','waveform')}
_PHRASES=(re.compile(r'(?<![A-Za-z0-9_])Auto\s+model\s+selection(?![A-Za-z0-9_])',re.I),)
_ROUTINE_UPPER=frozenset(('I','A','OK','AM','PM'))
_PROSE_ABBREVIATIONS=frozenset(('e.g','i.e','etc','vs'))
_CORRECTION=re.compile(r'不对|我说错了|我是说|\b(?:sorry|correction)\b|[,，]\s*no\b|[,，]\s*不是(?=\s*[,，])',re.I)
_BEFORE=re.compile(r'[\s,，]*\Z')
_AFTER=re.compile(r'[\s,，:：]*(?:(?:应该是|应为|是|用)\s*)?\Z')


@dataclass(frozen=True)
class _Term:
    spelling:str
    key:str
    start:int
    end:int


@dataclass(frozen=True)
class TermPlan:
    required:tuple[str,...]
    superseded:tuple[str,...]


def _key(word):
    folded=word.casefold()
    return _PLURALS.get(folded,folded)


def _terms(source):
    words=list(_WORD.finditer(source));run_sizes={};start=0
    for index in range(1,len(words)+1):
        if index==len(words) or not source[words[index-1].end():words[index].start()].isspace():
            for member in range(start,index):run_sizes[member]=index-start
            start=index
    phrases=[_Term(match.group(),match.group().casefold(),match.start(),match.end())
             for pattern in _PHRASES for match in pattern.finditer(source)]
    terms=list(phrases)
    for index,match in enumerate(words):
        if any(phrase.start<=match.start()<phrase.end for phrase in phrases):continue
        word=match.group();key=_key(word)
        identifier=key not in _PROSE_ABBREVIATIONS and (any(c.isdigit() for c in word) or any(c in '_.:+#' for c in word)
                    or bool(re.search(r'[a-z][A-Z]',word))
                    or sum(c.isupper() for c in word)>=2 and word not in _ROUTINE_UPPER)
        # A standalone title-cased name followed by Chinese 的 is a named
        # modifier, including unfamiliar names. Do not freeze English sentences
        # merely because their first word is capitalized.
        named_modifier = (run_sizes[index] == 1 and len(word) >= 3
                          and word[0].isupper() and word[1:].islower()
                          and bool(re.match(r'\s*的', source[match.end():])))
        if key in _CORE or identifier or named_modifier or key in _SHORT_TECH and run_sizes[index]<=3:
            terms.append(_Term(word,key,match.start(),match.end()))
    return sorted(terms,key=lambda term:term.start)


def mixed_term_plan(source):
    """Exempt only a directly adjacent old-name → new-name correction.

    Ordinary negation (不是), instructions (改成), uncertain replacements and
    non-adjacent correction scopes never waive protection for the entire text.
    Other occurrences of a corrected-away name still require its retention.
    """
    terms=_terms(source);removed=set()
    for marker in _CORRECTION.finditer(source):
        left=[term for term in terms if term.end<=marker.start()
              and marker.start()-term.end<=12 and _BEFORE.fullmatch(source[term.end:marker.start()])]
        right=[term for term in terms if term.start>=marker.end()
               and term.start-marker.end()<=12 and _AFTER.fullmatch(source[marker.end():term.start])]
        if len(left)==len(right)==1:removed.add((left[0].start,left[0].end))
    required=[];superseded=[];seen=set()
    for term in terms:
        if (term.start,term.end) in removed:
            if term.spelling not in superseded:superseded.append(term.spelling)
        elif term.key not in seen:
            required.append(term.spelling);seen.add(term.key)
    return TermPlan(tuple(required),tuple(superseded))


def validate_mixed_terms(source,result):
    plan=mixed_term_plan(source)
    retained={_key(match.group()) for match in _WORD.finditer(result)}
    for spelling in plan.required:
        if ' ' in spelling:
            present=bool(re.search(r'(?<![A-Za-z0-9_])'+r'\s+'.join(re.escape(part) for part in spelling.split())+
                                   r'(?![A-Za-z0-9_])',result,re.I))
        else:present=_key(spelling) in retained
        if not present:
            raise RuntimeError('The model changed or omitted English terms in mixed-language dictation. Your original text is preserved; copy it or retry with cleanup off.')
    return result

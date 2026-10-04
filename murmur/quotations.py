"""Freeze explicit quotations while the model edits surrounding prose."""
from dataclasses import dataclass
import re


_QUOTE_TOKEN = re.compile(r'\[MURMUR_QUOTE_\d+\]')


def quoted_ranges(text):
    stack=[];spans=[];closing={'”':'“','’':'‘'}
    for index,char in enumerate(text):
        if char in ('‘','’') and index and index+1<len(text) and all(
                c.isascii() and c.isalnum() for c in (text[index-1],text[index+1])):
            continue
        opening=char in ('“','‘') or (char=='"' and (not stack or stack[-1][0]!='"'))
        if opening:
            if stack:stack=[(mark,start,True) for mark,start,_ in stack]
            stack.append((char,index,bool(stack)));continue
        if char not in ('”','’','"'):continue
        if not stack:continue
        if stack[-1][0]!=closing.get(char,'"'):
            stack.clear();continue
        _,start,ambiguous=stack.pop()
        if not stack and not ambiguous and text[start+1:index].strip():spans.append((start,index+1))
    return tuple(spans)


def protected_quoted_spans(text):
    return [text[start:end] for start,end in quoted_ranges(text)]


def outside_quotations(text):
    result=list(text)
    for start,end in quoted_ranges(text):result[start:end]=' '*(end-start)
    return ''.join(result)


@dataclass(frozen=True)
class QuoteMask:
    source: str
    replacements: tuple[tuple[str,str],...]

    @property
    def contract(self):
        if not self.replacements:return ''
        tokens=', '.join(token for token,_ in self.replacements)
        return ('Frozen quotation tokens: '+tokens+'. Keep each token exactly once and in source order. '
                'They represent verbatim source quotations and will be restored after editing. '
                'Edit only surrounding prose; do not add quotation marks around tokens, reinterpret them or add causal links.')

    def restore(self,result):
        original=self.source
        for token,span in self.replacements:original=original.replace(token,span,1)
        error='The model changed or ambiguously moved quoted text. Your original text is preserved; copy it or retry with cleanup off.'
        probe=result
        for token,span in self.replacements:probe=probe.replace(token,span,1)
        # Count projected output, including literal IDs concealed by a frozen
        # quotation; an added visible copy must not escape after restoration.
        for token in set(_QUOTE_TOKEN.findall(probe)):
            if probe.count(token)>original.count(token):raise RuntimeError(error)
        if not self.replacements:return result
        # An exact unchanged echo cannot introduce wrappers. This also preserves
        # original empty delimiters that the conservative parser leaves alone.
        if result==self.source:return original
        counts=[result.count(token) for token,_ in self.replacements]
        if not any(counts):
            # Only the complete unchanged source is safe without its tokens.
            if result==original:return result
            raise RuntimeError(error)
        if any(count!=1 for count in counts):raise RuntimeError(error)
        positions=[result.index(token) for token,_ in self.replacements]
        if positions!=sorted(positions):raise RuntimeError(error)
        # Validate the model's unchanged token output before inserting any quote.
        # Otherwise an adjacent restored span looks like a new wrapper.
        for token,_ in self.replacements:
            start=result.index(token);end=start+len(token)
            left=result[:start].rstrip();right=result[end:].lstrip()
            if ((left and left[-1] in '“”‘’"')
                    or (right and right[0] in '“”‘’"')):raise RuntimeError(error)
        for token,span in self.replacements:
            result=result.replace(token,span,1)
        return result


def mask_quotations(text):
    replacements=[];parts=[];cursor=0;number=1
    for start,end in quoted_ranges(text):
        token=f'[MURMUR_QUOTE_{number}]'
        while token in text:
            number+=1;token=f'[MURMUR_QUOTE_{number}]'
        number+=1
        parts.extend((text[cursor:start],token));cursor=end
        replacements.append((token,text[start:end]))
    parts.append(text[cursor:])
    return QuoteMask(''.join(parts),tuple(replacements))

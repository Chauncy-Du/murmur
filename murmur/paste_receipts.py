"""UIA paste confirmation; document contents never leave the COM worker."""
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import time
import uuid

MAX_DOCUMENT_CHARS=128000


def _normalized(text):
    return text.replace('\r\n','\n').replace('\r','\n')


def _digest(text):
    return hashlib.sha256(_normalized(text).encode('utf-8','surrogatepass')).hexdigest()


def _read(range_):
    text=range_.GetText(MAX_DOCUMENT_CHARS+1)
    if not isinstance(text,str) or len(text)>MAX_DOCUMENT_CHARS or '\0' in text:
        raise ValueError('Document cannot be verified within the bounded read.')
    return _normalized(text)


def _single(pattern):
    ranges=pattern.GetSelection()
    return ranges.GetElement(0) if ranges and int(ranges.Length)==1 else None


def _same(first,second,types):
    return all(first.CompareEndpoints(endpoint,second,endpoint)==0 for endpoint in
               (types.TextPatternRangeEndpoint_Start,types.TextPatternRangeEndpoint_End))


@dataclass(frozen=True)
class _Receipt:
    target: object
    selected: object
    before_digest: str
    after_digest: str
    lengths: tuple[int,int,int]
    segment_digests: tuple[str,str,str]
    created: float


class PasteReceipts:
    def __init__(self,limit=8,ttl=10):
        self.entries=OrderedDict();self.limit=limit;self.ttl=ttl

    def _expire(self):
        now=time.monotonic()
        for token,entry in list(self.entries.items()):
            if now-entry.created>=self.ttl:self.entries.pop(token,None)

    def create(self,target,text,pattern,types):
        self._expire()
        if not getattr(target,'editable',False) or not isinstance(text,str) or not text.strip() or '\0' in text:
            return None
        try:
            selected=_single(pattern)
            if selected is None:return None
            selected=selected.Clone()
            document=pattern.DocumentRange
            before=_read(document)
            prefix=document.Clone();suffix=document.Clone()
            prefix.MoveEndpointByRange(types.TextPatternRangeEndpoint_End,selected,types.TextPatternRangeEndpoint_Start)
            suffix.MoveEndpointByRange(types.TextPatternRangeEndpoint_Start,selected,types.TextPatternRangeEndpoint_End)
            left=_read(prefix);right=_read(suffix)
            if left+_read(selected)+right!=before:return None
            after=left+_normalized(text)+right
            if len(after)>MAX_DOCUMENT_CHARS:return None
            current=_single(pattern)
            if current is None or not _same(current,selected,types) or _read(document)!=before:return None
            token=uuid.uuid4().hex
            inserted=_normalized(text)
            self.entries[token]=_Receipt(target,selected,_digest(before),_digest(after),
                                         (len(left),len(inserted),len(right)),
                                         (_digest(left),_digest(inserted),_digest(right)),time.monotonic())
            while len(self.entries)>self.limit:self.entries.popitem(last=False)
            return token
        except Exception:return None

    def ready(self,target,token,pattern,types):
        self._expire();entry=self.entries.get(token)
        if not entry or entry.target!=target:return False
        try:
            selected=_single(pattern)
            return bool(selected is not None and _same(selected,entry.selected,types)
                        and _digest(_read(pattern.DocumentRange))==entry.before_digest)
        except Exception:return False

    def create_value(self,target,text,value,selection):
        """Legacy native EDIT controls expose ValuePattern rather than ranges."""
        self._expire()
        if not getattr(target,'editable',False) or not isinstance(value,str) or len(value)>MAX_DOCUMENT_CHARS or '\0' in value:
            return None
        if not isinstance(text,str) or not text.strip() or '\0' in text:return None
        try:
            start,end=selection
            encoded=value.encode('utf-16-le','surrogatepass')
            if not 0<=start<=end<=len(encoded)//2:return None
            left=_normalized(encoded[:start*2].decode('utf-16-le','surrogatepass'))
            right=_normalized(encoded[end*2:].decode('utf-16-le','surrogatepass'))
            inserted=_normalized(text);after=left+inserted+right
            if len(after)>MAX_DOCUMENT_CHARS:return None
            token=uuid.uuid4().hex
            self.entries[token]=_Receipt(target,tuple(selection),_digest(value),_digest(after),
                                         (len(left),len(inserted),len(right)),
                                         (_digest(left),_digest(inserted),_digest(right)),time.monotonic())
            while len(self.entries)>self.limit:self.entries.popitem(last=False)
            return token
        except Exception:return None

    def ready_value(self,target,token,value,selection):
        self._expire();entry=self.entries.get(token)
        return bool(entry and entry.target==target and entry.selected==tuple(selection)
                    and isinstance(value,str) and len(value)<=MAX_DOCUMENT_CHARS and '\0' not in value
                    and _digest(value)==entry.before_digest)

    @staticmethod
    def _confirmed(entry,current):
        confirmed=_digest(current)==entry.after_digest
        left,inserted,right=entry.lengths
        if not confirmed and len(current)>=left+inserted+right:
            segments=(current[:left],current[left:left+inserted],current[-right:] if right else '')
            confirmed=tuple(_digest(part) for part in segments)==entry.segment_digests
        return confirmed

    def verified_value(self,target,token,value):
        self._expire();entry=self.entries.get(token)
        if not entry or entry.target!=target or not isinstance(value,str) or len(value)>MAX_DOCUMENT_CHARS or '\0' in value:return False
        confirmed=self._confirmed(entry,_normalized(value))
        if confirmed:self.entries.pop(token,None)
        return confirmed

    def verified(self,target,token,pattern,types):
        self._expire();entry=self.entries.get(token)
        if not entry or entry.target!=target:return False
        try:
            current=_read(pattern.DocumentRange)
            # Continuing to type immediately after the inserted text is normal.
            # Confirm the inserted span plus unchanged original prefix/suffix;
            # extra text is allowed only between the insertion and old suffix.
            confirmed=self._confirmed(entry,current)
            if confirmed:self.entries.pop(token,None)
            return confirmed
        except Exception:return False

    def forget(self,target,token):
        entry=self.entries.get(token)
        if entry and entry.target==target:self.entries.pop(token,None)

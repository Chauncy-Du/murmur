"""Bounded UIA context capture; fixtures never access another app or clipboard."""
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
import threading
import pytest
from murmur import windows


TYPES=SimpleNamespace(TextPatternRangeEndpoint_Start=0,TextPatternRangeEndpoint_End=1,
                      TextUnit_Character=0,UIA_ValuePatternId=1,UIA_TextPatternId=2,
                      IUIAutomationValuePattern=object(),IUIAutomationTextPattern=object(),
                      UIA_IsReadOnlyAttributeId=3)
TARGET=windows.Target(10,11,12,(42,1),12,True)
READ_ONLY=windows.Target(10,11,12,(42,1),12,False)


class Document:
    def __init__(self,text):self.text=text;self.reads=[]


class Range:
    def __init__(self,document,start,end):self.document=document;self.start=start;self.end=end
    def Clone(self):return Range(self.document,self.start,self.end)
    def CompareEndpoints(self,endpoint,other,other_endpoint):
        return (self.start if endpoint==0 else self.end)-(other.start if other_endpoint==0 else other.end)
    def MoveEndpointByUnit(self,endpoint,unit,count):
        old=self.start if endpoint==0 else self.end
        moved=max(0,min(len(self.document.text),old+count))
        if endpoint==0:self.start=moved;self.end=max(self.end,moved)
        else:self.end=moved;self.start=min(self.start,moved)
        return moved-old
    def GetText(self,limit):
        assert limit>0,'Unbounded document text reads are forbidden.'
        self.document.reads.append((self.start,self.end,limit))
        return self.document.text[self.start:self.end][:limit]


class Pattern:
    def __init__(self,document,ranges,read_only=False):
        self.document=document;self.ranges=[Range(document,*item) for item in ranges];self.read_only=read_only
        self.DocumentRange=SimpleNamespace(GetAttributeValue=lambda attr:self.read_only)
    def GetSelection(self):
        return SimpleNamespace(Length=len(self.ranges),GetElement=lambda index:self.ranges[index])
    def QueryInterface(self,interface):return self


def pattern(text='before selected after',ranges=((7,15),)):
    return Pattern(Document(text),ranges)


def test_context_is_immutable_and_does_not_expose_surrounding_text():
    value=windows.TextContext()
    with pytest.raises(FrozenInstanceError):value.text='changed'
    p=pattern();bookmarks=windows._ContextBookmarks();context=bookmarks.create(TARGET,p,TYPES)
    assert context.state=='selection' and context.text=='selected' and context.bookmark
    entry=bookmarks.entries[context.bookmark]
    assert isinstance(entry.fingerprint,str) and len(entry.fingerprint)==64
    assert not hasattr(entry,'text') and context.text not in entry.fingerprint
    assert all((start,end)==(7,15) for start,end,_ in p.document.reads)
    assert bookmarks.matches(TARGET,context,p,TYPES)


def test_selection_content_change_and_same_text_elsewhere_are_rejected():
    p=pattern('repeat repeat',((0,6),));bookmarks=windows._ContextBookmarks()
    context=bookmarks.create(TARGET,p,TYPES)
    p.ranges=[Range(p.document,7,13)]
    assert not bookmarks.matches(TARGET,context,p,TYPES)
    p.ranges=[Range(p.document,0,6)];p.document.text='update repeat'
    assert not bookmarks.matches(TARGET,context,p,TYPES)
    p.document.text='repeat repeat'
    assert not bookmarks.matches(TARGET,windows.TextContext('selection','forged',context.bookmark),p,TYPES)
    assert not bookmarks.matches(READ_ONLY,context,p,TYPES)


def test_caret_context_has_only_token_and_hash_and_checks_nearby_changes():
    p=pattern('a'*200+'b'*200,((200,200),));bookmarks=windows._ContextBookmarks()
    context=bookmarks.create(TARGET,p,TYPES)
    assert context.state=='caret' and context.text=='' and context.bookmark
    assert bookmarks.matches(TARGET,context,p,TYPES)
    assert all(136<=start<=end<=264 and end-start<=64 for start,end,_ in p.document.reads)
    p.document.text='a'*199+'c'+'b'*200
    assert not bookmarks.matches(TARGET,context,p,TYPES)
    p.document.text='a'*200+'b'*200;p.ranges=[Range(p.document,201,201)]
    assert not bookmarks.matches(TARGET,context,p,TYPES)


@pytest.mark.parametrize('text,position',[('',0),('abc',0),('abc',3)])
def test_caret_at_document_boundaries_is_verifiable(text,position):
    p=pattern(text,((position,position),));bookmarks=windows._ContextBookmarks()
    context=bookmarks.create(TARGET,p,TYPES)
    assert context.state=='caret' and bookmarks.matches(TARGET,context,p,TYPES)


@pytest.mark.parametrize('ranges',[[],[(0,1),(2,3)]])
def test_missing_or_multiple_ranges_are_unknown(ranges):
    p=pattern('abc',ranges)
    assert windows._ContextBookmarks().create(TARGET,p,TYPES)==windows.TextContext()
    assert not p.document.reads


def test_oversized_or_unsupported_context_never_returns_partial_text():
    p=pattern('a'*(windows.MAX_CONTEXT_CHARS+1),((0,windows.MAX_CONTEXT_CHARS+1),))
    assert windows._ContextBookmarks().create(TARGET,p,TYPES)==windows.TextContext()
    assert p.document.reads[0][2]==windows.MAX_CONTEXT_CHARS+1
    assert windows._ContextBookmarks().create(TARGET,object(),TYPES)==windows.TextContext()
    p=pattern('abc',((1,1),));p.ranges[0].Clone=lambda:None
    assert windows._ContextBookmarks().create(TARGET,p,TYPES)==windows.TextContext()


def test_capture_rechecks_content_before_issuing_token():
    p=pattern();original=p.GetSelection;calls=[]
    def changing_selection():
        calls.append(True)
        if len(calls)==2:p.document.text='before replaced after'
        return original()
    p.GetSelection=changing_selection
    bookmarks=windows._ContextBookmarks()
    assert bookmarks.create(TARGET,p,TYPES)==windows.TextContext() and not bookmarks.entries


def test_context_bookmarks_are_bounded_and_expire(monkeypatch):
    clock=[100.];monkeypatch.setattr(windows.time,'monotonic',lambda:clock[0])
    bookmarks=windows._ContextBookmarks(limit=2,ttl=10);p=pattern()
    contexts=[bookmarks.create(TARGET,p,TYPES) for _ in range(3)]
    assert len(bookmarks.entries)==2 and not bookmarks.matches(TARGET,contexts[0],p,TYPES)
    clock[0]=110.
    assert not bookmarks.matches(TARGET,contexts[-1],p,TYPES) and not bookmarks.entries


class Element:
    def __init__(self,p,*,password=False,read_only=False):
        self.pattern=p;self.password=password;self.read_only=read_only;self.requests=[]
        self.CurrentProcessId=12;self.CurrentHasKeyboardFocus=True;self.CurrentIsEnabled=True
        self.CurrentIsPassword=password
    def GetRuntimeId(self):return (42,1)
    def GetCurrentPattern(self,ident):
        self.requests.append(ident)
        if self.password:pytest.fail('Password fields must not expose patterns or text.')
        if ident==TYPES.UIA_ValuePatternId:
            value=SimpleNamespace(CurrentIsReadOnly=self.read_only)
            return SimpleNamespace(QueryInterface=lambda interface:value)
        return self.pattern


def answer(monkeypatch,element,operation='context',expected=TARGET,payload=None,contexts=None):
    monkeypatch.setattr(windows,'_native_target',lambda:expected)
    automation=SimpleNamespace(GetFocusedElement=lambda:element)
    return windows._FocusReader._answer(automation,TYPES,operation,expected,payload,
                                       windows._SelectionBookmarks(),contexts or windows._ContextBookmarks())


def test_worker_allows_read_only_selection_for_context_but_not_legacy_writes(monkeypatch):
    p=pattern();element=Element(p,read_only=True);contexts=windows._ContextBookmarks()
    context=answer(monkeypatch,element,expected=READ_ONLY,contexts=contexts)
    assert context.state=='selection' and context.text=='selected'
    assert answer(monkeypatch,element,'context_matches',READ_ONLY,context,contexts)
    assert answer(monkeypatch,element,'bookmark',READ_ONLY) is None


def test_worker_password_context_and_bookmarks_never_read_patterns(monkeypatch):
    p=pattern();element=Element(p,password=True)
    assert answer(monkeypatch,element,expected=READ_ONLY) is None
    assert answer(monkeypatch,element,'focus',READ_ONLY)==((42,1),12,False)
    assert not element.requests and not p.document.reads


def test_worker_rechecks_focus_after_read_and_discards_stale_text(monkeypatch):
    p=pattern();element=Element(p);original=p.GetSelection;other=windows.Target(20,21,22)
    def changing_focus():
        result=original();monkeypatch.setattr(windows,'_native_target',lambda:other);return result
    p.GetSelection=changing_focus
    assert answer(monkeypatch,element) is None


def test_public_context_api_is_bounded_and_never_injects_keys(monkeypatch):
    calls=[];context=windows.TextContext('selection','selected','token')
    def request(operation,target,payload=None):
        calls.append((operation,target,payload));return context if operation=='context' else payload==context
    monkeypatch.setattr(windows,'_reader',SimpleNamespace(request=request))
    monkeypatch.setattr(windows,'window_valid',lambda target:True)
    monkeypatch.setattr(windows,'chord',lambda *args:pytest.fail('Context capture injected a key.'))
    assert windows.text_context(READ_ONLY)==context and windows.context_matches(READ_ONLY,context)
    assert windows.text_context(windows.Target(10,11,12))==windows.TextContext()
    assert not windows.context_matches(READ_ONLY,windows.TextContext())
    assert calls==[('context',READ_ONLY,None),('context_matches',READ_ONLY,context)]


def test_public_timeout_unknown_and_changed_native_focus_discard_context(monkeypatch):
    monkeypatch.setattr(windows,'window_valid',lambda target:True)
    monkeypatch.setattr(windows,'_reader',SimpleNamespace(request=lambda *args:None))
    assert windows.text_context(TARGET)==windows.TextContext()
    assert not windows.context_matches(TARGET,windows.TextContext('caret','','token'))
    checks=iter((True,False));monkeypatch.setattr(windows,'window_valid',lambda target:next(checks))
    monkeypatch.setattr(windows,'_reader',SimpleNamespace(request=lambda *args:windows.TextContext('selection','private','token')))
    assert windows.text_context(TARGET)==windows.TextContext()


def test_public_reader_errors_fail_closed(monkeypatch):
    monkeypatch.setattr(windows,'window_valid',lambda target:True)
    def broken(*args):raise RuntimeError('UIA provider unavailable')
    monkeypatch.setattr(windows,'_reader',SimpleNamespace(request=broken))
    assert windows.text_context(TARGET)==windows.TextContext()
    assert not windows.context_matches(TARGET,windows.TextContext('caret','','token'))


def test_expired_queued_request_does_not_read_any_context(monkeypatch):
    monkeypatch.setattr(windows.time,'monotonic',lambda:10.)
    monkeypatch.setattr(windows._FocusReader,'_answer',lambda *args:pytest.fail('Expired context read was executed.'))
    done=threading.Event();result=[]
    request=('context',TARGET,None,done,result,9.)
    windows._FocusReader._serve(request,None,None,windows._SelectionBookmarks(),windows._ContextBookmarks())
    assert done.is_set() and result==[]


def test_late_provider_response_is_not_retained_in_request_result(monkeypatch):
    clock=[10.];monkeypatch.setattr(windows.time,'monotonic',lambda:clock[0])
    def late_answer(*args):
        clock[0]=11.;return windows.TextContext('selection','private','token')
    monkeypatch.setattr(windows._FocusReader,'_answer',late_answer)
    done=threading.Event();result=[]
    request=('context',TARGET,None,done,result,10.5)
    windows._FocusReader._serve(request,None,None,windows._SelectionBookmarks(),windows._ContextBookmarks())
    assert done.is_set() and result==[]


def test_unsupported_caret_movement_and_invalid_text_fail_closed():
    p=pattern('abc',((1,1),))
    cloned=Range(p.document,1,1);cloned.MoveEndpointByUnit=lambda *args:None
    p.ranges[0].Clone=lambda:cloned
    assert windows._ContextBookmarks().create(TARGET,p,TYPES)==windows.TextContext()
    assert windows._ContextBookmarks().create(TARGET,pattern('a\0b',((0,3),)),TYPES)==windows.TextContext()


def test_warmup_starts_worker_once_without_identity_or_text_request(monkeypatch):
    calls=[]
    reader=SimpleNamespace(request=lambda *args:pytest.fail('Warmup must not read identity or text.'))
    def create():calls.append('created');return reader
    monkeypatch.setattr(windows,'_reader',None)
    monkeypatch.setattr(windows,'_FocusReader',create)
    monkeypatch.setattr(windows,'_native_target',lambda:pytest.fail('Warmup must not inspect a target.'))
    windows.prepare_text_context();windows.prepare_text_context()
    assert windows._reader is reader and calls==['created']

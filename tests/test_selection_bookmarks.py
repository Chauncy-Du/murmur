from types import SimpleNamespace
import pytest
from murmur import windows


TYPES=SimpleNamespace(TextPatternRangeEndpoint_Start=0,TextPatternRangeEndpoint_End=1)
TARGET=windows.Target(10,11,12,(42,1),12,True)


class Range:
    def __init__(self,start,end):self.ends=(start,end)
    def Clone(self):return Range(*self.ends)
    def CompareEndpoints(self,endpoint,other,other_endpoint):return self.ends[endpoint]-other.ends[other_endpoint]
    def GetText(self,*args):pytest.fail('Bookmarks must never read document text')


class Pattern:
    def __init__(self,ranges):self.ranges=ranges
    def GetSelection(self):return SimpleNamespace(Length=len(self.ranges),GetElement=lambda index:self.ranges[index])


def test_same_text_at_different_location_is_rejected_by_both_endpoints():
    bookmarks=windows._SelectionBookmarks();pattern=Pattern([Range(0,6)])
    token=bookmarks.create(TARGET,pattern,TYPES)
    assert isinstance(token,str) and bookmarks.matches(TARGET,token,pattern,TYPES)
    pattern.ranges=[Range(9,15)]  # The identical word "repeat" at another position.
    assert not bookmarks.matches(TARGET,token,pattern,TYPES)
    pattern.ranges=[Range(0,5)];assert not bookmarks.matches(TARGET,token,pattern,TYPES)
    pattern.ranges=[Range(1,6)];assert not bookmarks.matches(TARGET,token,pattern,TYPES)


@pytest.mark.parametrize('ranges',[[],[Range(2,2)],[Range(0,2),Range(5,7)]])
def test_empty_caret_and_multiple_selection_fail_closed(ranges):
    assert windows._SelectionBookmarks().create(TARGET,Pattern(ranges),TYPES) is None


def test_unsupported_pattern_provider_error_and_target_change_fail_closed():
    bookmarks=windows._SelectionBookmarks();pattern=Pattern([Range(0,6)]);token=bookmarks.create(TARGET,pattern,TYPES)
    other=windows.Target(10,11,12,(42,2),12,True)
    assert not bookmarks.matches(other,token,pattern,TYPES)
    assert bookmarks.create(TARGET,object(),TYPES) is None
    assert not bookmarks.matches(TARGET,token,object(),TYPES)


def test_bookmark_cache_is_bounded_and_expires(monkeypatch):
    clock=[100.];monkeypatch.setattr(windows.time,'monotonic',lambda:clock[0])
    bookmarks=windows._SelectionBookmarks(limit=2,ttl=10);pattern=Pattern([Range(0,6)])
    tokens=[bookmarks.create(TARGET,pattern,TYPES) for _ in range(3)]
    assert len(bookmarks.entries)==2 and not bookmarks.matches(TARGET,tokens[0],pattern,TYPES)
    clock[0]=110.;assert not bookmarks.matches(TARGET,tokens[-1],pattern,TYPES) and not bookmarks.entries


def test_public_bookmark_api_passes_only_opaque_tokens_and_rejects_unknown(monkeypatch):
    requests=[]
    def request(operation,target,payload=None):requests.append((operation,target,payload));return 'opaque-token' if operation=='bookmark' else payload=='opaque-token'
    monkeypatch.setattr(windows,'_reader',SimpleNamespace(request=request))
    monkeypatch.setattr(windows,'window_valid',lambda target:True)
    token=windows.selection_bookmark(TARGET)
    assert token=='opaque-token' and windows.selection_matches(TARGET,token)
    assert not windows.selection_matches(TARGET,'unknown')
    assert windows.selection_bookmark(windows.Target(10,11,12)) is None
    assert not windows.selection_matches(windows.Target(10,11,12),token)
    assert requests==[('bookmark',TARGET,None),('matches',TARGET,'opaque-token'),('matches',TARGET,'unknown')]


def test_public_api_timeout_is_preview_only(monkeypatch):
    monkeypatch.setattr(windows,'_reader',SimpleNamespace(request=lambda *args:None))
    monkeypatch.setattr(windows,'window_valid',lambda target:True)
    assert windows.selection_bookmark(TARGET) is None and not windows.selection_matches(TARGET,'token')

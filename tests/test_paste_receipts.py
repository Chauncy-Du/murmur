from types import SimpleNamespace
import pytest
from murmur import windows
from murmur.paste_receipts import PasteReceipts,MAX_DOCUMENT_CHARS

TYPES=SimpleNamespace(TextPatternRangeEndpoint_Start=0,TextPatternRangeEndpoint_End=1)
TARGET=windows.Target(10,11,12,(1,2),12,True)


class Range:
    def __init__(self,pattern,start,end):self.pattern=pattern;self.start=start;self.end=end
    def Clone(self):return Range(self.pattern,self.start,self.end)
    def GetText(self,limit):
        assert limit==MAX_DOCUMENT_CHARS+1
        return self.pattern.text[self.start:self.end][:limit]
    def CompareEndpoints(self,endpoint,other,other_endpoint):
        return (self.start if endpoint==0 else self.end)-(other.start if other_endpoint==0 else other.end)
    def MoveEndpointByRange(self,endpoint,other,other_endpoint):
        value=other.start if other_endpoint==0 else other.end
        if endpoint==0:self.start=value
        else:self.end=value


class Pattern:
    def __init__(self,text,start,end=None):self.text=text;self.start=start;self.end=start if end is None else end
    @property
    def DocumentRange(self):return Range(self,0,len(self.text))
    def GetSelection(self):return SimpleNamespace(Length=1,GetElement=lambda index:Range(self,self.start,self.end))


@pytest.mark.parametrize('source,start,end,inserted,expected',[
    ('before after',7,7,'new ','before new after'),
    ('before old after',7,10,'new','before new after'),
    ('',0,0,'第一行\n第二行😀','第一行\r\n第二行😀'),
])
def test_confirms_actual_document_change_not_merely_sent_key(source,start,end,inserted,expected):
    p=Pattern(source,start,end);receipts=PasteReceipts()
    token=receipts.create(TARGET,inserted,p,TYPES)
    assert token and receipts.ready(TARGET,token,p,TYPES)
    assert not receipts.verified(TARGET,token,p,TYPES)
    p.text=expected
    assert receipts.verified(TARGET,token,p,TYPES)
    assert token not in receipts.entries


def test_ignored_paste_does_not_pass_when_identical_text_was_already_after_caret():
    p=Pattern('same',0);receipts=PasteReceipts();token=receipts.create(TARGET,'same',p,TYPES)
    assert not receipts.verified(TARGET,token,p,TYPES)


def test_user_can_continue_typing_after_insert_without_false_failure():
    p=Pattern('left right',5);receipts=PasteReceipts();token=receipts.create(TARGET,'new ',p,TYPES)
    p.text='left new more typing right'
    assert receipts.verified(TARGET,token,p,TYPES)


def test_preexisting_prefix_or_suffix_changed_never_confirms():
    for current in ('changed new right','left wrong right','left new changed'):
        p=Pattern('left right',5);receipts=PasteReceipts();token=receipts.create(TARGET,'new ',p,TYPES)
        p.text=current
        assert not receipts.verified(TARGET,token,p,TYPES)


def test_caret_move_and_document_change_before_paste_block_delivery():
    p=Pattern('repeat repeat',0);receipts=PasteReceipts();token=receipts.create(TARGET,'new ',p,TYPES)
    p.start=p.end=7
    assert not receipts.ready(TARGET,token,p,TYPES)
    p.start=p.end=0;p.text='changed repeat'
    assert not receipts.ready(TARGET,token,p,TYPES)


def test_legacy_value_receipt_handles_utf16_selection_and_preserves_clipboard_independence():
    receipts=PasteReceipts()
    token=receipts.create_value(TARGET,'新','A😀oldZ',(3,6))
    assert token and receipts.ready_value(TARGET,token,'A😀oldZ',(3,6))
    assert not receipts.ready_value(TARGET,token,'A😀oldZ',(4,6))
    assert not receipts.verified_value(TARGET,token,'A😀oldZ')
    assert receipts.verified_value(TARGET,token,'A😀新Z')


def test_legacy_value_receipt_handles_empty_field_and_continued_typing():
    receipts=PasteReceipts();token=receipts.create_value(TARGET,'Hello','',(0,0))
    assert receipts.ready_value(TARGET,token,'',(0,0))
    assert not receipts.verified_value(TARGET,token,'')
    assert receipts.verified_value(TARGET,token,'Hello more typing')


@pytest.mark.parametrize('value,selection', [('short',(0,99)),('short',(-1,0)),('short',(3,2)),('bad\0text',(0,0)),('x'*(MAX_DOCUMENT_CHARS+1),(0,0))],ids=['past-end','negative','reversed','nul','oversized'])
def test_invalid_native_value_snapshot_never_creates_receipt(value,selection):
    assert PasteReceipts().create_value(TARGET,'new',value,selection) is None


def test_receipts_store_hashes_and_ranges_not_document_or_inserted_text():
    p=Pattern('private document',3);receipts=PasteReceipts();token=receipts.create(TARGET,'private dictated text',p,TYPES)
    entry=receipts.entries[token]
    assert not hasattr(entry,'text') and not hasattr(entry,'before') and not hasattr(entry,'after')
    assert len(entry.before_digest)==len(entry.after_digest)==64


def test_unknown_oversized_readonly_and_expired_receipts_refuse_confirmation(monkeypatch):
    receipts=PasteReceipts();p=Pattern('x'*(MAX_DOCUMENT_CHARS+1),0)
    assert receipts.create(TARGET,'new',p,TYPES) is None
    assert receipts.create(windows.Target(10,11,12), 'new',Pattern('text',0),TYPES) is None
    assert receipts.create(TARGET,'new',object(),TYPES) is None
    p=Pattern('text',0);token=receipts.create(TARGET,'new',p,TYPES)
    assert not receipts.verified(windows.Target(10,11,13,(1,2),13,True),token,p,TYPES)
    created=receipts.entries[token].created
    monkeypatch.setattr('murmur.paste_receipts.time.monotonic',lambda:created+11)
    assert not receipts.ready(TARGET,token,p,TYPES)

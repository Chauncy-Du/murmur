"""Synthetic clipboard fixture recovery; no personal clipboard is accessed."""
from contextlib import contextmanager
from scripts.ask_clipboard_fixture import exact_fixture,restore_snapshot


def unicode(text):return text.encode('utf-16-le')+b'\0\0'
MARKER='MurMur public clipboard smoke fixture test-only-token.'
ORIGINAL={49491:b'Synthetic original HTML',13:unicode('Synthetic original text')}


class Clipboard:
    def __init__(self):
        self.values={13:unicode(MARKER)};self.actual_owner=0;self.open_owner=None;self.revision=10
        self.owner_failures=0;self.verify_failures=0;self.partial_write_failure=False;self.mutations=0
    @contextmanager
    def opened(self,owner):
        self.open_owner=owner
        try:yield self
        finally:self.open_owner=None
    def owner(self):
        if self.owner_failures:self.owner_failures-=1;raise RuntimeError('Transient owner query failure')
        return self.actual_owner
    def sequence(self):return self.revision
    def formats(self):return list(self.values)
    def data(self,ident):
        if self.verify_failures and self.mutations:
            self.verify_failures-=1;raise RuntimeError('Transient verification failure')
        return self.values[ident]
    def prepare(self,values):return [[ident,bytes(data)] for ident,data in values]
    def replace(self,values):
        self.values={};self.actual_owner=self.open_owner;self.revision+=1;self.mutations+=1
        for entry in values:
            self.values[entry[0]]=entry[1];entry[1]=None
            if self.partial_write_failure:self.partial_write_failure=False;raise RuntimeError('Transient partial write failure')
    def release(self,values):
        for entry in values:entry[1]=None


def restore(clipboard,**kwargs):
    metadata={}
    result=restore_snapshot(clipboard,777,list(ORIGINAL.items()),MARKER,10,metadata,pause=lambda seconds:None,**kwargs)
    return result,metadata


def test_equivalent_synthesized_text_formats_are_safe_but_rich_or_other_text_is_not():
    clipboard=Clipboard()
    clipboard.values.update({1:MARKER.encode('ascii')+b'\0',7:MARKER.encode('ascii')+b'\0',16:b'\x09\x04\0\0'})
    assert exact_fixture(clipboard,MARKER,{13})
    clipboard.values[49491]=b'Synthetic newer HTML'
    assert not exact_fixture(clipboard,MARKER,{13})
    del clipboard.values[49491];clipboard.values[1]=b'Different new text\0'
    assert not exact_fixture(clipboard,MARKER,{13})


def test_invalid_locale_refuses_fixture_matching():
    clipboard=Clipboard();clipboard.values[16]=b'\xff\xff\xff\xff'
    assert not exact_fixture(clipboard,MARKER,{13})


def test_zero_owner_and_synthesized_formats_restore_original_bytes():
    clipboard=Clipboard();clipboard.values.update({1:MARKER.encode()+b'\0',7:MARKER.encode()+b'\0'})
    result,metadata=restore(clipboard)
    assert result==0 and metadata['restored'] and clipboard.values==ORIGINAL


def test_transient_owner_error_keeps_backup_and_retries():
    clipboard=Clipboard();clipboard.owner_failures=2;reports=[]
    result,metadata=restore(clipboard,report=lambda:reports.append(True))
    assert result==0 and clipboard.values==ORIGINAL
    assert metadata['restore_attempts']==2 and not metadata['original_snapshot_retained_in_ram']


def test_partial_restore_uses_complete_preallocated_rollback():
    clipboard=Clipboard();clipboard.partial_write_failure=True
    result,metadata=restore(clipboard)
    assert result==0 and metadata['restored'] and clipboard.values==ORIGINAL and clipboard.mutations==2


def test_transient_readback_error_keeps_full_backup_until_verified():
    clipboard=Clipboard();clipboard.verify_failures=1
    result,metadata=restore(clipboard)
    assert result==0 and metadata['restore_attempts']==1 and clipboard.values==ORIGINAL


def test_new_content_during_wait_is_never_overwritten():
    clipboard=Clipboard();clipboard.values={13:unicode('Synthetic new user copy')};clipboard.revision+=1
    result,metadata=restore(clipboard)
    assert result==3 and metadata['changed'] and not metadata['restored'] and clipboard.mutations==0


def test_known_partial_install_revision_can_recover_without_marker_text():
    clipboard=Clipboard();clipboard.values={};clipboard.actual_owner=777
    result,metadata=restore(clipboard,owned_revision=clipboard.revision)
    assert result==0 and metadata['restored'] and clipboard.values==ORIGINAL


def test_new_copy_after_partial_install_revision_is_preserved():
    clipboard=Clipboard();clipboard.values={13:unicode('Synthetic new copy')};clipboard.actual_owner=55
    result,metadata=restore(clipboard,owned_revision=clipboard.revision-1)
    assert result==3 and metadata['changed'] and clipboard.mutations==0

"""Temporarily provide public plain text for native Ask smoke tests.

The original concrete HGLOBAL formats stay only in this process's RAM. Windows
may materialize delayed-rendered formats while they are read; restoring their
bytes does not restore the original owner's delayed-rendering semantics. GDI,
owner-display, private-handle, unreadable and oversized formats are refused.
Nothing is replaced unless every original format has a complete snapshot.
Restoration requires the exact public fixture and text-only format set under
the clipboard lock; newer unrelated clipboard content is never overwritten.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

# Standard clipboard formats documented as movable global-memory data. Bitmap,
# palette, metafile, owner-display and private/GDI-handle ranges are excluded.
HGLOBAL_FORMATS=frozenset((1,4,5,6,7,8,10,11,12,13,15,16,17))
TEXT_FORMATS=frozenset((1,7,13,16))


def arguments():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=float,default=90.,help='Wait duration, 0.1–600 seconds; default 90.')
    parser.add_argument('--restore-signal',type=Path,help='Restore early when this previously absent file appears.')
    parser.add_argument('--json-file',type=Path,help='Optional metadata-only JSON report; parent directory must exist.')
    parser.add_argument('--inspect',action='store_true',help='Inspect format metadata only; do not read content or modify clipboard.')
    parser.add_argument('--max-format-mib',type=int,default=8)
    parser.add_argument('--max-total-mib',type=int,default=32)
    args=parser.parse_args()
    if not .1<=args.seconds<=600:parser.error('--seconds must be 0.1–600')
    if not 1<=args.max_format_mib<=32 or not args.max_format_mib<=args.max_total_mib<=128:
        parser.error('Use a per-format limit of 1–32 MiB and a total limit between that value and 128 MiB')
    if args.json_file:
        args.json_file=args.json_file.resolve()
        if not args.json_file.parent.is_dir():parser.error('--json-file parent must exist')
    if args.restore_signal:
        args.restore_signal=args.restore_signal.resolve()
        if args.restore_signal.exists():parser.error('--restore-signal must initially be absent')
    return args


def publish(metadata,args):
    # Evidence failures never interrupt clipboard restoration.
    payload=json.dumps(metadata,ensure_ascii=True)
    try:print(payload,flush=True)
    except OSError:pass
    if args.json_file:
        temporary=args.json_file.with_suffix(args.json_file.suffix+'.tmp')
        try:
            temporary.write_text(payload+'\n','utf-8');temporary.replace(args.json_file)
        except OSError:pass


def allowed_format(format_id):
    return format_id in HGLOBAL_FORMATS or 0xC000<=format_id<=0xFFFF


def format_metadata(native):
    result=[]
    for ident in native.formats():
        try:name=native.api.GetClipboardFormatName(ident)
        except Exception:name='standard'
        result.append({'id':ident,'name':name,'supported_hglobal_candidate':allowed_format(ident)})
    return result


def exact_fixture(native,text,format_set=None):
    """Allow synthesized equivalent text formats; never return their content."""
    from murmur.clipboard import decode_unicode
    current=set(native.formats())
    if not current.issubset(TEXT_FORMATS) or 13 not in current:return False
    if format_set is not None and not set(format_set).issubset(TEXT_FORMATS):return False
    if decode_unicode(native.data(13))!=text:return False
    for ident in current.intersection((1,7)):
        value=native.data(ident).split(b'\0',1)[0]
        if value!=text.encode('ascii'):return False
    if 16 in current:
        locale=native.data(16)
        if len(locale)<4 or len(locale)>16:return False
        is_valid=ctypes.WinDLL('kernel32',use_last_error=True).IsValidLocale
        is_valid.argtypes=[wintypes.DWORD,wintypes.DWORD];is_valid.restype=wintypes.BOOL
        if not is_valid(int.from_bytes(locale[:4],'little'),2):return False
    return True


def restore_snapshot(native,owner,saved,fixture,fixture_sequence,metadata,*,pump=None,report=None,pause=time.sleep,
                     original_prepared=None,rollback_prepared=None,owned_revision=None):
    """Keep the RAM backup alive until restored or newer content is confirmed.

    Transient owner/read/lock failures never mean the backup may be discarded.
    An interrupted partial restore is retried only while its exact owned
    revision still matches; otherwise the newer clipboard remains untouched.
    """
    pump=pump or (lambda:None);report=report or (lambda:None)
    recovery_revision=owned_revision;recovery_owner=owner if owned_revision is not None else None
    attempt=0;last_report=0.;attempted_restore=owned_revision is not None
    while True:
        prepared=[];rollback=[]
        try:
            pump()
            with native.opened(owner):
                sequence=native.sequence();current_owner=native.owner()
                if recovery_revision is not None:
                    unchanged=sequence==recovery_revision and current_owner==recovery_owner
                elif attempted_restore:
                    # A failed sequence query after our write cannot establish
                    # a revision. Only our still-live hidden owner plus exact
                    # original bytes in every present format can recover it.
                    original=dict(saved);current=native.formats()
                    unchanged=(current_owner==owner and set(current).issubset(original) and
                               all(native.data(ident)==original[ident] for ident in current))
                else:
                    unchanged=exact_fixture(native,fixture)
                    unchanged=unchanged and native.sequence()==sequence and native.owner()==current_owner
                if not unchanged:
                    metadata.update(status='new_content_preserved',changed=True,restored=False,
                                    original_snapshot_retained_in_ram=False)
                    report();return 3
                metadata['fixture_revision_changed']=sequence!=fixture_sequence
                prepared=original_prepared if original_prepared is not None else native.prepare(saved)
                rollback=rollback_prepared if rollback_prepared is not None else native.prepare(saved)
                original_prepared=None;rollback_prepared=None
                try:
                    attempted_restore=True
                    try:native.replace(prepared)
                    except Exception:native.replace(rollback)
                finally:
                    # Only a restore attempted by this helper can establish
                    # this recovery revision, while no other writer intervenes.
                    recovery_revision=native.sequence();recovery_owner=owner
                restored_formats=native.formats()
                verified=(set(restored_formats)==set(ident for ident,_ in saved) and
                          all(native.data(ident)==data for ident,data in saved))
                if not verified:raise RuntimeError('Restored format verification failed.')
                metadata.update(status='restored',restored=True,restored_format_count=len(restored_formats),
                                original_snapshot_retained_in_ram=False)
                report();return 0
        except (Exception,KeyboardInterrupt) as exc:
            attempt+=1
            metadata.update(status='restore_pending',reason=type(exc).__name__,restore_attempts=attempt,
                            original_snapshot_retained_in_ram=True)
            if time.monotonic()-last_report>=1.:
                last_report=time.monotonic();report()
            # Keep trying with the full RAM snapshot instead of exiting and
            # irretrievably losing private data after a transient API error.
            pause(min(.5,.05*attempt))
        finally:
            native.release(prepared);native.release(rollback)


def run(args):
    import win32api
    import win32con
    import win32gui
    from murmur.clipboard import ClipboardBusy,NativeClipboard

    native=NativeClipboard();native.MAX_BYTES=args.max_format_mib*1024*1024
    metadata={
        'pid':os.getpid(),'status':'initializing','changed':False,'restored':False,
        'original_content_printed_or_persisted':False,'delayed_materialization_permitted':True,
        'limitation':'Concrete HGLOBAL bytes are preserved; original owner and delayed-rendering semantics are not restored.',
    }
    class_name=f'MurMurAskClipboardFixture-{os.getpid()}'
    window_class=win32gui.WNDCLASS();window_class.hInstance=win32api.GetModuleHandle(None)
    window_class.lpszClassName=class_name;window_class.lpfnWndProc=win32gui.DefWindowProc
    win32gui.RegisterClass(window_class)
    owner=win32gui.CreateWindowEx(win32con.WS_EX_NOACTIVATE|win32con.WS_EX_TOOLWINDOW,
        class_name,'',win32con.WS_POPUP,0,0,0,0,0,0,window_class.hInstance,None)
    saved=[];fixture_prepared=[];original_prepared=[];rollback_prepared=[]
    installed=False;owned_revision=None
    fixture='MurMur public clipboard smoke fixture '+uuid.uuid4().hex+'.'
    fixture_formats=set()
    try:
        with native.opened(owner):
            before_sequence=native.sequence();before_owner=native.owner()
            info=format_metadata(native)
            metadata.update(original_format_count=len(info),original_formats=info)
            unsupported=[item['id'] for item in info if not item['supported_hglobal_candidate']]
            if args.inspect:
                metadata['status']='inspected';publish(metadata,args);return 0
            if unsupported or len(info)>256:
                metadata.update(status='refused',reason='Unsupported format or too many formats.',unsupported_formats=unsupported)
                publish(metadata,args);return 2
            total=0
            for item in info:
                # GetClipboardData/GlobalSize/GlobalLock must all succeed. A
                # registered format is accepted only as concrete raw HGLOBAL.
                try:data=native.data(item['id'])
                except Exception:
                    metadata.update(status='refused',reason='An original format is unreadable, non-HGLOBAL, or oversized.',failed_format=item['id'])
                    publish(metadata,args);return 2
                total+=len(data);item['bytes']=len(data)
                if total>args.max_total_mib*1024*1024:
                    metadata.update(status='refused',reason='The original clipboard exceeds the total snapshot limit.')
                    publish(metadata,args);return 2
                saved.append((item['id'],data))
            if (native.sequence()!=before_sequence or native.owner()!=before_owner or
                native.formats()!=[item['id'] for item in info]):
                metadata.update(status='refused',reason='Owner, revision, or formats changed while snapshotting.')
                publish(metadata,args);return 2
        # Allocate restoration and immediate-rollback buffers before mutation.
        original_prepared=native.prepare(saved)
        rollback_prepared=native.prepare(saved)
        fixture_prepared=native.prepare([(13,fixture.encode('utf-16-le')+b'\0\0')])
        with native.opened(owner):
            if native.sequence()!=before_sequence or native.owner()!=before_owner:
                metadata.update(status='refused',reason='The clipboard changed before fixture installation.')
                publish(metadata,args);return 2
            installed=True
            try:native.replace(fixture_prepared)
            except Exception:
                try:native.replace(rollback_prepared)
                except Exception:
                    owned_revision=native.sequence()
                    raise
                installed=False
                metadata.update(status='refused',reason='Fixture installation failed; original buffers were restored.',restored=True)
                publish(metadata,args);return 2
            fixture_sequence=native.sequence();fixture_formats=set(native.formats())
            if not exact_fixture(native,fixture,fixture_formats):
                try:native.replace(original_prepared)
                except Exception:
                    owned_revision=native.sequence()
                    raise
                installed=False
                metadata.update(status='refused',reason='The installed fixture could not be verified.',restored=True)
                publish(metadata,args);return 2
        metadata.update(status='fixture_ready',fixture_text=fixture,fixture_format_count=len(fixture_formats),
                        fixture_sequence=fixture_sequence,original_total_bytes=sum(len(data) for _,data in saved))
        publish(metadata,args)
        deadline=time.monotonic()+args.seconds
        try:
            while time.monotonic()<deadline and not (args.restore_signal and args.restore_signal.exists()):
                # Clipboard ownership can receive synchronous destroy messages
                # from the production assistant. Pump only this hidden window's
                # thread; no foreground activation or input is synthesized.
                win32gui.PumpWaitingMessages();time.sleep(.05)
        except KeyboardInterrupt:
            metadata['interrupted']=True
        result=restore_snapshot(native,owner,saved,fixture,fixture_sequence,metadata,
                                pump=win32gui.PumpWaitingMessages,report=lambda:publish(metadata,args),
                                original_prepared=original_prepared,rollback_prepared=rollback_prepared)
        installed=False
        return result
    except Exception as exc:
        metadata.update(status='refused' if not installed else 'restore_pending',reason=type(exc).__name__)
        publish(metadata,args)
        if installed:
            result=restore_snapshot(native,owner,saved,fixture,0,metadata,
                                    pump=win32gui.PumpWaitingMessages,report=lambda:publish(metadata,args),
                                    owned_revision=owned_revision)
            installed=False;return result
        return 4
    finally:
        native.release(fixture_prepared);native.release(original_prepared);native.release(rollback_prepared)
        saved.clear()
        win32gui.DestroyWindow(owner)
        win32gui.UnregisterClass(class_name,window_class.hInstance)


def main():
    args=arguments()
    if sys.platform!='win32':raise SystemExit('This fixture requires native Windows clipboard APIs.')
    return run(args)


if __name__=='__main__':raise SystemExit(main())

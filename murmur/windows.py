import ctypes
import hashlib
import os
import queue
import threading
import sys
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from PySide6.QtWidgets import QApplication
from .clipboard import ClipboardBusy
from .paste_receipts import PasteReceipts,MAX_DOCUMENT_CHARS

@dataclass(frozen=True)
class Target:
    hwnd: int
    focus: int
    pid: int
    uia_id: tuple = ()
    uia_pid: int = 0
    editable: bool = False

MAX_CONTEXT_CHARS = 12000

@dataclass(frozen=True)
class TextContext:
    """One focused UIA selection or caret; bookmarks never contain plain text."""
    state: str = 'unknown'
    text: str = ''
    bookmark: str | None = None

class GUIINFO(ctypes.Structure):
    _fields_=[('cbSize',ctypes.c_ulong),('flags',ctypes.c_ulong),('hwndActive',ctypes.c_void_p),('hwndFocus',ctypes.c_void_p),('hwndCapture',ctypes.c_void_p),('hwndMenuOwner',ctypes.c_void_p),('hwndMoveSize',ctypes.c_void_p),('hwndCaret',ctypes.c_void_p),('rcCaret',ctypes.c_long*4)]

def _native_target():
    import win32gui,win32process
    hwnd=win32gui.GetForegroundWindow()
    if not hwnd: return Target(0,0,0)
    thread,pid=win32process.GetWindowThreadProcessId(hwnd)
    info=GUIINFO(); info.cbSize=ctypes.sizeof(info)
    if not ctypes.windll.user32.GetGUIThreadInfo(thread,ctypes.byref(info)):return Target(hwnd,0,pid)
    return Target(hwnd,int(info.hwndFocus or 0),pid)

def _native_equal(first,second):
    return bool(first and second and (first.hwnd,first.focus,first.pid)==(second.hwnd,second.focus,second.pid))


def _edit_message(hwnd,message,wparam=0,lparam=0):
    """Bounded native EDIT messages with a short timeout for unresponsive apps."""
    send=ctypes.windll.user32.SendMessageTimeoutW
    send.argtypes=(ctypes.c_void_p,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t,
                   ctypes.c_uint,ctypes.c_uint,ctypes.POINTER(ctypes.c_size_t))
    send.restype=ctypes.c_size_t
    answer=ctypes.c_size_t()
    if not send(hwnd,message,wparam,lparam,2,100,ctypes.byref(answer)):return None
    return answer.value


def _native_edit_state(expected):
    import win32gui,win32con
    if not window_valid(expected):return None
    if win32gui.GetClassName(expected.focus).casefold() not in ('edit','richedit','richedit20a','richedit20w','richedit50w'):return None
    if win32gui.GetWindowLong(expected.focus,win32con.GWL_STYLE)&(win32con.ES_PASSWORD|win32con.ES_READONLY):return None
    start=ctypes.c_ulong();end=ctypes.c_ulong()
    if _edit_message(expected.focus,win32con.EM_GETSEL,ctypes.addressof(start),ctypes.addressof(end)) is None:return None
    length=_edit_message(expected.focus,win32con.WM_GETTEXTLENGTH)
    if length is None or length>MAX_DOCUMENT_CHARS*2 or not 0<=start.value<=end.value<=length:return None
    return (start.value,end.value),length


def insert_native_edit(expected,text,*,guard=None,receipt=None):
    """Insert into a confirmed standard EDIT/RichEdit, preserving the clipboard."""
    import win32con
    if not isinstance(text,str) or not text.strip() or '\0' in text:return False
    if not valid(expected) or _native_edit_state(expected) is None:return False
    if receipt and not paste_ready(expected,receipt):raise RuntimeError('The cursor or input changed · Copy to use')
    if guard and not guard():raise RuntimeError('Input changed. Copy the result instead.')
    if not window_valid(expected):raise RuntimeError('The target changed · Copy to use')
    buffer=ctypes.create_unicode_buffer(text)
    if _edit_message(expected.focus,win32con.EM_REPLACESEL,1,ctypes.addressof(buffer)) is None:
        raise RuntimeError('Input did not confirm delivery · Review your result')
    return True

class _SelectionBookmarks:
    """MTA-owned COM ranges. Tokens are the only values crossing threads."""
    def __init__(self,limit=8,ttl=600):
        self.entries=OrderedDict();self.limit=limit;self.ttl=ttl
    def _expire(self):
        now=time.monotonic()
        for key,(_,_,created) in list(self.entries.items()):
            if now-created>=self.ttl:self.entries.pop(key,None)
    @staticmethod
    def _selected(pattern,types):
        ranges=pattern.GetSelection()
        if not ranges or int(ranges.Length)!=1:return None
        selected=ranges.GetElement(0)
        if not selected:return None
        if selected.CompareEndpoints(types.TextPatternRangeEndpoint_Start,selected,types.TextPatternRangeEndpoint_End)==0:return None
        return selected
    @staticmethod
    def _same(first,second,types):
        return all(first.CompareEndpoints(endpoint,second,endpoint)==0 for endpoint in
                   (types.TextPatternRangeEndpoint_Start,types.TextPatternRangeEndpoint_End))
    def create(self,expected,pattern,types):
        self._expire()
        try:
            selected=self._selected(pattern,types)
            if selected is None:return None
            cloned=selected.Clone();current=self._selected(pattern,types)
            if not cloned or current is None or not self._same(current,cloned,types):return None
            token=uuid.uuid4().hex;self.entries[token]=(expected,cloned,time.monotonic())
            while len(self.entries)>self.limit:self.entries.popitem(last=False)
            return token
        except Exception:return None
    def matches(self,expected,token,pattern,types):
        self._expire()
        entry=self.entries.get(token)
        if not entry or entry[0]!=expected:return False
        try:
            current=self._selected(pattern,types)
            return bool(current is not None and self._same(current,entry[1],types))
        except Exception:return False

@dataclass(frozen=True)
class _ContextBookmark:
    target: Target
    selected: object
    state: str
    fingerprint: str
    created: float

class _ContextBookmarks:
    """MTA-owned ranges with hashes; selected text belongs only to the caller."""
    CARET_UNITS = 64
    def __init__(self,limit=8,ttl=600):
        self.entries=OrderedDict();self.limit=limit;self.ttl=ttl
    def _expire(self):
        now=time.monotonic()
        for key,entry in list(self.entries.items()):
            if now-entry.created>=self.ttl:self.entries.pop(key,None)
    @staticmethod
    def _single(pattern):
        ranges=pattern.GetSelection()
        return ranges.GetElement(0) if ranges and int(ranges.Length)==1 else None
    @staticmethod
    def _state(selected,types):
        return 'caret' if selected.CompareEndpoints(types.TextPatternRangeEndpoint_Start,selected,types.TextPatternRangeEndpoint_End)==0 else 'selection'
    @staticmethod
    def _text(selected,limit):
        value=selected.GetText(limit+1)
        if not isinstance(value,str) or len(value)>limit or '\0' in value:
            raise ValueError('UIA text is unavailable or exceeds the context limit.')
        return value
    @staticmethod
    def _digest(*values):
        return hashlib.sha256(repr(values).encode('utf-8','surrogatepass')).hexdigest()
    def _fingerprint(self,selected,state,types):
        if state=='selection':
            text=self._text(selected,MAX_CONTEXT_CHARS)
            if not text:raise ValueError('The selected range contains no text.')
            return self._digest(state,text),text
        left=selected.Clone();right=selected.Clone()
        left_units=left.MoveEndpointByUnit(types.TextPatternRangeEndpoint_Start,types.TextUnit_Character,-self.CARET_UNITS)
        right_units=right.MoveEndpointByUnit(types.TextPatternRangeEndpoint_End,types.TextUnit_Character,self.CARET_UNITS)
        if (not isinstance(left_units,int) or isinstance(left_units,bool) or not -self.CARET_UNITS<=left_units<=0 or
            not isinstance(right_units,int) or isinstance(right_units,bool) or not 0<=right_units<=self.CARET_UNITS or
            left.CompareEndpoints(types.TextPatternRangeEndpoint_End,selected,types.TextPatternRangeEndpoint_End)!=0 or
            right.CompareEndpoints(types.TextPatternRangeEndpoint_Start,selected,types.TextPatternRangeEndpoint_Start)!=0):
            raise ValueError('The caret surroundings cannot be verified.')
        # Character units can map to CRLF pairs. Limit each bounded range read
        # independently; surrounding text is used only for a local hash.
        left_text=self._text(left,self.CARET_UNITS*2)
        right_text=self._text(right,self.CARET_UNITS*2)
        return self._digest(state,left_units,right_units,left_text,right_text),''
    def create(self,expected,pattern,types):
        self._expire()
        try:
            selected=self._single(pattern)
            if selected is None:return TextContext()
            cloned=selected.Clone()
            if not cloned:return TextContext()
            state=self._state(cloned,types)
            fingerprint,text=self._fingerprint(cloned,state,types)
            current=self._single(pattern)
            if current is None or not _SelectionBookmarks._same(current,cloned,types) or self._state(current,types)!=state:
                return TextContext()
            if self._fingerprint(current,state,types)[0]!=fingerprint:return TextContext()
            token=uuid.uuid4().hex
            self.entries[token]=_ContextBookmark(expected,cloned,state,fingerprint,time.monotonic())
            while len(self.entries)>self.limit:self.entries.popitem(last=False)
            return TextContext(state,text,token)
        except Exception:return TextContext()
    def matches(self,expected,context,pattern,types):
        self._expire()
        if not _known_context(context):return False
        entry=self.entries.get(context.bookmark)
        if not entry or entry.target!=expected or entry.state!=context.state:return False
        if context.state=='selection' and self._digest(context.state,context.text)!=entry.fingerprint:return False
        try:
            current=self._single(pattern)
            return bool(current is not None and self._state(current,types)==entry.state and
                        _SelectionBookmarks._same(current,entry.selected,types) and
                        self._fingerprint(current,entry.state,types)[0]==entry.fingerprint)
        except Exception:return False

def _known_context(context):
    return bool(isinstance(context,TextContext) and isinstance(context.bookmark,str) and context.bookmark and
                isinstance(context.text,str) and '\0' not in context.text and
                ((context.state=='selection' and 0<len(context.text)<=MAX_CONTEXT_CHARS) or
                 (context.state=='caret' and context.text=='')))

class _FocusReader:
    """Read UIA only in an MTA thread, with bounded waits and no stale cache.

    Provider calls can hang. A bounded queue refuses new requests and callers
    then get an unknown identity. Context reads are bounded and exclude password
    fields. Only focused selected text can leave this worker; caret surroundings
    and bounded document reads for paste receipts are hashed locally and never returned.
    """
    def __init__(self):
        self.requests=queue.Queue(maxsize=1)
        self.initialization_error=''
        self.thread=threading.Thread(target=self._run,name='MurMur-UIA',daemon=True)
        self.thread.start()
    def read(self,native,timeout=.08):
        return self.request('focus',native,timeout=timeout)
    def request(self,operation,native,payload=None,timeout=.08):
        done=threading.Event();result=[]
        try:self.requests.put_nowait((operation,native,payload,done,result,time.monotonic()+timeout))
        except queue.Full:return None
        return result[0] if done.wait(timeout) and result else None
    def _run(self):
        types=None
        try:
            # comtypes initializes COM on its first import. Request MTA for
            # that import too; importing first with its default STA then asking
            # for MTA would fail with RPC_E_CHANGED_MODE.
            previous_flags=getattr(sys,'coinit_flags',None)
            sys.coinit_flags=0
            try:import comtypes
            finally:
                if previous_flags is None:del sys.coinit_flags
                else:sys.coinit_flags=previous_flags
            import comtypes.client
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            comtypes.client.gen_dir=None
            types=comtypes.client.GetModule('UIAutomationCore.dll')
            automation=comtypes.client.CreateObject(types.CUIAutomation,interface=types.IUIAutomation)
        except Exception as exc:
            automation=None
            self.initialization_error=type(exc).__name__+': '+str(exc)
        bookmarks=_SelectionBookmarks();contexts=_ContextBookmarks();receipts=PasteReceipts()
        while True:
            # A separate frame releases returned text before waiting on the
            # next request. Only COM ranges and hashes live in the caches.
            self._serve(self.requests.get(),automation,types,bookmarks,contexts,receipts)
    @staticmethod
    def _serve(request,automation,types,bookmarks,contexts,receipts=None):
        operation,native,payload,done,result,deadline=request
        bookmarks._expire();contexts._expire()
        if receipts is not None:receipts._expire()
        try:
            if time.monotonic()>=deadline:return
            answer=_FocusReader._answer(automation,types,operation,native,payload,bookmarks,contexts,receipts)
            if answer is not None and time.monotonic()<deadline:result.append(answer)
        except Exception:pass
        finally:done.set()
    @staticmethod
    def _answer(automation,types,operation,native,payload,bookmarks,contexts,receipts=None):
        if operation=='forget_paste' and receipts is not None:
            receipts.forget(native,payload);return True
        if automation is None or not _native_equal(native,_native_target()):return None
        element=automation.GetFocusedElement()
        runtime_id=tuple(element.GetRuntimeId());pid=int(element.CurrentProcessId)
        focused=bool(element.CurrentHasKeyboardFocus);enabled=bool(element.CurrentIsEnabled)
        password=bool(element.CurrentIsPassword);editable=False
        # A control type alone does not establish writable text. Password
        # providers are never queried for text patterns or text values.
        if not password:
            try:
                value=element.GetCurrentPattern(types.UIA_ValuePatternId).QueryInterface(types.IUIAutomationValuePattern)
                editable=not bool(value.CurrentIsReadOnly)
            except Exception:
                try:
                    text=element.GetCurrentPattern(types.UIA_TextPatternId).QueryInterface(types.IUIAutomationTextPattern)
                    read_only=text.DocumentRange.GetAttributeValue(types.UIA_IsReadOnlyAttributeId)
                    editable=isinstance(read_only,(bool,int)) and not bool(read_only)
                except Exception:pass
        if not runtime_id or not pid or not focused or not _native_equal(native,_native_target()):return None
        identity=(runtime_id,pid,editable and enabled and not password)
        if operation=='focus':return identity
        if Target(native.hwnd,native.focus,native.pid,*identity)!=native or password:return None
        if operation not in ('context','context_matches') and not native.editable:return None
        try:pattern=element.GetCurrentPattern(types.UIA_TextPatternId).QueryInterface(types.IUIAutomationTextPattern)
        except Exception:
            if operation not in ('prepare_paste','paste_ready','paste_verified') or receipts is None:return None
            state=_native_edit_state(native)
            if state is None:return None
            value_pattern=element.GetCurrentPattern(types.UIA_ValuePatternId).QueryInterface(types.IUIAutomationValuePattern)
            if bool(value_pattern.CurrentIsReadOnly):return None
            value=value_pattern.CurrentValue
            if value is None and state[1]==0:value=''
            if (not isinstance(value,str) or len(value)>MAX_DOCUMENT_CHARS or '\0' in value
                    or len(value.encode('utf-16-le','surrogatepass'))//2!=state[1]):return None
            if operation=='prepare_paste':answer=receipts.create_value(native,payload,value,state[0])
            elif operation=='paste_ready':answer=receipts.ready_value(native,payload,value,state[0])
            else:answer=receipts.verified_value(native,payload,value)
            return answer if _native_equal(native,_native_target()) else None
        if operation=='context':answer=contexts.create(native,pattern,types)
        elif operation=='context_matches':answer=contexts.matches(native,payload,pattern,types)
        elif operation=='bookmark':answer=bookmarks.create(native,pattern,types)
        elif operation=='matches':answer=bookmarks.matches(native,payload,pattern,types)
        elif operation=='prepare_paste' and receipts is not None:answer=receipts.create(native,payload,pattern,types)
        elif operation=='paste_ready' and receipts is not None:answer=receipts.ready(native,payload,pattern,types)
        elif operation=='paste_verified' and receipts is not None:answer=receipts.verified(native,payload,pattern,types)
        else:return None
        return answer if _native_equal(native,_native_target()) else None

_reader=None
_reader_lock=threading.Lock()
def prepare_text_context():
    """Start the COM worker during app startup, without reading any target/text."""
    global _reader
    with _reader_lock:
        if _reader is None:_reader=_FocusReader()

def _focus_identity(native):
    if not native.hwnd or not native.focus:return None
    prepare_text_context()
    return _reader.read(native)

def target():
    native=_native_target();identity=_focus_identity(native)
    return Target(native.hwnd,native.focus,native.pid,*identity) if identity and _native_equal(native,_native_target()) else native

def window_valid(expected):
    """Native identity only: suitable for copying, never safe insertion proof."""
    import win32gui
    return bool(expected and expected.hwnd and expected.focus and win32gui.IsWindow(expected.hwnd) and _native_equal(_native_target(),expected))

def valid(expected):
    """A known writable UIA element and unchanged native focus are required."""
    return bool(expected and expected.uia_id and expected.editable and window_valid(expected) and target()==expected)

def selection_bookmark(expected):
    """Remember one nonempty UIA selection, or refuse unverifiable replacement.

    Microsoft GetSelection/Clone/CompareEndpoints are evaluated on the same
    MTA thread. No selected/full document text or COM object crosses threads.
    """
    if not expected or not expected.uia_id or not expected.editable or not window_valid(expected):return None
    if _reader is None:_focus_identity(expected)
    token=_reader.request('bookmark',expected) if _reader is not None else None
    return token if isinstance(token,str) and window_valid(expected) else None

def selection_matches(expected,bookmark):
    """Check both original endpoints; equal text elsewhere is insufficient."""
    if not isinstance(bookmark,str) or not bookmark or not expected or not expected.uia_id or not expected.editable or not window_valid(expected):return False
    if _reader is None:return False
    return bool(_reader.request('matches',expected,bookmark) and window_valid(expected))

def text_context(expected):
    """Read one focused non-password selection/caret without keyboard injection.

    Read-only selections are useful context but never establish permission to
    write. Unknown identities, provider errors and timeouts expose no text.
    """
    try:
        if not expected or not expected.uia_id or not window_valid(expected):return TextContext()
        if _reader is None:_focus_identity(expected)
        answer=_reader.request('context',expected) if _reader is not None else None
        return answer if _known_context(answer) and window_valid(expected) else TextContext()
    except Exception:return TextContext()

def context_matches(expected,context):
    """Recheck range and content; callers additionally require valid() to write."""
    try:
        if not _known_context(context) or not expected or not expected.uia_id or not window_valid(expected):return False
        if _reader is None:return False
        return bool(_reader.request('context_matches',expected,context) and window_valid(expected))
    except Exception:return False


def prepare_paste(expected,text):
    if not valid(expected) or _reader is None:return None
    token=_reader.request('prepare_paste',expected,text,timeout=.2)
    return token if isinstance(token,str) and valid(expected) else None


def paste_ready(expected,token):
    return bool(isinstance(token,str) and valid(expected) and _reader is not None
                and _reader.request('paste_ready',expected,token,timeout=.2) and valid(expected))


def paste_verified(expected,token):
    return bool(isinstance(token,str) and valid(expected) and _reader is not None
                and _reader.request('paste_verified',expected,token,timeout=.2) and valid(expected))


def forget_paste(expected,token):
    if isinstance(token,str) and _reader is not None:_reader.request('forget_paste',expected,token)

def activate(expected):
    import win32gui
    if not expected or not win32gui.IsWindow(expected.hwnd): return False
    try: win32gui.SetForegroundWindow(expected.hwnd)
    except Exception: return False
    return valid(expected)

def own_target(t):
    import os
    return not t or t.pid==os.getpid() or not t.focus

def chord(letter):
    import win32api, win32con
    # Do not inject while physical modifiers remain pressed.
    if any(win32api.GetAsyncKeyState(k)&0x8000 for k in (win32con.VK_MENU,win32con.VK_SHIFT,win32con.VK_CONTROL,win32con.VK_LWIN,win32con.VK_RWIN)):
        raise RuntimeError('Release modifier keys and try again. Your result is preserved.')
    win32api.keybd_event(win32con.VK_CONTROL,0,0,0)
    try:
        win32api.keybd_event(ord(letter),0,0,0)
        win32api.keybd_event(ord(letter),0,win32con.KEYEVENTF_KEYUP,0)
    finally:win32api.keybd_event(win32con.VK_CONTROL,0,win32con.KEYEVENTF_KEYUP,0)

def clipboard_owner_pid():
    import win32clipboard,win32process
    try:
        owner=win32clipboard.GetClipboardOwner()
        return win32process.GetWindowThreadProcessId(owner)[1] if owner else 0
    except Exception:return 0

_clipboard_window=None
_clipboard_native=None

def _clipboard_owner():
    """Keep one hidden Qt HWND alive; it never shows or takes input focus."""
    global _clipboard_window
    from PySide6.QtCore import QThread,Qt
    from PySide6.QtGui import QWindow
    app=QApplication.instance()
    if app is None or QThread.currentThread()!=app.thread():raise RuntimeError('Clipboard operations require the application UI thread.')
    if _clipboard_window is None:
        _clipboard_window=QWindow();_clipboard_window.setFlags(Qt.Tool|Qt.FramelessWindowHint|Qt.WindowDoesNotAcceptFocus)
        _clipboard_window.create()
    return int(_clipboard_window.winId())

def _clipboard_backend():
    global _clipboard_native
    if _clipboard_native is None:
        from .clipboard import NativeClipboard
        _clipboard_native=NativeClipboard()
    return _clipboard_native

class ClipboardTransaction:
    """One-shot clipboard CAS: a revision and owner bind each exact snapshot.

    All sequence checks, data reads and mutations happen inside OpenClipboard.
    Changed revisions terminate the transaction. ClipboardBusy leaves it pending,
    so the controller can make bounded attempts, always checking under the lock.
    """
    def __init__(self):
        self.owner=_clipboard_owner();self.native=_clipboard_backend()
        self.sequence=None;self.captured_sequence=None;self.captured_owner=None
        self.restored=False;self.finished=False;self.thread_id=threading.get_ident()
        with self.native.opened(self.owner):
            formats=self.native.formats()
            if any(format not in self.native.TEXT_FORMATS for format in formats):
                raise RuntimeError('Your clipboard contains rich content. Copy the result manually to preserve it.')
            self.saved=[(format,self.native.data(format)) for format in formats]
            if sum(len(data) for _,data in self.saved)>self.native.MAX_BYTES:
                raise RuntimeError('Clipboard text is too large to preserve safely. Copy the result manually.')
            # GetClipboardData may finish delayed rendering. Bind the snapshot
            # to the revision after rendering, while the clipboard stays locked.
            self.initial_sequence=self.native.sequence();self.initial_owner=self.native.owner()

    def write(self,text):
        if self.finished or self.sequence is not None or threading.get_ident()!=self.thread_id:
            raise RuntimeError('This clipboard transaction cannot write again. Your result is preserved.')
        if not isinstance(text,str) or '\0' in text:raise RuntimeError('The result cannot be copied safely. Your original text is preserved.')
        prepared=[];rollback=[]
        try:
            prepared=self.native.prepare([(self.native.UNICODE,text.encode('utf-16-le')+b'\0\0')])
            rollback=self.native.prepare(self.saved)
            with self.native.opened(self.owner):
                if self.native.sequence()!=self.initial_sequence or self.native.owner()!=self.initial_owner:
                    raise RuntimeError('The clipboard changed before insertion. Your result is preserved; copy it manually.')
                try:
                    self.native.replace(prepared);self.sequence=self.native.sequence()
                except Exception:
                    # No other writer can intervene during this rollback.
                    self.native.replace(rollback)
                    raise RuntimeError('Clipboard insertion failed. Your result is preserved.') from None
        except Exception:
            self.finished=True;raise
        finally:self.native.release(prepared);self.native.release(rollback)

    def copied(self,expected):
        """Return a target-owned copied revision and text from one locked read."""
        if self.finished or self.sequence is None or threading.get_ident()!=self.thread_id or not expected:return None
        from .clipboard import decode_unicode
        try:
            with self.native.opened(self.owner):
                if self.native.sequence()==self.sequence:return None
                owner=self.native.owner()
                pids={pid for pid in (expected.pid,expected.uia_pid) if pid}
                if self.native.owner_pid(owner) not in pids or self.native.UNICODE not in self.native.formats():return None
                text=decode_unicode(self.native.data(self.native.UNICODE))
                sequence=self.native.sequence()
                if not text or not text.strip() or sequence==self.sequence or self.native.owner()!=owner:return None
                self.captured_sequence=sequence;self.captured_owner=owner
                return sequence,text
        except ClipboardBusy:raise
        except Exception:return None

    def restore(self,expected=None):
        if self.finished or threading.get_ident()!=self.thread_id:return False
        revision=self.sequence if expected is None else expected
        expected_owner=self.owner if expected is None or expected==self.sequence else self.captured_owner
        if revision is None or (expected is not None and expected not in (self.sequence,self.captured_sequence)):
            self.finished=True;return False
        prepared=[]
        try:
            prepared=self.native.prepare(self.saved)
            with self.native.opened(self.owner):
                self.finished=True
                if self.native.sequence()!=revision or self.native.owner()!=expected_owner:return False
                self.native.replace(prepared);self.restored=True;return True
        except ClipboardBusy:raise
        except Exception:
            self.finished=True
            raise RuntimeError('The original clipboard could not be restored. Your result is preserved in Preview.') from None
        finally:self.native.release(prepared)

    def owned_by(self,expected):
        """Diagnostic only; copied() is the authority for a captured revision."""
        return bool(expected and clipboard_owner_pid() in {pid for pid in (expected.pid,expected.uia_pid) if pid})

def startup(enabled):
    import winreg
    from pathlib import Path
    command=f'"{sys.executable}"'
    if not getattr(sys,'frozen',False): command+=f' "{Path(__file__).resolve().parents[1]/"run.py"}"'
    command+=' --tray'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
        if enabled: winreg.SetValueEx(key,'MurMur',0,winreg.REG_SZ,command)
        else:
            try: winreg.DeleteValue(key,'MurMur')
            except FileNotFoundError: pass

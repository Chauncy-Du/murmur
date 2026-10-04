"""Native Win32 clipboard primitives; no Qt MIME conversion or delayed writes.

Transactions in windows.py hold OpenClipboard across each snapshot or
compare-and-replace. This module preserves the exact HGLOBAL bytes of supported
plain text formats, including CF_LOCALE and original ANSI/OEM encodings.
"""
import ctypes
from ctypes import wintypes
from contextlib import contextmanager

class ClipboardBusy(RuntimeError):
    """OpenClipboard failed; no clipboard data or transaction state changed."""


class NativeClipboard:
    MAX_BYTES=8*1024*1024
    TEXT_FORMATS=frozenset((1,7,13,16))  # CF_TEXT/OEMTEXT/UNICODETEXT/LOCALE
    UNICODE=13

    def __init__(self):
        import win32clipboard
        self.api=win32clipboard
        self.user=ctypes.WinDLL('user32',use_last_error=True)
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.user.GetClipboardData.argtypes=[wintypes.UINT];self.user.GetClipboardData.restype=wintypes.HANDLE
        self.user.SetClipboardData.argtypes=[wintypes.UINT,wintypes.HANDLE];self.user.SetClipboardData.restype=wintypes.HANDLE
        self.user.GetClipboardOwner.argtypes=[];self.user.GetClipboardOwner.restype=wintypes.HWND
        self.kernel.GlobalSize.argtypes=[wintypes.HGLOBAL];self.kernel.GlobalSize.restype=ctypes.c_size_t
        self.kernel.GlobalLock.argtypes=[wintypes.HGLOBAL];self.kernel.GlobalLock.restype=ctypes.c_void_p
        self.kernel.GlobalUnlock.argtypes=[wintypes.HGLOBAL];self.kernel.GlobalUnlock.restype=wintypes.BOOL
        self.kernel.GlobalAlloc.argtypes=[wintypes.UINT,ctypes.c_size_t];self.kernel.GlobalAlloc.restype=wintypes.HGLOBAL
        self.kernel.GlobalFree.argtypes=[wintypes.HGLOBAL];self.kernel.GlobalFree.restype=wintypes.HGLOBAL

    @contextmanager
    def opened(self,owner):
        try:self.api.OpenClipboard(owner)
        except Exception:raise ClipboardBusy('The clipboard is busy. Your result is preserved; copy it manually.') from None
        try:yield self
        finally:self.api.CloseClipboard()

    def sequence(self):
        value=self.api.GetClipboardSequenceNumber()
        if not value:raise RuntimeError('The clipboard revision could not be verified. Your result is preserved.')
        return value

    def owner(self):
        # A null HWND is legal when clipboard data has no live owner. pywin32
        # raises error(0, ...) for that result, so use the documented native
        # API directly and distinguish a real last-error from an unowned value.
        ctypes.set_last_error(0)
        owner=self.user.GetClipboardOwner()
        error=ctypes.get_last_error()
        if not owner and error:
            raise RuntimeError('The clipboard owner could not be verified. Your result is preserved.')
        return int(owner or 0)

    def owner_pid(self,owner):
        import win32process
        try:return win32process.GetWindowThreadProcessId(owner)[1] if owner else 0
        except Exception:return 0

    def formats(self):
        formats=[];value=0
        while True:
            value=self.api.EnumClipboardFormats(value)
            if not value:return formats
            formats.append(value)

    def data(self,format):
        handle=self.user.GetClipboardData(format)
        if not handle:raise RuntimeError('Clipboard text could not be read safely. Your result is preserved.')
        size=self.kernel.GlobalSize(handle)
        if not size or size>self.MAX_BYTES:raise RuntimeError('Clipboard text is too large or cannot be preserved safely. Copy the result manually.')
        pointer=self.kernel.GlobalLock(handle)
        if not pointer:raise RuntimeError('Clipboard text could not be preserved safely. Copy the result manually.')
        try:return ctypes.string_at(pointer,size)
        finally:self.kernel.GlobalUnlock(handle)

    def prepare(self,values):
        """Allocate all buffers before EmptyClipboard; caller retains failures."""
        prepared=[]
        try:
            for format,data in values:
                if not data or len(data)>self.MAX_BYTES:raise RuntimeError('Clipboard text cannot be preserved safely. Copy the result manually.')
                handle=self.kernel.GlobalAlloc(0x0042,len(data))  # MOVEABLE | ZEROINIT
                if not handle:raise RuntimeError('Could not allocate clipboard memory. Your result is preserved.')
                prepared.append([format,handle])
                pointer=self.kernel.GlobalLock(handle)
                if not pointer:raise RuntimeError('Could not prepare clipboard memory. Your result is preserved.')
                try:ctypes.memmove(pointer,data,len(data))
                finally:self.kernel.GlobalUnlock(handle)
            return prepared
        except Exception:self.release(prepared);raise

    def replace(self,prepared):
        self.api.EmptyClipboard()
        for entry in prepared:
            format,handle=entry
            if not self.user.SetClipboardData(format,handle):raise RuntimeError('Could not write clipboard data. Your result is preserved.')
            entry[1]=0  # Ownership transfers to Windows only after success.

    def release(self,prepared):
        for entry in prepared:
            if entry[1]:self.kernel.GlobalFree(entry[1]);entry[1]=0


def decode_unicode(data):
    # Search for an aligned UTF-16 terminator. Do not decode untrusted padding.
    for offset in range(0,len(data)-1,2):
        if data[offset:offset+2]==b'\0\0':
            try:return data[:offset].decode('utf-16-le')
            except UnicodeDecodeError:return None
    return None

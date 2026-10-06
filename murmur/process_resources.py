"""Windows process-tree counters and cached WDDM dedicated-memory query."""
import ctypes
import os
import re
from ctypes import wintypes as w


class _Entry(ctypes.Structure):
    _fields_=[('size',w.DWORD),('usage',w.DWORD),('pid',w.DWORD),('heap',ctypes.c_size_t),
              ('module',w.DWORD),('threads',w.DWORD),('parent',w.DWORD),('priority',w.LONG),
              ('flags',w.DWORD),('exe',w.WCHAR*260)]


def descendants(parents,root):
    selected={root}
    while True:
        extra={pid for pid,parent in parents.items() if parent in selected}-selected
        if not extra:return selected
        selected.update(extra)


def process_ids(kernel):
    handle=kernel.CreateToolhelp32Snapshot(2,0)
    if handle==ctypes.c_void_p(-1).value:return {os.getpid()}
    parents={};entry=_Entry();entry.size=ctypes.sizeof(entry)
    try:
        ok=kernel.Process32FirstW(handle,ctypes.byref(entry))
        while ok:
            parents[entry.pid]=entry.parent
            ok=kernel.Process32NextW(handle,ctypes.byref(entry))
    finally:kernel.CloseHandle(handle)
    return descendants(parents,os.getpid())


class _ValueUnion(ctypes.Union):
    _fields_=[('value',ctypes.c_double),('large',ctypes.c_longlong)]


class _Value(ctypes.Structure):
    _anonymous_=('data',)
    _fields_=[('status',w.DWORD),('data',_ValueUnion)]


class _Item(ctypes.Structure):
    _fields_=[('name',w.LPWSTR),('counter',_Value)]


def dedicated_bytes(items,pids):
    used=0
    for item in items:
        match=re.match(r'pid_(\d+)_',item.name or '')
        if match and int(match[1]) in pids:
            if item.counter.status not in (0,1):return None
            used+=max(0,item.counter.value)
    return used


class ProcessGpuMemory:
    def __init__(self):self.api=None;self.query=ctypes.c_void_p();self.counter=ctypes.c_void_p();self.initialized=False

    def initialize(self):
        self.initialized=True
        try:
            api=ctypes.WinDLL('pdh');status=ctypes.c_ulong
            api.PdhOpenQueryW.argtypes=[w.LPCWSTR,ctypes.c_size_t,ctypes.POINTER(ctypes.c_void_p)]
            api.PdhAddEnglishCounterW.argtypes=[ctypes.c_void_p,w.LPCWSTR,ctypes.c_size_t,ctypes.POINTER(ctypes.c_void_p)]
            api.PdhCollectQueryData.argtypes=[ctypes.c_void_p]
            api.PdhGetFormattedCounterArrayW.argtypes=[ctypes.c_void_p,w.DWORD,ctypes.POINTER(w.DWORD),ctypes.POINTER(w.DWORD),ctypes.c_void_p]
            api.PdhCloseQuery.argtypes=[ctypes.c_void_p]
            for name in ('PdhOpenQueryW','PdhAddEnglishCounterW','PdhCollectQueryData','PdhGetFormattedCounterArrayW','PdhCloseQuery'):getattr(api,name).restype=status
            if api.PdhOpenQueryW(None,0,ctypes.byref(self.query))!=0:return
            if api.PdhAddEnglishCounterW(self.query,r'\GPU Process Memory(*)\Dedicated Usage',0,ctypes.byref(self.counter))!=0:
                api.PdhCloseQuery(self.query);self.query=ctypes.c_void_p();return
            self.api=api
        except (OSError,AttributeError):pass

    def sample(self,pids):
        if not self.initialized:self.initialize()
        if not self.api:return None
        if self.api.PdhCollectQueryData(self.query)!=0:return None
        for _ in range(2):
            size=w.DWORD();count=w.DWORD()
            status=self.api.PdhGetFormattedCounterArrayW(self.counter,0x200,ctypes.byref(size),ctypes.byref(count),None)
            if status!=0x800007D2 or not 0<size.value<=8*1024*1024:return None
            buffer=ctypes.create_string_buffer(size.value)
            status=self.api.PdhGetFormattedCounterArrayW(self.counter,0x200,ctypes.byref(size),ctypes.byref(count),buffer)
            if status==0x800007D2:continue
            if status!=0 or count.value*ctypes.sizeof(_Item)>len(buffer):return None
            items=ctypes.cast(buffer,ctypes.POINTER(_Item))
            return dedicated_bytes((items[i] for i in range(count.value)),pids)
        return None

    def close(self):
        if self.api:self.api.PdhCloseQuery(self.query);self.api=None

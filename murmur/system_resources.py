"""Low-frequency Windows counters, without subprocesses or extra dependencies."""
import ctypes
import sys
import time
from ctypes import wintypes


def cpu_percent(previous,current):
    if previous is None:return None
    idle,kernel,user=(b-a for a,b in zip(previous,current))
    total=kernel+user
    if min(idle,kernel,user)<0 or total<=0:return None
    return max(0.,min(100.,100.*(total-idle)/total))


class _MemoryStatus(ctypes.Structure):
    _fields_=[('length',wintypes.DWORD),('load',wintypes.DWORD)]+[(name,ctypes.c_ulonglong) for name in
        ('total_physical','available_physical','total_page','available_page','total_virtual','available_virtual','extended')]


class _ProcessMemory(ctypes.Structure):
    _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in
        ('peak_working','working','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile')]


class ResourceSampler:
    def __init__(self):
        self.previous=None;self.kernel=None
        from .gpu_memory import GpuMemory
        self.gpu=GpuMemory()
        from .process_resources import ProcessGpuMemory
        self.process_gpu=ProcessGpuMemory();self.process_previous={};self.sample_time=None
        if sys.platform=='win32':
            self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            self.psapi=ctypes.WinDLL('psapi',use_last_error=True)
            self.kernel.GetSystemTimes.argtypes=[ctypes.POINTER(wintypes.FILETIME)]*3
            self.kernel.GetSystemTimes.restype=wintypes.BOOL
            self.kernel.GlobalMemoryStatusEx.argtypes=[ctypes.POINTER(_MemoryStatus)]
            self.kernel.GlobalMemoryStatusEx.restype=wintypes.BOOL
            self.kernel.GetCurrentProcess.restype=wintypes.HANDLE
            self.kernel.CreateToolhelp32Snapshot.argtypes=[wintypes.DWORD,wintypes.DWORD];self.kernel.CreateToolhelp32Snapshot.restype=wintypes.HANDLE
            from .process_resources import _Entry
            for name in ('Process32FirstW','Process32NextW'):
                getattr(self.kernel,name).argtypes=[wintypes.HANDLE,ctypes.POINTER(_Entry)];getattr(self.kernel,name).restype=wintypes.BOOL
            self.kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];self.kernel.OpenProcess.restype=wintypes.HANDLE
            self.kernel.CloseHandle.argtypes=[wintypes.HANDLE]
            self.kernel.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
            self.kernel.GetProcessTimes.restype=wintypes.BOOL
            self.psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(_ProcessMemory),wintypes.DWORD]
            self.psapi.GetProcessMemoryInfo.restype=wintypes.BOOL

    def sample(self):
        result={'cpu_percent':None,'memory_percent':None,'memory_used_gb':None,'memory_total_gb':None,'process_mb':None,
                'gpu_percent':None,'gpu_used_gb':None,'gpu_total_gb':None}
        if self.kernel is None:return result
        from .process_resources import process_ids
        import os
        pids=process_ids(self.kernel);now=time.monotonic();ticks={};working=delta=0;valid=False
        for pid in pids:
            handle=self.kernel.OpenProcess(0x410,False,pid)
            if not handle:continue
            try:
                times=[wintypes.FILETIME() for _ in range(4)]
                if self.kernel.GetProcessTimes(handle,*(ctypes.byref(x) for x in times)):
                    ticks[pid]=sum((x.dwHighDateTime<<32)|x.dwLowDateTime for x in times[2:])
                    if pid in self.process_previous:delta+=max(0,ticks[pid]-self.process_previous[pid])
                process=_ProcessMemory();process.cb=ctypes.sizeof(process)
                if self.psapi.GetProcessMemoryInfo(handle,ctypes.byref(process),process.cb):working+=process.working;valid=True
            finally:self.kernel.CloseHandle(handle)
        if self.sample_time is not None and now>self.sample_time:
            result['cpu_percent']=min(100.,100*delta/1e7/(now-self.sample_time)/(os.cpu_count() or 1))
        self.process_previous=ticks;self.sample_time=now
        memory=_MemoryStatus();memory.length=ctypes.sizeof(memory)
        if self.kernel.GlobalMemoryStatusEx(ctypes.byref(memory)):
            if valid and memory.total_physical:
                result.update(memory_percent=100*working/memory.total_physical,memory_used_gb=working/2**30,
                              memory_total_gb=memory.total_physical/2**30,process_mb=working/2**20)
        gpu=self.gpu.sample()
        gpu_used=self.process_gpu.sample(pids)
        if gpu and gpu_used is not None:
            total=gpu['gpu_total_gb'];result.update(gpu_used_gb=gpu_used/2**30,gpu_total_gb=total,gpu_percent=min(100.,100*gpu_used/2**30/total))
        return result

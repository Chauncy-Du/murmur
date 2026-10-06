"""Read NVIDIA device VRAM through cached NVML handles, without nvidia-smi."""
import ctypes
import os
import sys
from pathlib import Path


class _Memory(ctypes.Structure):
    _fields_=[('total',ctypes.c_ulonglong),('free',ctypes.c_ulonglong),('used',ctypes.c_ulonglong)]


class GpuMemory:
    def __init__(self):self.initialized=False;self.api=None;self.handles=[]

    def initialize(self):
        self.initialized=True
        if sys.platform!='win32':return
        paths=[Path(os.environ.get('SystemRoot','C:/Windows'))/'System32/nvml.dll',
               Path(os.environ.get('ProgramW6432','C:/Program Files'))/'NVIDIA Corporation/NVSMI/nvml.dll']
        for path in paths:
            if not path.is_file():continue
            try:
                api=ctypes.CDLL(str(path))
                api.nvmlInit_v2.argtypes=[];api.nvmlInit_v2.restype=ctypes.c_int
                api.nvmlDeviceGetCount_v2.argtypes=[ctypes.POINTER(ctypes.c_uint)];api.nvmlDeviceGetCount_v2.restype=ctypes.c_int
                api.nvmlDeviceGetHandleByIndex_v2.argtypes=[ctypes.c_uint,ctypes.POINTER(ctypes.c_void_p)];api.nvmlDeviceGetHandleByIndex_v2.restype=ctypes.c_int
                api.nvmlDeviceGetMemoryInfo.argtypes=[ctypes.c_void_p,ctypes.POINTER(_Memory)];api.nvmlDeviceGetMemoryInfo.restype=ctypes.c_int
                if api.nvmlInit_v2()!=0:continue
                self.api=api;count=ctypes.c_uint()
                if api.nvmlDeviceGetCount_v2(ctypes.byref(count))!=0:return
                for i in range(min(count.value,16)):
                    handle=ctypes.c_void_p()
                    if api.nvmlDeviceGetHandleByIndex_v2(i,ctypes.byref(handle))==0:self.handles.append(handle)
                return
            except (OSError,AttributeError):continue

    def sample(self):
        if not self.initialized:self.initialize()
        used=total=0
        if self.api:
            for handle in self.handles:
                memory=_Memory()
                if self.api.nvmlDeviceGetMemoryInfo(handle,ctypes.byref(memory))!=0:return None
                if not 0<=memory.used<=memory.total or not memory.total:return None
                used+=memory.used;total+=memory.total
        return {'gpu_percent':used/total*100,'gpu_used_gb':used/2**30,'gpu_total_gb':total/2**30} if total else None

    def close(self):
        if self.api:
            self.api.nvmlShutdown();self.api=None;self.handles=[]

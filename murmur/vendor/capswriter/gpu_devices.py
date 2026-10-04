"""Read-only DXGI adapter inventory matching DirectML device indices."""
import ctypes
import os
from pathlib import Path
import sys
import uuid


def dxgi_adapters():
    """Enumerate DXGI adapters without creating a GPU inference session.

    ONNX Runtime DirectML device_id is the DXGI enumeration index. Laptops
    commonly put integrated graphics at index zero; report the actual device
    name before describing a DirectML result as a particular GPU benchmark.
    """
    if sys.platform != 'win32':
        return []

    class GUID(ctypes.Structure):
        _fields_ = [('Data1', ctypes.c_uint32), ('Data2', ctypes.c_uint16),
                    ('Data3', ctypes.c_uint16), ('Data4', ctypes.c_uint8 * 8)]

    class LUID(ctypes.Structure):
        _fields_ = [('LowPart', ctypes.c_uint32), ('HighPart', ctypes.c_int32)]

    class Description(ctypes.Structure):
        _fields_ = [('Description', ctypes.c_wchar * 128),
                    ('VendorId', ctypes.c_uint32), ('DeviceId', ctypes.c_uint32),
                    ('SubSysId', ctypes.c_uint32), ('Revision', ctypes.c_uint32),
                    ('DedicatedVideoMemory', ctypes.c_size_t),
                    ('DedicatedSystemMemory', ctypes.c_size_t),
                    ('SharedSystemMemory', ctypes.c_size_t),
                    ('AdapterLuid', LUID), ('Flags', ctypes.c_uint32)]

    def method(pointer, index, result, *args):
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(result, ctypes.c_void_p, *args)(table[index])

    library = ctypes.WinDLL(str(Path(os.environ['SystemRoot'])/'System32'/'dxgi.dll'))
    create = library.CreateDXGIFactory1
    create.argtypes = [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
    create.restype = ctypes.c_long
    iid = GUID.from_buffer_copy(uuid.UUID('770aae78-f26f-4dba-a829-253c83d1b387').bytes_le)
    factory = ctypes.c_void_p()
    status = create(ctypes.byref(iid), ctypes.byref(factory))
    if status < 0 or not factory:
        raise RuntimeError(f'DXGI adapter enumeration failed: 0x{status & 0xffffffff:08x}')
    adapters = []
    try:
        enumerate_adapter = method(factory, 12, ctypes.c_long,
                                    ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p))
        for index in range(32):
            adapter = ctypes.c_void_p()
            status = enumerate_adapter(factory, index, ctypes.byref(adapter))
            if status & 0xffffffff == 0x887a0002:  # DXGI_ERROR_NOT_FOUND
                break
            if status < 0 or not adapter:
                raise RuntimeError(f'DXGI adapter {index} could not be inspected.')
            try:
                description = Description()
                describe = method(adapter, 10, ctypes.c_long, ctypes.POINTER(Description))
                status = describe(adapter, ctypes.byref(description))
                if status < 0:
                    raise RuntimeError(f'DXGI adapter {index} description is unavailable.')
                adapters.append({
                    'device_id': index, 'name': description.Description,
                    'vendor_id': description.VendorId, 'device_identifier': description.DeviceId,
                    'dedicated_video_memory': description.DedicatedVideoMemory,
                    'shared_system_memory': description.SharedSystemMemory,
                    'software': bool(description.Flags & 2),
                    'luid': f'{description.AdapterLuid.HighPart & 0xffffffff:08x}'
                            f'{description.AdapterLuid.LowPart:08x}',
                })
            finally:
                method(adapter, 2, ctypes.c_uint32)(adapter)
    finally:
        method(factory, 2, ctypes.c_uint32)(factory)
    return adapters

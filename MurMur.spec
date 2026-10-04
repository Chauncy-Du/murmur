# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, copy_metadata
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = []
binaries = []
hiddenimports = ['pynput.keyboard._win32', 'pynput.mouse._win32', 'comtypes.client', 'comtypes.gen']
datas += collect_data_files('dashscope')
datas += copy_metadata('dashscope')
tmp_sherpa = collect_all('sherpa_onnx')
datas += tmp_sherpa[0]; binaries += tmp_sherpa[1]; hiddenimports += tmp_sherpa[2]
tmp_ret = collect_all('keyring')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Split ONNX / GGUF recognizers are imported in a spawned child process.
# Preserve package-specific DLL locations; sherpa and DirectML use different
# ONNX Runtime versions and must not share one interpreter.
for package in ('onnxruntime', 'sentencepiece', 'gguf'):
    collected = collect_all(package)
    datas += collected[0]; binaries += collected[1]; hiddenimports += collected[2]
hiddenimports += collect_submodules('murmur.vendor.capswriter')
datas += collect_data_files('murmur.vendor.capswriter', includes=['LICENSE', 'NOTICE.md'])
datas += collect_data_files('murmur', includes=['assets/providers/*'])


a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest'],
    noarchive=False,
    optimize=0,
)
# Windows 10/11 provide ICU, API-set forwarders and the Universal CRT.
# Never ship similarly named DLLs discovered in an unrelated tool's PATH:
# Poppler's ICU exports versioned symbols and cannot satisfy Qt's Windows ICU API.
from pathlib import Path
def operating_system_dll(entry):
    name = Path(entry[0]).name.lower()
    return (name in {'icuuc.dll', 'icuin.dll', 'ucrtbase.dll'}
            or name.startswith(('api-ms-win-', 'ext-ms-win-', 'icudt')))
a.binaries = [entry for entry in a.binaries if not operating_system_dll(entry)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MurMur',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='MurMur',
)

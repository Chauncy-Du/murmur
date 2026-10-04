"""Smoke-test the actual portable executable with no Python/tool directories in PATH."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

bundle=Path(sys.argv[1]).resolve()
exe=bundle/'MurMur.exe'
if not exe.is_file():raise SystemExit('Portable executable is missing.')
internal=bundle/'_internal'
for dll in internal.rglob('*.dll'):
    name=dll.name.lower()
    if name in ('icuuc.dll','icuin.dll','ucrtbase.dll') or name.startswith(('api-ms-win-','ext-ms-win-','icudt')):
        raise SystemExit('An operating-system DLL was incorrectly bundled: '+str(dll))
root=Path(tempfile.mkdtemp(prefix='MurMur-portable-qa-'))
env=os.environ.copy()
system=env.get('SystemRoot',r'C:\Windows')
env['PATH']=os.pathsep.join((system+'\\System32',system))
for key in ('PYTHONPATH','PYTHONHOME','QT_PLUGIN_PATH','QT_QPA_PLATFORM_PLUGIN_PATH','QT_QPA_PLATFORM'):
    env.pop(key,None)
try:
    result=subprocess.run([str(exe),'--no-hotkeys','--data-dir',str(root/'data'),'--screenshots',str(root/'screenshots')],cwd=root,env=env,timeout=45)
except subprocess.TimeoutExpired:raise SystemExit('Portable smoke test did not exit within 45 seconds.')
if result.returncode:raise SystemExit(f'Portable smoke test failed: exit {result.returncode}.')
shots=list((root/'screenshots').glob('*.png'))
if len(shots)!=16 or any(p.stat().st_size<100 for p in shots):
    raise SystemExit(f'Portable UI capture failed: {len(shots)} screenshots.')
print('Portable startup and clean exit passed. Screenshots:',root/'screenshots')

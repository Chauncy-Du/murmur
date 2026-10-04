"""Verified llama.cpp dependency installation; recognition never downloads it."""
import hashlib
import json
import os
import tempfile
import threading
import zipfile
from pathlib import Path

import httpx
from .paths import runtime_root

VERSION='b10621'
ARCHIVE_URL='https://github.com/ggml-org/llama.cpp/releases/download/b10621/llama-b10621-bin-win-vulkan-x64.zip'
ARCHIVE_SIZE=34403304
ARCHIVE_SHA256='2672d85bf87c8280d94dee01eb6a86280046878f70a07d786a93637fa9081163'
# Fixed hashes of the DLL subset from the verified official archive.
DLL_FILES={'LICENSE-LLVM-OpenMP': (19741, 'fdad1758a9e1f9d5a81e18879b3406772115edc92c24bfa36b70c654f325e8e4'),
 'ggml-base.dll': (780800, '70187128a468674c19968968d532780217cbac2f2e0a8b1dca11d1338ed536fa'),
 'ggml-cpu-alderlake.dll': (1181696, 'c8f82a7e4cdc9ac9c25f7f81eecdf5978151cd0a6969e33f57eb73bf6dda35fa'),
 'ggml-cpu-cannonlake.dll': (1396736, '4bf93b606b713d1cacdb688ffa64acf5fc4c06699473da4b9dc63e830142eee5'),
 'ggml-cpu-cascadelake.dll': (1383424, '33c94f715b36a56498333813c03d9ec1ea0ab140515f798ce9b3a3ec9c4a562c'),
 'ggml-cpu-cooperlake.dll': (1384448, '4e8915adb96b8b2d3bf96ba5a845a4abe06eab13999a4aaa3b29876ee4be16d0'),
 'ggml-cpu-haswell.dll': (1185792, 'df2d6b06a5d367c9939cf98cc0d137fd1a566b08fa7ac96611bcc53aadf8805f'),
 'ggml-cpu-icelake.dll': (1390080, '09305aa9d12c248f9fe227030cbf1927b0b4569d54884542048cc7404fddf6d0'),
 'ggml-cpu-ivybridge.dll': (1075200, '547f2e90eb2836b94231a59ed578a735d5955a8709516447fc2ff0fd56787189'),
 'ggml-cpu-piledriver.dll': (1079296, '3d3ba8d0e921b476983bce1853d443fccd5be97dc01d0a9486b20fc79a500e94'),
 'ggml-cpu-sandybridge.dll': (1055232, '3804cf686a2e1043e5024f6bcb5a76e86caaae46a84d33dc9536873bbfe8d733'),
 'ggml-cpu-sapphirerapids.dll': (1660928, '443d330b3b1e59674432ddfe91d2edeb31bd8bd4c7e9db56a37de5e89cafba5a'),
 'ggml-cpu-skylakex.dll': (1390592, '14ac82c59ed29dbcb30b2be19a24ecdd5fa85636cf36ba39f7a9ca196cd424bf'),
 'ggml-cpu-sse42.dll': (878080, '035daa24bb5bc474a82db0209b7976766ac570d62c928a1d18cf7a16258122c8'),
 'ggml-cpu-x64.dll': (870912, 'db6c12ee536e4725aa980588c1551f039f5880ceeea731178970e76bf401a505'),
 'ggml-cpu-zen4.dll': (1391104, '08562e7fe6e06c2aff5a6f41bf22c882c34d8f8018ec23873b40ad99190160e3'),
 'ggml-vulkan.dll': (54359040, 'b2d30302c08395cdc896a78677589fdf7ae44887e59eb76f924ea5c5306491a5'),
 'ggml.dll': (86016, '58873500786645941f11fb0feacbc74f97e26fd9d6bcde7d141581a23f1ed4ec'),
 'libomp.dll': (768000, 'a12116ba72d1d6820407cf30be23da04ce79d6bb8a71a5ee71759c5a1faa6f1c'),
 'llama.dll': (3009024, '9992c500c0224838b4e049fb85f06029d1b5826ebf865f60b87895280bbebc7b')}
LICENSE_URL='https://raw.githubusercontent.com/ggml-org/llama.cpp/b10621/LICENSE'
LICENSE_SIZE=1078
LICENSE_SHA256='94f29bbed6a22c35b992c5c6ebf0e7c92f13b836b90f36f461c9cf2f0f1d010d'
_INSTALL_LOCK=threading.Lock()


def runtime_dir():
    override=os.getenv('MURMUR_LLAMA_BIN')
    if override:return Path(override).expanduser().resolve()
    return (runtime_root()/('llama-'+VERSION)).resolve()


def _cancelled(cancel):
    if cancel is not None and cancel.is_set():raise InterruptedError()


def _matches(path, size, sha):
    if not path.is_file() or path.stat().st_size!=size:return False
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()==sha


def verify_runtime(folder=None):
    folder=Path(folder) if folder is not None else runtime_dir()
    return (bool(DLL_FILES) and all(_matches(folder/name,*expected) for name,expected in DLL_FILES.items())
            and _matches(folder/'LICENSE-llama.cpp.txt',LICENSE_SIZE,LICENSE_SHA256))


def install_runtime(progress=lambda text:None,cancel=None,destination=None,archive=None):
    """Install an allowlisted DLL subset without extracting executable tools."""
    if not _INSTALL_LOCK.acquire(blocking=False):raise RuntimeError('A local runtime installation is already running.')
    try:
        _cancelled(cancel)
        folder=(Path(destination).expanduser().resolve() if destination else runtime_dir())
        if verify_runtime(folder):return folder
        folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.murmur-runtime-install-',dir=folder) as temporary_folder:
            stage=Path(temporary_folder)
            downloaded=archive is None
            source=Path(archive) if archive is not None else stage/'llama-runtime.download'
            if downloaded:
                digest=hashlib.sha256();written=0
                with httpx.Client(follow_redirects=True,timeout=httpx.Timeout(60,connect=15)) as client:
                    with client.stream('GET',ARCHIVE_URL) as response:
                        response.raise_for_status()
                        with source.open('wb') as output:
                            for chunk in response.iter_bytes(1024*1024):
                                _cancelled(cancel);written+=len(chunk)
                                if written>ARCHIVE_SIZE:raise RuntimeError('The runtime download exceeded its expected size.')
                                output.write(chunk);digest.update(chunk)
                                progress(f'Downloading local decoder runtime · {int(written*100/ARCHIVE_SIZE)}%')
                if written!=ARCHIVE_SIZE or digest.hexdigest()!=ARCHIVE_SHA256:
                    raise RuntimeError('Local decoder runtime integrity check failed.')
            elif not _matches(source,ARCHIVE_SIZE,ARCHIVE_SHA256):
                raise RuntimeError('Local decoder runtime integrity check failed.')
            with zipfile.ZipFile(source) as zipped:
                names=[item.filename for item in zipped.infolist()]
                if len(names)!=len(set(names)):raise RuntimeError('Duplicate files in the local runtime archive.')
                # Never use extractall: only known plain filenames enter this folder.
                for name,(size,sha) in DLL_FILES.items():
                    _cancelled(cancel)
                    if name not in names or Path(name).name!=name:
                        raise RuntimeError('The local runtime archive is incomplete.')
                    info=zipped.getinfo(name)
                    if info.file_size!=size:raise RuntimeError('Local decoder DLL integrity check failed.')
                    data=zipped.read(info)
                    if hashlib.sha256(data).hexdigest()!=sha:raise RuntimeError('Local decoder DLL integrity check failed.')
                    # Validate the entire archive and license before replacing
                    # any existing DLL. A later failure leaves a working runtime
                    # and custom files intact.
                    if not _matches(folder/name,size,sha):(stage/name).write_bytes(data)
            _cancelled(cancel)
            with httpx.Client(follow_redirects=True,timeout=30) as client:
                response=client.get(LICENSE_URL);response.raise_for_status();license_data=response.content
            if len(license_data)!=LICENSE_SIZE or hashlib.sha256(license_data).hexdigest()!=LICENSE_SHA256:
                raise RuntimeError('The decoder license integrity check failed.')
            (stage/'LICENSE-llama.cpp.txt').write_bytes(license_data)
            (stage/'murmur-runtime.json').write_text(json.dumps({'version':VERSION,'archive_sha256':ARCHIVE_SHA256,'files':DLL_FILES},indent=2),'utf-8')
            _cancelled(cancel)
            for name in (*DLL_FILES,'LICENSE-llama.cpp.txt','murmur-runtime.json'):
                staged=stage/name
                if staged.is_file():staged.replace(folder/name)
            progress('Local decoder runtime installed and verified')
            return folder
    finally:_INSTALL_LOCK.release()

"""Pinned local ASR model installation. Never download at recognition time."""
import hashlib
import json
import stat
import threading
import tempfile
import zipfile
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
import httpx

REVISION='2365baeacb507f821a0c8120fcee3d484dba7a07'
BASE='https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/'+REVISION+'/'
FILES={
 'model.int8.onnx':(239233841,'c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51'),
 'tokens.txt':(315894,'f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc'),
 'LICENSE':(71,'221c6df10b0931a5629adad671ea48fb7747e034c414b6d2bfa275bc3dd4ea17'),
 'MODEL_LICENSE':(5306,'7dba975a2069691db4992b0592d70828b330d2f8a30a71450f4e152a554e84f8'),
 'silero_vad.onnx':(643854,'9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6'),
 'SILERO_LICENSE':(1075,'2e63e9a38b6e8fc0c7bc37ce174caca1862870856c6daf5697cfb785e925520b')}
SOURCES={'MODEL_LICENSE':'https://raw.githubusercontent.com/modelscope/FunASR/66d7a4c264a5993a2a63ed00c1f402c296ee521a/MODEL_LICENSE',
 'silero_vad.onnx':'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx',
 'SILERO_LICENSE':'https://raw.githubusercontent.com/snakers4/silero-vad/caddb3b7ce1dee88a14d5621a0e9a8fdeb2c2c48/LICENSE'}
PARAFORMER_REVISION='def027084691107096b5ebba69785756d63de6c5'
PARAFORMER_BASE='https://huggingface.co/csukuangfj/sherpa-onnx-paraformer-zh-2023-09-14/resolve/'+PARAFORMER_REVISION+'/'
PARAFORMER_FILES={
 'model.int8.onnx':(243371218,'f36a0433bcf096bd6d6f11b80a3ac8bed110bdca632fe0d731df8d1a84475945'),
 'tokens.txt':(75756,'59aba8873a2ed1e122c25fee421e25f283b63290efbde85c1f01a853d83cb6e6'),
 'README.md':(191,'7fa50f584c7f944ce9bf97d53e69050d92dbae745091603fa212f0edd94c7acf'),
 'LICENSE':(11358,'cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30'),
 'MODEL_LICENSE':FILES['MODEL_LICENSE'],
 'silero_vad.onnx':FILES['silero_vad.onnx'],
 'SILERO_LICENSE':FILES['SILERO_LICENSE']}
PARAFORMER_SOURCES={**SOURCES,
 'LICENSE':'https://raw.githubusercontent.com/k2-fsa/sherpa-onnx/11afbd009a7f8c08f4bcf2fc1b265d0df4670fbf/LICENSE'}
MODELS={
 'sensevoice':{
     'name':'SenseVoice Small INT8','folder':'sensevoice-small',
     'kind':'sherpa','gpu_supported':True,
     'required_files':[['model.int8.onnx','model.onnx'],['tokens.txt']],
     'languages':['auto','zh','en','ja','ko','yue'],
     'language_hint':'Chinese, English, Japanese, Korean and Cantonese',
     'revision':REVISION,'base':BASE,'files':FILES,'sources':SOURCES,
     'notice':'SenseVoiceSmall model weights: Alibaba Group.\n'
              'ONNX conversion: sherpa-onnx contributors / csukuangfj.\n'
              'Model terms: MODEL_LICENSE (FunASR Model Open Source License Agreement v1.1).\n'
              'Original model: https://huggingface.co/FunAudioLLM/SenseVoiceSmall\n'},
 'paraformer':{
     'name':'Paraformer Chinese + English INT8','folder':'paraformer-zh',
     'kind':'sherpa','gpu_supported':False,
     'required_files':[['model.int8.onnx','model.onnx'],['tokens.txt']],
     'languages':['auto','zh','en'], 'language_hint':'Chinese and English',
     'revision':PARAFORMER_REVISION,'base':PARAFORMER_BASE,
     'files':PARAFORMER_FILES,'sources':PARAFORMER_SOURCES,
     'notice':'Paraformer model weights: Alibaba Group.\n'
              'ONNX conversion: sherpa-onnx contributors / csukuangfj.\n'
              'Conversion model card lists Apache-2.0; retained as README.md and LICENSE.\n'
              'FunASR model family terms are retained as MODEL_LICENSE.\n'
              'Original model: https://www.modelscope.cn/models/iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-onnx\n'
              'Languages: Chinese and English. This ASR model does not restore punctuation.\n'}}

# CapsWriter's published archives are pinned by release-asset SHA256. Their
# extracted contents are authenticated by that archive hash; member sizes and
# an explicit filename allowlist also guard extraction. No model is downloaded
# implicitly while transcribing.
CAPSWRITER_REVISION='84912d5218ee5e51e216c54dc15a1cb0f466eb76'
CAPSWRITER_BASE='https://github.com/HaujetZhao/CapsWriter-Offline/releases/download/models/'
CAPSWRITER_LICENSE=(1068,'a79d5745b690b0ea72608cf1d1ac86626c9400e3e4111eb1cf7d1b98b8b3dfd1')
CAPSWRITER_LICENSE_URL='https://raw.githubusercontent.com/HaujetZhao/CapsWriter-Offline/'+CAPSWRITER_REVISION+'/LICENSE'
_VAD_FILES={name:FILES[name] for name in ('silero_vad.onnx','SILERO_LICENSE')}
_VAD_SOURCES={name:SOURCES[name] for name in _VAD_FILES}
_CONVERSION_NOTICE=('ONNX/GGUF conversion: HaujetZhao / CapsWriter-Offline.\n'
                    'Conversion code license: LICENSE (MIT).\n'
                    'Conversion source revision: '+CAPSWRITER_REVISION+'\n')

MODELS['sensevoice']['gpu_variant']={
    'name':'SenseVoice Small FP16 (DirectML)', 'folder':'sensevoice-small-dml',
    'kind':'split_onnx','gpu_supported':True,
    'languages':MODELS['sensevoice']['languages'],
    'language_hint':MODELS['sensevoice']['language_hint'],
    'revision':'3948b5761f12db1c01d7a7e596294b43b0316aa5c7a8df77981e78573997dcbb',
    'base':CAPSWRITER_BASE,
    'archive':{'name':'Sensevoice-Small-ONNX.zip','size':433798984,
               'sha256':'3948b5761f12db1c01d7a7e596294b43b0316aa5c7a8df77981e78573997dcbb',
               'members':{'SenseVoice-CTC.fp16.onnx':25711621,
                          'SenseVoice-Encoder.fp16.onnx':447453789,
                          'tokenizer.bpe.model':377341}},
    'required_files':[['SenseVoice-Encoder.fp16.onnx'],['SenseVoice-CTC.fp16.onnx'],['tokenizer.bpe.model']],
    'files':{**_VAD_FILES,'LICENSE':CAPSWRITER_LICENSE,'MODEL_LICENSE':FILES['MODEL_LICENSE']},
    'sources':{**_VAD_SOURCES,'LICENSE':CAPSWRITER_LICENSE_URL,'MODEL_LICENSE':SOURCES['MODEL_LICENSE']},
    'notice':'SenseVoiceSmall model weights: Alibaba Group.\n'+_CONVERSION_NOTICE+
             'Model terms: MODEL_LICENSE (FunASR Model Open Source License Agreement v1.1).\n'
             'Original model: https://huggingface.co/FunAudioLLM/SenseVoiceSmall\n'}

MODELS['fun_asr_nano']={
    'name':'Fun-ASR-Nano Q5_K (ONNX + GGUF)','folder':'fun-asr-nano',
    'kind':'gguf','gpu_supported':True,
    'languages':['auto','zh','en','ja'], 'language_hint':'Chinese, English and Japanese',
    'revision':'26a557923aedc44f1a3033d0a9b9c7b13cbb551f57fb9fd4b15a67bb4b57f998',
    'base':CAPSWRITER_BASE,
    'archive':{'name':'Fun-ASR-Nano-GGUF.zip','size':834231292,
               'sha256':'26a557923aedc44f1a3033d0a9b9c7b13cbb551f57fb9fd4b15a67bb4b57f998',
               'members':{'Fun-ASR-Nano-CTC.fp16.onnx':78185816,
                          'Fun-ASR-Nano-Decoder.q5_k.gguf':444414752,
                          'Fun-ASR-Nano-Encoder-Adaptor.fp16.onnx':464131509,
                          'tokens.txt':1000331}},
    'required_files':[['Fun-ASR-Nano-Encoder-Adaptor.fp16.onnx'],['Fun-ASR-Nano-Decoder.q5_k.gguf'],
                      ['Fun-ASR-Nano-CTC.fp16.onnx'],['tokens.txt']],
    'files':{**_VAD_FILES,'LICENSE':CAPSWRITER_LICENSE,
             'MODEL_LICENSE':(11357,'c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4'),
             'MODEL_CARD.md':(14586,'c6b3c162768ab8482d65aabb836d2216b137b5fe10276c2dbc3e21c362d741e1')},
    'sources':{**_VAD_SOURCES,'LICENSE':CAPSWRITER_LICENSE_URL,
               'MODEL_LICENSE':'https://raw.githubusercontent.com/FunAudioLLM/Fun-ASR/0339018ba74a7defa3b6b6a96718d17b816be77b/LICENSE',
               'MODEL_CARD.md':'https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512/resolve/272c57b82523ada6fd87095e955f8e29100979ab/README.md'},
    'notice':'Fun-ASR-Nano-2512 model weights: Alibaba Group / FunAudioLLM.\n'+_CONVERSION_NOTICE+
             'Original model card lists Apache-2.0; retained as MODEL_CARD.md and MODEL_LICENSE.\n'
             'Original model revision: 272c57b82523ada6fd87095e955f8e29100979ab\n'
             'Original model: https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512\n'}

MODELS['qwen_asr']={
    'name':'Qwen3-ASR 1.7B Q4_K (ONNX + GGUF)','folder':'qwen3-asr',
    'kind':'gguf','gpu_supported':True,
    'languages':['auto','zh','en','yue','ar','de','fr','es','pt','id','it','ko','ru','th','vi','ja',
                 'tr','hi','ms','nl','sv','da','fi','pl','cs','tl','fa','el','hu','mk','ro'],
    'language_hint':'30 languages including Chinese, English, Japanese and Cantonese',
    'revision':'9b3d2a66a4a26a0404c32085ec838b7c482495a7827919a5aa674de617c2757b',
    'base':CAPSWRITER_BASE,
    'archive':{'name':'Qwen3-ASR-1.7B-q4_k.zip','size':1410584449,
               'sha256':'9b3d2a66a4a26a0404c32085ec838b7c482495a7827919a5aa674de617c2757b',
               'members':{'qwen3_asr_encoder_backend.onnx':164740452,
                          'qwen3_asr_encoder_frontend.onnx':20876699,
                          'qwen3_asr_llm.gguf':1282434624}},
    'required_files':[['qwen3_asr_encoder_frontend.onnx','qwen3_asr_encoder_frontend.int4.onnx'],
                      ['qwen3_asr_encoder_backend.onnx','qwen3_asr_encoder_backend.int4.onnx'],
                      ['qwen3_asr_llm.gguf','qwen3_asr_llm.q4_k.gguf','qwen3_asr_llm.q5_k.gguf']],
    'files':{**_VAD_FILES,'LICENSE':CAPSWRITER_LICENSE,
             'MODEL_LICENSE':(11343,'a44a6081c73ad75f0255bb2bb5cab74ef1829565a895a24e53a4f11290ab7655'),
             'MODEL_CARD.md':(57456,'5058416891bc47a2051557765997e8c42f8eb78a0e33c3e775bd17d4b0ba4d50')},
    'sources':{**_VAD_SOURCES,'LICENSE':CAPSWRITER_LICENSE_URL,
               'MODEL_LICENSE':'https://raw.githubusercontent.com/QwenLM/Qwen3-ASR/7c6daf77a2421100f5fb066495372c00129d39ff/LICENSE',
               'MODEL_CARD.md':'https://huggingface.co/Qwen/Qwen3-ASR-1.7B/resolve/7278e1e70fe206f11671096ffdd38061171dd6e5/README.md'},
    'notice':'Qwen3-ASR-1.7B model weights: Alibaba Group / Qwen.\n'+_CONVERSION_NOTICE+
             'Model terms: MODEL_LICENSE (Apache-2.0), with original MODEL_CARD.md retained.\n'
             'Original model revision: 7278e1e70fe206f11671096ffdd38061171dd6e5\n'
             'Original model: https://huggingface.co/Qwen/Qwen3-ASR-1.7B\n'
             'Basic dictation only; word timestamps require a separately installed ForcedAligner.\n'}
_INSTALL_LOCK=threading.Lock()

def _matches(path,size,sha):
    if not path.is_file() or path.stat().st_size!=size:return False
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()==sha

def model_spec(engine,acceleration='cpu'):
    """Return the install specification for an engine and compute backend."""
    if engine not in MODELS:
        raise RuntimeError('Choose a supported local model: SenseVoice, Paraformer, Fun-ASR-Nano or Qwen3-ASR.')
    if acceleration not in ('cpu','gpu'):
        raise RuntimeError('Choose CPU or GPU acceleration.')
    spec=MODELS[engine]
    if acceleration=='gpu':
        if not spec.get('gpu_supported',False):
            raise RuntimeError(spec['name']+' supports CPU inference only.')
        if spec.get('gpu_variant'):return spec['gpu_variant']
    # Preserve constants as the public SenseVoice compatibility API, including
    # callers that override the files when testing the downloader.
    if engine=='sensevoice':
        return {**spec,'revision':REVISION,'base':BASE,'files':FILES,'sources':SOURCES}
    return spec


def download_size(engine,acceleration='cpu'):
    """Model download bytes, excluding the separately managed native runtime."""
    spec=model_spec(engine,acceleration)
    return sum(size for size,sha in spec['files'].values())+spec.get('archive',{}).get('size',0)


def _relative_path(root,name):
    # Paths from a download catalog or manifest must remain under their root.
    if not isinstance(name,str) or '\\' in name or ':' in name or '\x00' in name:
        raise RuntimeError('Invalid model file path.')
    relative=PurePosixPath(name)
    if relative.is_absolute() or not relative.parts or any(part in ('.','..') for part in relative.parts):
        raise RuntimeError('Invalid model file path.')
    path=root.joinpath(*relative.parts)
    if not path.resolve().is_relative_to(root.resolve()):
        raise RuntimeError('Model file path leaves the installation folder.')
    return path


def _release_chunks(client,url,size,cancel):
    """Bounded parallel ranges keep large official release downloads moving.

    Some proxies stall large response bodies. Each range is checked against the
    exact requested offset and size; the caller still authenticates the entire
    assembled archive against its pinned SHA256 before any extraction.
    """
    chunk_size=1024*1024
    stopping=threading.Event()
    def cancelled():
        if cancel.is_set() or stopping.is_set():raise InterruptedError()
    def checked_body(response,start,end):
        try:response.raise_for_status()
        except httpx.HTTPStatusError:
            raise RuntimeError('The model server rejected a download range.') from None
        if response.status_code!=206 or response.headers.get('Content-Range')!=f'bytes {start}-{end}/{size}':
            raise RuntimeError('The model server returned an unexpected download range.')
        data=bytearray()
        for chunk in response.iter_bytes(64*1024):
            cancelled();data.extend(chunk)
            if len(data)>end-start+1:raise RuntimeError('The model download range exceeded its expected size.')
        if len(data)!=end-start+1:raise RuntimeError('The model download range is incomplete.')
        return bytes(data)
    def retry(operation):
        for attempt in range(3):
            cancelled()
            try:return operation()
            except httpx.TransportError:
                cancelled()
                if attempt==2:
                    # Signed release URLs remain transient and never enter
                    # progress messages, manifests, or exception text.
                    raise RuntimeError('The model server could not finish a download range.') from None
                if stopping.wait(.25*(attempt+1)):raise InterruptedError()
    def resolve_release():
        # Resolve the official redirect once, rather than establishing a new
        # GitHub redirect/TLS connection for every 1 MiB. A distinct probe key
        # also prevents a cache mixing this single byte with the first chunk.
        target=url+('&' if '?' in url else '?')+'murmur_probe=1'
        with client.stream('GET',target,headers={'Range':'bytes=0-0'},
                           timeout=httpx.Timeout(15,connect=15)) as response:
            checked_body(response,0,0)
            resolved=str(response.url);location=urlsplit(resolved)
            if (location.scheme!='https' or location.hostname not in
                    ('github.com','release-assets.githubusercontent.com','objects.githubusercontent.com')
                    or location.username or location.password or location.port not in (None,443)):
                raise RuntimeError('The model release redirected to an unexpected download host.')
            return url if location.hostname=='github.com' else resolved
    release_url=retry(resolve_release)
    def fetch(start):
        end=min(size,start+chunk_size)-1
        def request():
            # Distinct query keys prevent a proxy reusing another range.
            target=release_url+('&' if '?' in release_url else '?')+'murmur_range='+str(start)
            with client.stream('GET',target,headers={'Range':f'bytes={start}-{end}'},
                               timeout=httpx.Timeout(15,connect=15)) as response:
                return checked_body(response,start,end)
        return retry(request)
    pending=deque();offsets=iter(range(0,size,chunk_size))
    pool=ThreadPoolExecutor(max_workers=6,thread_name_prefix='MurMur-model-part')
    try:
        for _ in range(6):
            start=next(offsets,None)
            if start is not None:pending.append(pool.submit(fetch,start))
        while pending:
            cancelled()
            yield pending.popleft().result()
            start=next(offsets,None)
            if start is not None:pending.append(pool.submit(fetch,start))
    finally:
        stopping.set()
        for future in pending:future.cancel()
        pool.shutdown(wait=True,cancel_futures=True)


def _download(client,url,path,size,sha,cancel,progress,spec,completed,total):
    if cancel.is_set():raise InterruptedError()
    path.parent.mkdir(parents=True,exist_ok=True)
    partial=path.with_name(path.name+'.download')
    digest=hashlib.sha256();written=0;last_percent=-1
    try:
        def save(chunks):
            nonlocal written,last_percent
            with partial.open('wb') as output:
                for chunk in chunks:
                    if cancel.is_set():raise InterruptedError()
                    written+=len(chunk)
                    if written>size:raise RuntimeError('The model download exceeded its expected size.')
                    output.write(chunk);digest.update(chunk)
                    percent=int((completed+written)*100/max(1,total))
                    if percent!=last_percent:
                        progress(f'Downloading {spec["name"]} · {percent}%');last_percent=percent
        if url.startswith('https://github.com/') and size>64*1024*1024:
            save(_release_chunks(client,url,size,cancel))
        else:
            with client.stream('GET',url) as response:
                response.raise_for_status()
                save(response.iter_bytes(1024*1024))
        if written!=size or digest.hexdigest()!=sha:
            raise RuntimeError('Model integrity check failed. Retry the download.')
        partial.replace(path)
    finally:partial.unlink(missing_ok=True)


def _unpack_archive(archive_path,stage,members,cancel,progress):
    """Extract only the catalog's flat filenames after authenticating the ZIP."""
    found={};records={}
    with zipfile.ZipFile(archive_path) as archive:
        for entry in archive.infolist():
            if cancel.is_set():raise InterruptedError()
            # ZipInfo normalizes backslashes and strips NULs on Windows, so
            # inspect the original central-directory name before using it.
            _relative_path(stage,entry.orig_filename.rstrip('/'))
            if stat.S_ISLNK(entry.external_attr>>16):
                raise RuntimeError('Model archive contains a symbolic link.')
            if entry.is_dir():continue
            name=PurePosixPath(entry.filename).name
            if name not in members or name in found:
                raise RuntimeError('Model archive contains an unexpected or duplicate file.')
            if entry.file_size!=members[name]:
                raise RuntimeError('Model archive member has an unexpected size.')
            found[name]=entry
        if set(found)!=set(members):raise RuntimeError('Model archive is missing required files.')
        for name,entry in found.items():
            progress('Extracting '+name)
            path=_relative_path(stage,name);digest=hashlib.sha256();written=0
            with archive.open(entry) as source,path.open('wb') as output:
                while chunk:=source.read(1024*1024):
                    if cancel.is_set():raise InterruptedError()
                    written+=len(chunk)
                    if written>members[name]:raise RuntimeError('Model archive member exceeded its expected size.')
                    digest.update(chunk);output.write(chunk)
            if written!=members[name]:raise RuntimeError('Model archive member is incomplete.')
            records[name]=(written,digest.hexdigest())
    return records


def installed_file_hashes(folder,engine,acceleration='cpu'):
    """Return expected file metadata without reading any model contents.

    Direct downloads use the pinned catalog hashes. Extracted archive members
    use their recorded SHA256 only if the install manifest identifies the same
    authenticated archive and all filenames/sizes/hash formats match. An empty
    mapping means archive metadata is absent or invalid; callers should report
    integrity as unverified. Callers perform actual file hashing themselves.
    """
    folder=Path(folder).expanduser().resolve();spec=model_spec(engine,acceleration)
    if not spec.get('archive'):return dict(spec['files'])
    try:
        manifest=json.loads((folder/'murmur-model.json').read_text('utf-8'))
        if manifest.get('engine')!=engine or manifest.get('revision')!=spec['revision']:
            return {}
        # GGUF models share their authenticated weights between CPU and GPU.
        # SenseVoice's separate GPU archive has its own revision and folder.
        recorded=manifest['files'];members=spec['archive']['members'];result=dict(spec['files'])
        for name,size in members.items():
            row=recorded[name]
            if not isinstance(row,(list,tuple)) or len(row)!=2 or type(row[0]) is not int or row[0]!=size:return {}
            sha=row[1]
            if not isinstance(sha,str) or len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha):return {}
            _relative_path(folder,name)
            result[name]=(size,sha)
        return result
    except (OSError,ValueError,KeyError,TypeError,RuntimeError):return {}


def _archive_reusable(folder,spec,engine,acceleration):
    """Only reuse files recorded by a verified install of the same archive."""
    recorded=installed_file_hashes(folder,engine,acceleration)
    members=spec['archive']['members']
    if not recorded:return {}
    for name in members:
        size,sha=recorded[name]
        if not _matches(_relative_path(folder,name),size,sha):return {}
    return {name:recorded[name] for name in members}


def install_model(engine,destination,progress=lambda text:None,cancel=None,*,acceleration='cpu'):
    """Install a selected, verified model only when explicitly requested.

    Every remote model revision and file/archive hash is fixed. Existing custom files
    are replaced only after a complete successful download and kept as backups.
    """
    spec=model_spec(engine,acceleration)
    files=spec['files'];sources=spec['sources'];base=spec['base']
    cancel=cancel or threading.Event()
    if not _INSTALL_LOCK.acquire(blocking=False):raise RuntimeError('A model download is already running.')
    try:
        folder=Path(destination).expanduser().resolve();folder.mkdir(parents=True,exist_ok=True)
        total=download_size(engine,acceleration);completed=0;records=dict(files)
        with tempfile.TemporaryDirectory(prefix='.murmur-install-',dir=folder) as temp:
            stage=Path(temp)
            with httpx.Client(follow_redirects=True,timeout=httpx.Timeout(60,connect=15)) as client:
                archive=spec.get('archive')
                if archive:
                    records.update(_archive_reusable(folder,spec,engine,acceleration))
                    if not all(name in records for name in archive['members']):
                        archive_path=stage/'model-archive.zip'
                        _download(client,archive.get('url',base+archive['name']),archive_path,
                                  archive['size'],archive['sha256'],cancel,progress,spec,completed,total)
                        records.update(_unpack_archive(archive_path,stage,archive['members'],cancel,progress))
                        archive_path.unlink()
                    completed+=archive['size']
                for name,(size,sha) in files.items():
                    if cancel.is_set():raise InterruptedError()
                    path=_relative_path(folder,name)
                    if not _matches(path,size,sha):
                        _download(client,sources.get(name,base+name),_relative_path(stage,name),
                                  size,sha,cancel,progress,spec,completed,total)
                    completed+=size
            if cancel.is_set():raise InterruptedError()
            if spec.get('kind')=='gguf':
                from .native_runtime import install_runtime
                install_runtime(progress=progress,cancel=cancel)
            if cancel.is_set():raise InterruptedError()
            # Commit only after every file is authenticated and extraction passed.
            for name in records:
                staged=_relative_path(stage,name)
                if not staged.is_file():continue
                path=_relative_path(folder,name);path.parent.mkdir(parents=True,exist_ok=True)
                if path.exists():
                    path.replace(path.with_name(path.name+'.previous-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')))
                staged.replace(path)
        (folder/'murmur-model.json').write_text(json.dumps({'engine':engine,'acceleration':acceleration,
            'model':spec['name'],'revision':spec['revision'],'files':records},indent=2),'utf-8')
        (folder/'NOTICE.txt').write_text(spec['notice']+'Conversion: '+base+'\nSilero VAD: https://github.com/snakers4/silero-vad (MIT).\n','utf-8')
        progress('Model files downloaded and verified')
        return folder
    finally:_INSTALL_LOCK.release()


def install_sensevoice(destination,progress=lambda text:None,cancel=None):
    """Compatibility wrapper for existing callers and model installations."""
    return install_model('sensevoice',destination,progress,cancel)

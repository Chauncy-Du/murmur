"""Plain-text adapters for the attributed CapsWriter feature extractors.

Prompt construction follows the pinned CapsWriter implementation. This module
does no downloading and creates no network client. Import only in an isolated
worker, so its ONNX Runtime and llama.cpp DLLs cannot collide with sherpa.
"""
import codecs
import os
from pathlib import Path

import numpy as np

from .onnx_session import set_threads


def _device_diagnostics(provider):
    if provider.upper() != 'DML':
        return {'directml_device_id': None, 'directml_adapter': None}
    from .gpu_devices import dxgi_adapters
    adapters = dxgi_adapters()
    # make_session passes no override, so ORT's documented default is index 0.
    return {'directml_device_id': 0,
            'directml_adapter': next((item for item in adapters if item['device_id'] == 0), None)}


def create_engine(engine, model_dir, *, threads=2, onnx_provider='CPU',
                  llm_use_gpu=False, language='auto', runtime_dir=None):
    set_threads(threads)
    if engine == 'sensevoice':
        return SenseVoice(model_dir, onnx_provider, language)
    if engine in ('fun_asr_nano', 'qwen_asr'):
        return GenerativeASR(engine, model_dir, threads, onnx_provider,
                             llm_use_gpu, runtime_dir)
    raise RuntimeError('Unsupported local transcription engine.')


class SenseVoice:
    def __init__(self, folder, provider, language):
        import sentencepiece
        from .fun_encoder import FunASRMelExtractor
        from .sensevoice_encoder import SenseVoiceEncoder
        from .sensevoice_decoder import SenseVoiceDecoder
        folder = Path(folder)
        self.language = language
        self.encoder = SenseVoiceEncoder(str(folder/'SenseVoice-Encoder.fp16.onnx'),
                                         provider, dml_pad_to=30)
        self.decoder = SenseVoiceDecoder(str(folder/'SenseVoice-CTC.fp16.onnx'),
                                         provider, dml_pad_to=30)
        self.frontend = FunASRMelExtractor()
        self.tokenizer = sentencepiece.SentencePieceProcessor()
        self.tokenizer.load_from_serialized_proto((folder/'tokenizer.bpe.model').read_bytes())
        self.diagnostics = {
            'engine': 'sensevoice', 'worker_pid': os.getpid(),
            'encoder_providers': self.encoder.session.get_providers(),
            'decoder_providers': self.decoder.session.get_providers(),
            'decoder_backend': 'ONNX',
            'onnx_provider_options': [self.encoder.session.get_provider_options(),
                                      self.decoder.session.get_provider_options()],
            **_device_diagnostics(provider),
        }

    def transcribe(self, samples):
        features = self.frontend.extract(samples)
        encoded = self.encoder.forward(features, lid=self.language, itn=True)
        results, _, _, _ = self.decoder.decode_all(
            encoded, self.tokenizer, top_k=1, T_valid=features.shape[0])
        return ''.join(item['text'] for item in results).strip()

    def close(self):
        self.encoder = self.decoder = self.frontend = self.tokenizer = None


class GenerativeASR:
    def __init__(self, engine, folder, threads, provider, use_gpu, runtime_dir):
        from . import llama
        self.llama = llama
        self.engine = engine
        self.model = self.ctx = self.embedding_table = self.encoder = None
        llama.set_runtime_directory(runtime_dir)
        folder = Path(folder)
        from ...gguf_asr import required_files
        paths = required_files(engine, folder)
        try:
            if engine == 'fun_asr_nano':
                from .fun_encoder import AudioEncoder
                self.encoder = AudioEncoder(str(paths[0]),
                                            provider, dml_pad_to=30)
                gguf = paths[1]
                sessions = [self.encoder.sess]
            else:
                from .qwen_encoder import QwenAudioEncoder
                self.encoder = QwenAudioEncoder(
                    str(paths[0]), str(paths[1]),
                    provider, dml_pad_to=30, verbose=False)
                gguf = paths[2]
                sessions = [self.encoder.sess_fe, self.encoder.sess_be]
            self.model = llama.LlamaModel(str(gguf), use_gpu=use_gpu)
            self.embedding_table = llama.get_token_embeddings_gguf(str(gguf))
            if self.embedding_table is None:
                raise RuntimeError('The GGUF model is missing its token embedding table.')
            self.ctx = llama.LlamaContext(self.model, n_ctx=4096, n_batch=4096,
                                          n_threads=threads, n_threads_batch=threads,
                                          offload_kqv=use_gpu)
            self.end_token = self.model.token_to_id('<|im_end|>')
            self.diagnostics = {
                'engine': engine, 'worker_pid': os.getpid(),
                'encoder_providers': [s.get_providers() for s in sessions],
                'decoder_backend': 'Vulkan' if use_gpu else 'CPU',
                'llama_runtime': str(runtime_dir), 'threads': threads,
                'gpu_model_buffers': self.model.gpu_model_buffers,
                'vulkan_devices': self.model.gpu_devices,
                'offload_information': self.model.offload_information,
                'model_files': [path.name for path in paths],
                'onnx_provider_options': [session.get_provider_options() for session in sessions],
                **_device_diagnostics(provider),
            }
        except BaseException:
            self.close()
            raise

    def _prompt(self, audio_embeddings):
        if self.engine == 'fun_asr_nano':
            before = self.model.tokenize(
                '<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n'
                '<|im_start|>user\n语音转写：')
            after = self.model.tokenize('<|im_end|>\n<|im_start|>assistant\n')
        else:
            token = self.model.token_to_id
            text = self.model.tokenize
            before = ([token('<|im_start|>')] + text('system\nYou are a helpful assistant.')
                      + [self.end_token, token('<|im_start|>')] + text('user\n')
                      + [token('<|audio_start|>')])
            after = ([token('<|audio_end|>'), self.end_token, token('<|im_start|>')]
                     + text('assistant\n') + [token('<asr_text>')])
        return np.concatenate([self.embedding_table[before],
                               audio_embeddings.astype(np.float32),
                               self.embedding_table[after]], axis=0)

    def transcribe(self, samples):
        audio_embeddings, _ = self.encoder.encode(samples)
        full_embeddings = self._prompt(audio_embeddings)
        llama = self.llama
        total = len(full_embeddings)
        if total + 512 > 4096:
            raise RuntimeError('The local decoder context is full. Record shorter phrases.')
        # Qwen3 uses four position planes. Allocate enough position capacity
        # before copying, mirroring the pinned upstream ASR implementation.
        batch = llama.LlamaBatch(total * 4 if self.engine == 'qwen_asr' else total,
                                 self.model.n_embd, 1)
        if self.engine == 'qwen_asr':
            positions = np.arange(total, dtype=np.int32)
            positions = np.concatenate([positions, positions, positions,
                                        np.zeros(total, dtype=np.int32)])
            batch.set_embd(full_embeddings, pos=positions)
        else:
            batch.set_embd(full_embeddings)
        self.ctx.clear_kv_cache()
        if self.ctx.decode(batch) != 0:
            raise RuntimeError('The local GGUF decoder could not process the audio embeddings.')
        del batch
        tokens = []
        pieces = []
        decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        # Greedy decoding makes local dictation repeatable. Never insert a
        # partial result when a native decode fails or generation loops.
        with llama.LlamaSampler(temperature=0.0) as sampler:
            for _ in range(512):
                token = sampler.sample(self.ctx, -1)
                if token in (self.model.eos_token, self.end_token):
                    pieces.append(decoder.decode(b'', final=True))
                    return ''.join(pieces).strip()
                tokens.append(token)
                pieces.append(decoder.decode(self.model.token_to_bytes(token)))
                if len(tokens) >= 30 and len(set(tokens[-30:])) <= 3:
                    raise RuntimeError('The local decoder repeated the same phrase. Try recording again.')
                if self.ctx.decode_token(token) != 0:
                    raise RuntimeError('The local GGUF decoder failed while transcribing.')
        raise RuntimeError('The local decoder reached its output limit. Record shorter phrases.')

    def close(self):
        # Context owns a reference to the model, so release it first.
        if self.ctx is not None:
            self.ctx.close()
            self.ctx = None
        if self.model is not None:
            self.model.close()
            self.model = None
        self.embedding_table = self.encoder = None

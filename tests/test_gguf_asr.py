"""Offline worker protocol, bounded audio and explicit acceleration checks."""
import sys
from types import SimpleNamespace
import threading

import numpy as np
import pytest

from murmur import gguf_asr


def fixture_model(folder, engine):
    for name in gguf_asr.ENGINE_FILES[engine]:
        (folder/name).write_bytes(b'local model fixture')


@pytest.mark.parametrize('engine', ['sensevoice', 'fun_asr_nano', 'qwen_asr'])
def test_incomplete_model_rejected_before_process_start(tmp_path, monkeypatch, engine):
    monkeypatch.setattr(gguf_asr, '_start_worker', lambda *a: pytest.fail('Unexpected process'))
    with pytest.raises(RuntimeError, match='incomplete'):
        gguf_asr.load_model(engine, tmp_path)


def test_unknown_engine_rejected_before_runtime_import(tmp_path, monkeypatch):
    monkeypatch.setattr(gguf_asr, '_start_worker', lambda *a: pytest.fail('Unexpected process'))
    with pytest.raises(RuntimeError, match='supported local'):
        gguf_asr.load_model('cloud-model', tmp_path)


@pytest.mark.parametrize('decoder', ['qwen3_asr_llm.q4_k.gguf', 'qwen3_asr_llm.q5_k.gguf'])
def test_qwen_imported_upstream_aliases_are_selected(tmp_path, decoder):
    names = ('qwen3_asr_encoder_frontend.int4.onnx',
             'qwen3_asr_encoder_backend.int4.onnx', decoder)
    for name in names:
        (tmp_path/name).write_bytes(b'fixture')
    assert tuple(path.name for path in gguf_asr.required_files('qwen_asr', tmp_path)) == names


def test_canonical_qwen_files_take_precedence_over_imported_aliases(tmp_path):
    fixture_model(tmp_path, 'qwen_asr')
    for names in gguf_asr.ENGINE_FILE_ALTERNATIVES['qwen_asr']:
        for name in names[1:]:
            (tmp_path/name).write_bytes(b'alias fixture')
    assert tuple(path.name for path in gguf_asr.required_files('qwen_asr', tmp_path)) == gguf_asr.ENGINE_FILES['qwen_asr']


@pytest.mark.parametrize('threads', [0, 17, True, '2'])
def test_threads_checked_before_process_start(tmp_path, threads):
    fixture_model(tmp_path, 'sensevoice')
    with pytest.raises(RuntimeError, match='threads'):
        gguf_asr.load_model('sensevoice', tmp_path, threads=threads)


def test_cancelled_load_does_not_start_worker(tmp_path, monkeypatch):
    fixture_model(tmp_path, 'sensevoice')
    event = threading.Event()
    event.set()
    monkeypatch.setattr(gguf_asr, '_start_worker', lambda *a: pytest.fail('Unexpected process'))
    with pytest.raises(InterruptedError):
        gguf_asr.load_model('sensevoice', tmp_path, cancel=event)


def test_split_sensevoice_options_forwarded_without_llama_dependency(tmp_path, monkeypatch):
    fixture_model(tmp_path, 'sensevoice')
    calls = []
    monkeypatch.setattr(gguf_asr, '_start_worker', lambda options, cancel: calls.append(options) or 'worker')
    assert gguf_asr.load_model('sensevoice', tmp_path, threads=4,
                               onnx_provider='dml', language='zh') == 'worker'
    assert calls[0]['onnx_provider'] == 'DML'
    assert calls[0]['threads'] == 4 and calls[0]['language'] == 'zh'
    assert calls[0]['runtime_dir'] is None


def test_stream_appends_samples_and_copies_capture_buffers():
    stream = gguf_asr.RecognitionStream()
    first = np.ones(800, dtype=np.float32)
    stream.accept_waveform(16000, first)
    first[:] = 0
    stream.accept_waveform(16000, np.full(800, .5, dtype=np.float32))
    assert np.array_equal(stream.samples()[:800], np.ones(800))
    assert np.array_equal(stream.samples()[800:], np.full(800, .5))


@pytest.mark.parametrize('rate,audio', [(48000, [0.1]), (16000, [[0.1]]),
                                      (16000, [np.nan]), (16000, [np.inf])])
def test_stream_rejects_invalid_audio(rate, audio):
    with pytest.raises(RuntimeError):
        gguf_asr.RecognitionStream().accept_waveform(rate, audio)


def test_stream_requires_complete_segment_and_never_truncates():
    stream = gguf_asr.RecognitionStream()
    with pytest.raises(RuntimeError, match='complete speech'):
        stream.samples()
    with pytest.raises(RuntimeError, match='exceeds 30 seconds'):
        stream.accept_waveform(16000, np.ones(480001, dtype=np.float32))
    assert stream._sample_count == 0


class FakeProcess:
    def __init__(self):
        self.alive = True
        self.exitcode = None
        self.terminated = False

    def is_alive(self):
        return self.alive

    def join(self, timeout):
        pass

    def terminate(self):
        self.terminated = True
        self.alive = False
        self.exitcode = 1


class FakePipe:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []
        self.closed = False

    def poll(self, timeout):
        return bool(self.responses)

    def recv(self):
        return self.responses.pop(0)

    def send(self, message):
        self.sent.append(message)

    def close(self):
        self.closed = True


def proxy(responses):
    process = FakeProcess()
    pipe = FakePipe([('ready', {'decoder_backend': 'CPU', 'worker_pid': 123})] + responses)
    return gguf_asr.LocalRecognizer(process, pipe), process, pipe


def test_proxy_sets_stream_result_and_exposes_actual_worker_diagnostics():
    recognizer, process, pipe = proxy([('result', '你好世界')])
    stream = recognizer.create_stream()
    stream.accept_waveform(16000, np.ones(1600, dtype=np.float32))
    recognizer.decode_stream(stream)
    assert stream.result.text == '你好世界'
    assert pipe.sent[0][0] == 'transcribe'
    assert recognizer.diagnostics['worker_pid'] == 123
    recognizer.close()
    recognizer.close()
    assert process.terminated and pipe.closed


def test_proxy_never_inserts_partial_text_after_decode_failure():
    recognizer, process, pipe = proxy([('error', 'DirectML model failed')])
    stream = recognizer.create_stream()
    stream.result.text = 'old result'
    stream.accept_waveform(16000, np.ones(1600, dtype=np.float32))
    with pytest.raises(RuntimeError, match='DirectML model failed'):
        recognizer.decode_stream(stream)
    assert stream.result.text == '' and process.terminated and pipe.closed


def test_cancelled_decode_stops_worker_without_inserting_text():
    recognizer, process, pipe = proxy([])
    stream = recognizer.create_stream()
    stream.accept_waveform(16000, np.ones(1600, dtype=np.float32))
    event = threading.Event()
    # Cancellation arrives after the PCM was submitted to native inference.
    original_send = pipe.send
    def send(message):
        original_send(message)
        event.set()
    pipe.send = send
    with pytest.raises(InterruptedError):
        recognizer.decode_stream(stream, event)
    assert process.terminated and pipe.closed and stream.result.text == ''


def test_failed_load_closes_process_and_pipe():
    process = FakeProcess()
    pipe = FakePipe([('error', 'Invalid GGUF file')])
    with pytest.raises(RuntimeError, match='Invalid GGUF'):
        gguf_asr.LocalRecognizer(process, pipe)
    assert process.terminated and pipe.closed


def test_native_crash_becomes_explicit_local_failure():
    recognizer, process, pipe = proxy([])
    process.alive = False
    process.exitcode = 0xc0000005
    with pytest.raises(RuntimeError, match='No audio was sent online'):
        recognizer._reply(1)
    recognizer.close()


def test_worker_uses_only_private_pcm_protocol(monkeypatch):
    samples = np.ones(1600, dtype=np.float32)
    closed = []
    engine = SimpleNamespace(diagnostics={'worker_pid': 456},
                             transcribe=lambda audio: 'local text' if np.array_equal(audio, samples) else '',
                             close=lambda: closed.append(True))
    monkeypatch.setitem(sys.modules, 'murmur.vendor.capswriter.runtime',
                        SimpleNamespace(create_engine=lambda **kwargs: engine))
    connection = FakePipe([('transcribe', samples), ('close', None)])
    gguf_asr._worker(connection, {'engine': 'qwen_asr'})
    assert connection.sent == [('ready', {'worker_pid': 456}), ('result', 'local text')]
    assert closed == [True] and connection.closed


def test_requested_directml_must_be_available(monkeypatch):
    from murmur.vendor.capswriter import onnx_session
    monkeypatch.setattr(onnx_session.ort, 'get_available_providers', lambda: ['CPUExecutionProvider'])
    monkeypatch.setattr(onnx_session.ort, 'InferenceSession', lambda *a, **k: pytest.fail('Unexpected session'))
    with pytest.raises(RuntimeError, match='DmlExecutionProvider is unavailable'):
        onnx_session.make_session('fixture.onnx', 'DML')


def test_directml_session_uses_required_options_and_checks_effective_provider(monkeypatch):
    from murmur.vendor.capswriter import onnx_session
    ort = onnx_session.ort
    calls = []
    no_fallback = []
    monkeypatch.setattr(ort, 'get_available_providers', lambda: ['DmlExecutionProvider', 'CPUExecutionProvider'])
    def session(path, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(get_providers=lambda: kwargs['providers'],
                               disable_fallback=lambda: no_fallback.append(True))
    monkeypatch.setattr(ort, 'InferenceSession', session)
    onnx_session.make_session('fixture.onnx', 'DML')
    options = calls[0]['sess_options']
    assert options.enable_mem_pattern is False
    assert options.execution_mode == ort.ExecutionMode.ORT_SEQUENTIAL
    assert calls[0]['providers'][0] == 'DmlExecutionProvider'
    assert no_fallback == [True]
    monkeypatch.setattr(ort, 'InferenceSession', lambda *a, **k: SimpleNamespace(get_providers=lambda: ['CPUExecutionProvider']))
    with pytest.raises(RuntimeError, match='could not be initialized'):
        onnx_session.make_session('fixture.onnx', 'DML')


def test_vendored_native_import_does_not_change_cwd_or_path(monkeypatch):
    import os
    import ctypes
    monkeypatch.setattr(os, 'chdir', lambda *a: pytest.fail('Unexpected cwd mutation'))
    monkeypatch.setattr(ctypes, 'CDLL', lambda *a: pytest.fail('Unexpected native load at import'))
    from murmur.vendor.capswriter import llama
    assert llama.llama is None


def mocked_generative_engine(engine_name='qwen_asr', prefill_status=0,
                             generated_tokens=(1, 2, 99)):
    from murmur.vendor.capswriter.runtime import GenerativeASR
    engine = GenerativeASR.__new__(GenerativeASR)
    engine.engine = engine_name
    engine.encoder = SimpleNamespace(encode=lambda audio: (np.ones((3, 8), np.float32), 0))
    engine.end_token = 99
    engine.model = SimpleNamespace(n_embd=8, eos_token=98,
        tokenize=lambda text: [4, 5], token_to_id=lambda text: 6,
        token_to_bytes=lambda token: {1:b'\xe4\xbd', 2:b'\xa0'}.get(token, b'a'))
    engine.embedding_table = np.ones((100, 8), np.float32)
    batches = []
    class Batch:
        def __init__(self, capacity, dim, seq):
            self.capacity = capacity
            self.dim = dim
            batches.append(self)
        def set_embd(self, embeddings, pos=None):
            self.embeddings = embeddings
            self.positions = pos
    tokens = iter(generated_tokens)
    class Sampler:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def sample(self, *args):
            return next(tokens)
    engine.llama = SimpleNamespace(LlamaBatch=Batch, LlamaSampler=Sampler)
    engine.ctx = SimpleNamespace(clear_kv_cache=lambda:None,
                                 decode=lambda batch:prefill_status,
                                 decode_token=lambda token:0)
    return engine, batches


@pytest.mark.parametrize('name', ['fun_asr_nano', 'qwen_asr'])
def test_native_generation_decodes_utf8_incrementally_and_bounds_position_copy(name):
    engine, batches = mocked_generative_engine(name)
    assert engine.transcribe(np.ones(1600, np.float32)) == '你'
    batch = batches[0]
    if name == 'qwen_asr':
        assert batch.positions.dtype == np.int32
        assert len(batch.positions) <= batch.capacity
        assert len(batch.positions) == 4 * len(batch.embeddings)
    else:
        assert batch.positions is None


def test_native_prefill_failure_is_not_returned_as_partial_transcription():
    engine, _ = mocked_generative_engine(prefill_status=-1)
    with pytest.raises(RuntimeError, match='could not process the audio embeddings'):
        engine.transcribe(np.ones(1600, np.float32))


def test_native_generation_failure_is_not_returned_as_partial_transcription():
    engine, _ = mocked_generative_engine()
    engine.ctx.decode_token = lambda token:-1
    with pytest.raises(RuntimeError, match='failed while transcribing'):
        engine.transcribe(np.ones(1600, np.float32))


def test_native_repetition_stops_inference_instead_of_inserting_looped_text():
    engine, _ = mocked_generative_engine(generated_tokens=[7] * 32)
    with pytest.raises(RuntimeError, match='repeated the same phrase'):
        engine.transcribe(np.ones(1600, np.float32))

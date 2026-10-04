"""Explicit offline ONNX sessions for CapsWriter's exported models."""
import onnxruntime as ort

_threads = 2


def set_threads(threads):
    global _threads
    _threads = threads


def make_session(path, provider='CPU'):
    provider = provider.upper()
    name = {'CPU': 'CPUExecutionProvider', 'DML': 'DmlExecutionProvider'}.get(provider)
    if name is None:
        raise RuntimeError('Choose CPU or DirectML for the local encoder.')
    if name not in ort.get_available_providers():
        raise RuntimeError(f'{name} is unavailable. Install the complete local ASR dependencies.')
    options = ort.SessionOptions()
    options.log_severity_level = 3
    options.intra_op_num_threads = _threads
    options.inter_op_num_threads = 1
    options.add_session_config_entry('session.intra_op.allow_spinning', '0')
    options.add_session_config_entry('session.inter_op.allow_spinning', '0')
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    if provider == 'DML':
        options.enable_mem_pattern = False
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    providers = [name]
    if provider == 'DML':
        providers.append('CPUExecutionProvider')
    session = ort.InferenceSession(str(path), sess_options=options, providers=providers)
    # ORT can disable a failing provider during construction. Do not claim GPU
    # acceleration while silently accepting an entirely CPU session.
    if session.get_providers()[0] != name:
        raise RuntimeError(f'{name} could not be initialized for this model.')
    session.disable_fallback()
    return session

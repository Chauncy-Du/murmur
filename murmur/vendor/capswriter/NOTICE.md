# CapsWriter-Offline inference helpers

Source: https://github.com/HaujetZhao/CapsWriter-Offline

Pinned source commit: `84912d5218ee5e51e216c54dc15a1cb0f466eb76`

License: MIT, Copyright (c) 2026 Haujet Zhao. The complete license is in
`LICENSE` beside these files.

Adapted files:

- `core/server/engines/llama/llama.py` -> `llama.py`
- `core/server/engines/fun_asr_gguf/inference/encoder.py` -> `fun_encoder.py`
- `core/server/engines/qwen_asr_gguf/inference/encoder.py` -> `qwen_encoder.py`
- `core/server/engines/sensevoice_onnx/inference/encoder.py` -> `sensevoice_encoder.py`
- `core/server/engines/sensevoice_onnx/inference/decoder.py` -> `sensevoice_decoder.py`

MurMur replaces process-wide working-directory/PATH mutation and eager DLL
initialization with explicit runtime paths, process isolation and lazy loading.
ONNX provider selection is checked; selecting acceleration fails explicitly
when the provider or Vulkan device is unavailable. ONNX thread limits are
respected, DirectML sessions disable memory patterns and use sequential
execution, and CPU-only model loading does not warm up 30 seconds of silence.

The transcription adapter uses the upstream NumPy feature extraction and
prompt construction. Optional CapsWriter hotwords and token timestamp
alignment are outside this adapter's plain-text dictation interface.
Generation uses deterministic greedy decoding and reports decoder failure or
repetition without returning a partial transcription.
Imported Qwen exports may use the upstream `.int4.onnx` encoder names and
`.q4_k.gguf` / `.q5_k.gguf` decoder names. Files must use CapsWriter's split
encoder graph input/output contract; arbitrary Hugging Face/PyTorch weights
or an unrelated GGUF language model are unsupported.

Native inference requires the pinned llama.cpp `b10621` runtime, licensed MIT
by ggml-org. Runtime installation retains its own license and provenance.

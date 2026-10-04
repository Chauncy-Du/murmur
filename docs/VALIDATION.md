# MurMur 0.4.5 public source validation

Source publication date: 2026-10-05. Development validation date: 2026-10-04.

The recorded frozen regression passed **1849 tests across 86 test files**, with no failures, skips or errors. Its recorded duration was 261.891 seconds. Before this upload, all **158 frozen source/test/resource hashes** still matched the active files. This verifies the applicability of that historical test snapshot; the full suite was not repeated for this upload.

For this upload, **276 selected tests passed in 14.22 seconds**, covering participant fidelity, shared editing, prompts, service accessibility, core behavior, assets, storage defaults and release/download contracts. Another **3 source-version tests passed in 0.47 seconds**. These 279 checks are reported separately from the prior full suite. `uv lock --check --offline` passed for 79 packages, and `Start-MurMur.cmd --help` exited successfully.

The previous isolated application startup exited successfully and generated 16 synthetic screenshots. Six recorded actual requests to the installed local qwen3.5:4b model were assessed as five complete and one partial quality passes. The partial result omitted the explicit subject of “I hope”; preference expressions remain outside the finite cognitive-state guard. These samples do not establish a general accuracy or latency benchmark. See [0.4.5 changes and limitations](RELEASE_0.4.5.md).

Public source file inventories and all remote blob hashes are verified during upload. Implementation, tests, assets and licenses are copied unchanged; public documentation excludes private migration and conversation details. Internal logs, screenshots and personal evidence remain local.

No new live microphone, physical hotkey, focus, insertion, cloud-audio or mixed-DPI acceptance is claimed. This source push creates a version tag, not a GitHub Release or binary asset. No model weights, native runtimes, private data or credentials are uploaded. The [portable security block](PORTABLE_SECURITY_BLOCK.txt) remains in place.

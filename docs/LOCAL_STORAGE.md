# MurMur local storage

Current defaults use `D:\LocalProjects\MurMur`, independently of the checkout's working directory. Follow the [first installation instructions](../README.md) when using this source snapshot.

| Content | Default location |
| --- | --- |
| Application settings, history, optional recordings, startup errors | `data/` |
| Speech models, in separate engine/format directories | `models/` |
| Native ASR runtimes | `runtimes/llama-b10621/` |
| Credentials | Windows Credential Manager |
| Compatible text models | Existing Ollama-managed storage |

An explicit `--data-dir` overrides application data only; model and runtime roots remain independent. Normal launchers do not set it. Model weights and native runtimes are installed separately through the application and retain their own licenses.

Run `uv sync --locked` for first installation, then use `Start-MurMur.cmd` for daily startup without dependency synchronization. See [LOCAL_RUN.md](../LOCAL_RUN.md).

Private data, credentials, API.txt, model weights, runtimes, screenshots, caches and internal work/migration evidence are excluded from this public source snapshot. Local migration records are preserved privately. The [portable security block](PORTABLE_SECURITY_BLOCK.txt) remains in place.

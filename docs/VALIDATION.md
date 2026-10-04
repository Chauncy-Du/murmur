# Public source validation record

Date: 2026-10-04. Repository: [Chauncy-Du/murmur](https://github.com/Chauncy-Du/murmur).

Before this source upload, the existing local environment passed **95 tests in 8.71 seconds**:

```powershell
uv run --no-sync python -m pytest -q tests/test_core.py tests/test_provider_icons.py tests/test_local_storage_paths.py tests/test_release_downloads.py
```

These checks cover core behavior, provider assets, local storage defaults and release/download contracts. Application implementation files are copied unchanged. Source file hashes and the final GitHub tree are checked during upload.

Earlier local documentation recorded 927 regression tests with three upstream warnings. That historical result is not a new full-suite run for this upload. More detailed recorded scopes and limitations are in [Ask validation](ASK_ANYTHING_VALIDATION.md), [dictation/progress validation](DICTATION_AND_PROGRESS_VALIDATION.md) and [service/writing validation](SERVICES_AND_WRITING_VALIDATION.md). Internal logs, private migration records and screenshots are retained locally and are excluded from this repository.

This upload does not revalidate live microphone input, physical shortcuts, cross-application insertion, Windows 10, input methods or mixed-DPI displays. No executable, installer, portable archive or model weights are published. The [portable security block](PORTABLE_SECURITY_BLOCK.txt) and build-script check remain in effect.

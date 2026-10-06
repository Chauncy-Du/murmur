# MurMur 0.4.7 source validation

2026-10-06: 290 affected regression tests passed, 2 failed before upload. Operational source/test/resource hashes were unchanged across the run. Source, pyproject and lockfile identify version 0.4.7.

The combined run had two failures: dashboard resource-card shimmer, and HTTP profile saving. In a separate rerun of these two checks, the resource-card check passed, while the HTTP-profile test still failed because its SimpleNamespace test window has no `check_saved_services` method (1 passed, 1 failed). These reruns are not added to the combined count. The prior 0.4.6 dots-waveform check passed in this run. This snapshot preserves current implementation and test fixtures; no full-green regression is claimed.

See [0.4.7 changes and limitations](RELEASE_0.4.7.md). Previous full-suite and feature-specific results are historical; this upload does not repeat or combine those counts. Internal migration records, logs, personal data and screenshots remain local.

The remote file inventory and all blob hashes are verified after pushing main and v0.4.7. No binary or installer is created, and the [portable security block](PORTABLE_SECURITY_BLOCK.txt) remains unchanged.

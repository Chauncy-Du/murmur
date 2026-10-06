# MurMur 0.4.6 source validation

2026-10-06: 492 affected regression tests passed, 1 failed before upload. Operational source/test/resource hashes were unchanged across the run. Source, pyproject and lockfile identify version 0.4.6.

Known failing check: `test_wave_layout_styles.py::test_each_style_uses_real_input_and_silence_then_fades[12-dots]` at 125% offscreen scaling. The 12-pixel dots image did not differ from silence immediately after feeding levels. An isolated rerun also failed (33 passed, 1 failed). This snapshot retains the current implementation; no fix or full-green regression is claimed.

See [0.4.6 changes and limitations](RELEASE_0.4.6.md). Previous full-suite and feature-specific results are historical; this upload does not repeat or combine those counts. Internal migration records, logs, personal data and screenshots remain local.

The remote file inventory and all blob hashes are verified after pushing main and v0.4.6. No binary or installer is created, and the [portable security block](PORTABLE_SECURITY_BLOCK.txt) remains unchanged.

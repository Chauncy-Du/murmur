# Startup speech model loading

MurMur preloads the selected local speech recognizer on a background thread when the desktop application starts. Demo and online ASR configurations skip native-model loading. Diagnostic screenshot mode also skips it. With microphone standby enabled (now the default), normal startup additionally opens the microphone and waits for its first valid audio frame; online ASR also uses this preparation. See `PRE_RECORDING.md`.

The purple capsule shows **Check files → Load model → Ready**. File validation and successful completion are actual events. Intermediate percentages are a monotonic estimate capped at 95%; the native model loaders do not expose byte-level or layer-level progress. The tooltip identifies estimated progress. Only successful loading displays 100%.

During loading, the main window and preview are disabled. Controller guards also reject dictation, translation, Ask Anything, selection capture, editing, service checks, model downloads, settings saves, and hotkey cancellation. The capsule's recording and cancellation buttons are disabled. Quit remains available through the tray. Late callbacks after quitting are ignored.

At completion, 100% remains visible briefly, then the capsule disappears and controls unlock. Recording reuses the existing recognizer cache. A failure displays an error and unlocks Settings for repairs; speech actions remain blocked until corrected settings are saved and loading succeeds, or another backend is selected.

Validation on 2026-10-06: controller/service/progress tests passed (68 tests); estimated-progress/result-bubble/startup tests passed (32 tests); the final startup/estimated-progress rerun passed (20 tests). Real isolated Qwen3-ASR GPU loading at 125% and 150% confirmed control locking, 100% on completion, capsule hiding, and reuse of the same cached recognizer (~0.01 s lookup). Final rendered screenshots use explicitly loaded Segoe UI fonts for the offscreen platform. Evidence: `work/startup-model-20261006/`. These checks used no microphone, global hotkeys, private history or cloud calls; the running user instance was not restarted.

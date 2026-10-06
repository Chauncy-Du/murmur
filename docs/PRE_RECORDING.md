# Microphone standby and pre-recording

`audio_warm_enabled=true` and `audio_preroll_ms=500` are the defaults, including existing settings files that do not yet contain these options. Settings → General → Audio capture offers **Keep microphone ready**, with **Pre-record buffer · ms** under Advanced (0–2000 ms).

In normal desktop mode, startup prepares the selected local ASR model when applicable, then starts the microphone and waits for a valid input frame before unlocking speech operations. Demo and diagnostic screenshot mode do not enable standby capture. Disabling standby restores microphone-on-demand behavior. A zero buffer keeps the device warm without retaining pre-key audio.

Only one input stream is used. At 16 kHz mono PCM16, a 500 ms buffer holds exactly 16,000 bytes of audio. While idle, the oldest samples are overwritten, with no ASR, upload, audio file or history write. A recording atomically attaches to the stream, obtains the buffered audio in order, then receives new frames through the existing bounded PCM queue. ASR models, silence trimming and network delivery retain their existing behavior. If recording saving is enabled, the intentional session recording includes its pre-roll; unrelated idle audio is never saved.

Stopping or cancelling detaches the session and clears its preceding cache, while the physical microphone continues running. Closing MurMur or disabling standby releases it and erases the ring. Changing microphones or buffer settings prepares a replacement stream under the startup operation lock. Stream errors clear idle audio and stop the active session; saving Settings reconnects an unhealthy stream.

Pre-recording does not recover audio from before the application/microphone is ready, or speech earlier than the selected ring duration. It also cannot correct ASR omissions or hardware audio loss. Startup lock prevents recording before the first valid frame, but a full 500 ms history naturally requires 500 ms of prior capture.

Validation (2026-10-06): synthetic tests cover exact and partial-frame ring limits, zero buffer, ordered one-time transfer, stream reuse, cancellation, errors, cleanup and default validation. A five-second actual input check reached its first frame in approximately 0.90 seconds and retained exactly 16,000 bytes; audio was not saved, recognized or uploaded. CPU time was below the process timer's resolution during this short check, not proof of zero overhead. Evidence: `work/warm-microphone-20261006/idle-check.json`. Real-device dictation across suspend/resume and unplug/replug remains to be tried.

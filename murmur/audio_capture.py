"""One bounded, capture-first PCM path. No microphone runs while idle.

Callbacks never send network data or load models. A deferred collector retains
at most fifty 100 ms frames until a provider calls activate(). Overflow fails
the session instead of silently discarding the beginning of speech.
"""
import queue
import threading
import time

from .audio_levels import pcm_level

SAMPLE_RATE = 16000
FRAME_SAMPLES = 1600
MAX_SECONDS = 600
INPUT_CLOSE_TIMEOUT = 10.
AUDIO_DELIVERY_TIMEOUT = 10.


class PCMCollector:
    def __init__(self, cfg, on_level, cancel, on_frame=None, *,
                 defer_delivery=False, on_error=None):
        self.cfg = cfg
        self.on_level = on_level
        self.cancel = cancel
        self.on_frame = on_frame
        self.on_error = on_error
        self.frames = queue.Queue(maxsize=50)
        self.stream = None
        self.started = 0.
        self.error = ''
        self.recorded_frames = 0
        self.closed = False
        self._pcm = []
        self._lock = threading.RLock()
        self._active = threading.Event()
        if not defer_delivery:
            self._active.set()
        self._aborted = threading.Event()
        self._start_finished = threading.Event()
        self._input_closed = threading.Event()
        self._finished = threading.Event()
        self._start_claimed = False
        self._close_claimed = False
        self._close_scheduled = False
        self._worker = None

    @property
    def duration(self):
        with self._lock:
            return self.recorded_frames / SAMPLE_RATE

    @property
    def pcm(self):
        with self._lock:
            return b''.join(self._pcm)

    def check(self):
        if self.cancel.is_set():
            raise InterruptedError()
        if self.error:
            raise RuntimeError(self.error)
        if self._aborted.is_set():
            raise InterruptedError()

    def _fail(self, message):
        with self._lock:
            if self.error or self._aborted.is_set() or self.cancel.is_set():
                return
            self.error = message
            self.closed = True
        self._active.set()
        self._schedule_close()
        if self.on_error:
            try:
                self.on_error(message)
            except Exception:
                pass

    def _audio(self, data, frames, timing, status):
        chunk = bytes(data)
        message = ''
        with self._lock:
            if self.closed or self.cancel.is_set() or self._aborted.is_set():
                return
            if status:
                message = 'The microphone dropped audio. Recording stopped; your original text is preserved.'
            elif frames <= 0 or frames > FRAME_SAMPLES or len(chunk) != frames * 2:
                message = 'The microphone returned invalid PCM audio. Recording stopped.'
            elif self.recorded_frames + frames > MAX_SECONDS * SAMPLE_RATE:
                message = 'The 10-minute recording limit was reached. Stop and begin a new recording.'
            else:
                self.recorded_frames += frames
                self._pcm.append(chunk)
                try:
                    self.frames.put_nowait(chunk)
                except queue.Full:
                    message = 'The audio queue overflowed while the speech service was preparing or could not keep up. Recording stopped; try again when it is ready.'
        if message:
            self._fail(message)
            return
        try:
            self.on_level(pcm_level(chunk))
        except Exception:
            # A display callback must not stop capture or escape PortAudio.
            pass

    def start(self):
        with self._lock:
            if self._start_claimed:
                raise RuntimeError('The microphone collector has already been started.')
            if self.cancel.is_set() or self._aborted.is_set():
                self._start_finished.set()
                raise InterruptedError()
            if self.closed:
                self._start_finished.set()
                raise RuntimeError('Recording stopped before the microphone was ready. Nothing was inserted.')
            self._start_claimed = True
        try:
            self.check()
            import sounddevice as sd
            stream = sd.RawInputStream(
                samplerate=SAMPLE_RATE, blocksize=FRAME_SAMPLES, channels=1,
                dtype='int16', device=int(self.cfg.get('microphone', ''))
                if self.cfg.get('microphone') else None, callback=self._audio)
            with self._lock:
                self.stream = stream
                if self.closed:
                    raise RuntimeError('Recording stopped before the microphone was ready. Nothing was inserted.')
            self.check()
            self._worker = threading.Thread(target=self._deliver,
                                           name='MurMur-PCM-delivery', daemon=True)
            self._worker.start()
            self.started = time.monotonic()
            if self.closed:
                raise RuntimeError('Recording stopped before the microphone was ready. Nothing was inserted.')
            stream.start()
            self.check()
        except InterruptedError:
            self.abort()
            raise
        except Exception:
            if self.cancel.is_set() or self._aborted.is_set():
                self.abort()
                raise InterruptedError() from None
            message = ('Recording stopped before the microphone was ready. Nothing was inserted.'
                       if self.closed and not self.error else
                       'Could not open the microphone. Check the selected input device and microphone permissions.')
            self._fail(message)
            raise RuntimeError(self.error) from None
        finally:
            self._start_finished.set()

    def activate(self, on_frame=None):
        """Release preparation frames in capture order, without a second mic."""
        self.check()
        if on_frame is not None:
            self.on_frame = on_frame
        self._active.set()

    def _deliver(self):
        try:
            while not self.cancel.is_set() and not self._aborted.is_set() and not self.error:
                if not self._active.wait(.05):
                    continue
                if self.cancel.is_set() or self._aborted.is_set() or self.error:
                    return
                try:
                    chunk = self.frames.get(timeout=.05)
                except queue.Empty:
                    if self.closed:
                        return
                    continue
                if self.cancel.is_set() or self._aborted.is_set() or self.error:
                    return
                if self.on_frame:
                    try:
                        self.on_frame(chunk)
                    except Exception:
                        if not self.cancel.is_set() and not self._aborted.is_set():
                            self._fail('Could not send audio to the speech service. Recording stopped; your original text is preserved.')
                        return
        finally:
            self._finished.set()

    def close_input(self):
        """Seal capture promptly, including while startup is still preparing."""
        with self._lock:
            self.closed = True
        if self._start_claimed and not self._start_finished.is_set():
            # Do not close a stream while PortAudio.start is publishing it.
            # Capture is already sealed; cleanup runs once startup returns.
            self._schedule_close()
            return
        with self._lock:
            if self._close_claimed:
                return
            self._close_claimed = True
            stream = self.stream
            self.stream = None
        try:
            if stream:
                try:
                    stop = getattr(stream, 'stop', None) or getattr(stream, 'abort', None)
                    if stop:
                        stop()
                except Exception:
                    self._fail('Could not finish microphone capture. Your original text is preserved.')
                finally:
                    try:
                        stream.close()
                    except Exception:
                        self._fail('Could not close the microphone. Try selecting the input device again.')
        finally:
            # Claiming the stream is not proof that native disposal completed.
            # Only the cleanup owner can publish this completion barrier.
            self._input_closed.set()

    def request_stop(self):
        """Seal now; dispose the mic off the GUI thread, without canceling ASR.

        Preparation may still finish and drain the frames captured before this
        request. A collector that has not started must never open a mic later.
        """
        with self._lock:
            self.closed = True
            if not self._start_claimed:
                self._start_finished.set()
        self._schedule_close()

    def stop(self):
        self.request_stop()
        self._wait_finished(self._input_closed, INPUT_CLOSE_TIMEOUT,
                            'Microphone cleanup timed out. Your original text is preserved; try selecting the input device again.')
        if self._worker:
            self._wait_finished(self._finished, AUDIO_DELIVERY_TIMEOUT,
                                'Audio upload timed out. Your original text is preserved.')
        self.check()
        return self.pcm

    def _wait_finished(self, event, seconds, message):
        deadline = time.monotonic() + seconds
        while not event.is_set():
            self.check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._fail(message)
                break
            event.wait(min(.05, remaining))
        self.check()

    def _schedule_close(self):
        with self._lock:
            if self._close_scheduled:
                return
            self._close_scheduled = True
        def cleanup():
            self._start_finished.wait()
            self.close_input()
        threading.Thread(target=cleanup, name='MurMur-PCM-cleanup', daemon=True).start()

    def abort(self):
        """Nonblocking and idempotent; keep opt-in PCM for error recovery only."""
        already = self._aborted.is_set()
        self._aborted.set()
        self._active.set()
        with self._lock:
            self.closed = True
            if not self.cfg.get('save_audio'):
                self._pcm.clear()
            if not self._start_claimed:
                self._start_finished.set()
        # Queue.clear under its own lock avoids executing an overridden,
        # potentially blocking get() from a GUI-thread abort.
        with self.frames.mutex:
            self.frames.queue.clear()
            self.frames.not_full.notify_all()
        if not already:
            self._schedule_close()

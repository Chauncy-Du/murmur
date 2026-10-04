"""Isolated Windows Ask integration smoke, with scripted audio/model output.

Run the editor and assistant roles as separate processes. Focus/select the
editor with an external UI controller before the assistant countdown expires.
This helper never activates a target or synthesizes keyboard/mouse input.
Native UIA, monitoring, clipboard transactions and Ctrl+V are production code.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from murmur.paths import data_dir

EDITOR_TITLE = 'MurMur Ask Smoke Editor'
SAMPLE_TEXT = 'The meeting is scheduled for Friday.\nPlease bring the project notes.'
REPLACEMENT = 'The meeting is set for Friday. Please bring the project notes.'
DRAFT = '\nFollow-up: Please confirm that you can attend.'
ANSWER = 'The meeting is on Friday, and attendees should bring the project notes.'
COMMANDS = {
    'replace': 'Rewrite the selected text concisely.',
    'insert': 'Draft a short follow-up asking attendees to confirm they can attend.',
    'answer': 'What does the selected text say about the meeting?',
    'read_only': 'Rewrite the selected text concisely.',
    'changed': 'Rewrite the selected text concisely.',
}


def protected_profile_path(path):
    """Neither current nor former personal data may hold smoke artifacts."""
    path = Path(path).resolve()
    roots = (data_dir().resolve(),
             (Path(os.getenv('LOCALAPPDATA', str(Path.home()))) / 'MurMur').resolve())
    return any(path == root or path.is_relative_to(root) for root in roots)


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', choices=('editor', 'assistant'), required=True)
    parser.add_argument('--scenario', choices=tuple(COMMANDS), required=True)
    parser.add_argument('--output-dir', type=Path, required=True, help='An existing directory for public smoke evidence.')
    parser.add_argument('--data-dir', type=Path, help='An empty isolated assistant data directory; default creates one under output-dir.')
    parser.add_argument('--start-delay', type=float, default=8., help='Seconds to focus/select the editor before capture.')
    parser.add_argument('--record-seconds', type=float, default=1., help='Scripted recording duration.')
    parser.add_argument('--model-delay', type=float, default=1., help='Scripted model delay; increase for changed-target checks.')
    parser.add_argument('--lifetime', type=float, help='Assistant lifetime from launch, normally 20 seconds; editor waits for external close.')
    parser.add_argument('--screenshots', action='store_true', help='Capture public editor/result and hidden home/settings widgets.')
    parser.add_argument('--target-title', default=EDITOR_TITLE, help='Exact foreground title; override only for a dedicated public browser test window.')
    args = parser.parse_args()
    args.output_dir = args.output_dir.resolve()
    if protected_profile_path(args.output_dir):
        parser.error('Normal MurMur data cannot be used for smoke output')
    if not args.output_dir.is_dir():
        parser.error('--output-dir must already exist')
    if any(value < 0 for value in (args.start_delay, args.record_seconds, args.model_delay)):
        parser.error('Delays must be nonnegative')
    if args.lifetime is not None and args.lifetime <= 0:
        parser.error('--lifetime must be positive')
    if args.role == 'assistant':
        expected_finish = args.start_delay + args.record_seconds + args.model_delay
        if args.lifetime is None:
            args.lifetime = max(20., expected_finish + 6.)
        elif args.lifetime < expected_finish + 2.:
            parser.error('--lifetime must allow the countdown, recording, model delay and two seconds for results')
    if args.data_dir is not None:
        args.data_dir = args.data_dir.resolve()
        if protected_profile_path(args.data_dir):
            parser.error('Normal MurMur data cannot be used for this smoke')
        if args.data_dir.exists() and (not args.data_dir.is_dir() or any(args.data_dir.iterdir())):
            parser.error('--data-dir must be absent or an empty isolated directory')
    return args


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


class Evidence:
    def __init__(self, args):
        self.path = args.output_dir / f'{args.scenario}-{args.role}.json'
        self.started = time.monotonic()
        self.last_error_logged = 0.
        self.data = {
            'role': args.role, 'scenario': args.scenario, 'pid': os.getpid(),
            'created_at': timestamp(), 'editor_title': EDITOR_TITLE,
            'events': [], 'completed': False,
        }

    def save(self):
        self.data['updated_at'] = timestamp()
        self.data['elapsed_seconds'] = round(time.monotonic() - self.started, 3)
        temporary = self.path.with_suffix('.json.tmp')
        delays = (.02, .04, .08, .16)
        try:
            payload = json.dumps(self.data, ensure_ascii=False, indent=2)
            for attempt in range(len(delays) + 1):
                try:
                    temporary.write_text(payload, 'utf-8')
                    temporary.replace(self.path)
                    return True
                except PermissionError:
                    if attempt == len(delays):
                        raise
                    time.sleep(delays[attempt])
        except Exception as exc:
            # Evidence is secondary to the tested session. A sync client or
            # concurrent report reader must never prevent stop/quit callbacks.
            self.data['evidence_write_failures'] = self.data.get('evidence_write_failures', 0) + 1
            self.data['last_evidence_write_error'] = f'{type(exc).__name__}: {exc}'
            if time.monotonic() - self.last_error_logged >= 1.:
                self.last_error_logged = time.monotonic()
                try:
                    print('Smoke evidence write failed: ' + self.data['last_evidence_write_error'], file=sys.stderr, flush=True)
                except OSError:
                    pass
            return False

    def event(self, name, **values):
        self.data.update(values)
        self.data['events'].append({'name': name, 'elapsed_seconds': round(time.monotonic() - self.started, 3)})
        self.save()


def editor(args):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QPlainTextEdit, QVBoxLayout, QWidget
    import win32gui

    app = QApplication(sys.argv[:1])
    app.setStyle('Fusion')
    app.setApplicationName('MurMur Ask Smoke Editor')
    window = QMainWindow()
    window.setWindowTitle(EDITOR_TITLE)
    window.resize(700, 400)
    body = QWidget()
    layout = QVBoxLayout(body)
    note = QLabel('Public smoke text. Select text for replace/answer/read_only, or place the caret for insert.\n'
                  'For changed: edit or move the caret after the assistant reports context_captured.')
    note.setWordWrap(True)
    layout.addWidget(note)
    edit = QPlainTextEdit(SAMPLE_TEXT)
    edit.setAccessibleName('MurMur Ask Smoke Public Text')
    edit.setReadOnly(args.scenario == 'read_only')
    layout.addWidget(edit)
    window.setCentralWidget(body)
    evidence = Evidence(args)
    evidence.data.update(initial_text=SAMPLE_TEXT, read_only=edit.isReadOnly())

    def record(completed=False):
        cursor = edit.textCursor()
        evidence.data.update(
            text=edit.toPlainText(), selected_text=cursor.selectedText().replace('\u2029', '\n'),
            selection_start=cursor.selectionStart(), selection_end=cursor.selectionEnd(),
            hwnd=int(window.winId()), foreground_hwnd=int(win32gui.GetForegroundWindow()),
            received_replacement=edit.toPlainText() == REPLACEMENT,
            received_draft=DRAFT in edit.toPlainText(), completed=completed,
        )
        evidence.save()

    edit.textChanged.connect(record)
    edit.selectionChanged.connect(record)
    timer = QTimer(window)
    timer.timeout.connect(record)
    timer.start(500)
    app.aboutToQuit.connect(lambda: record(True))
    if args.screenshots:
        def capture():
            window.grab().save(str(args.output_dir / f'{args.scenario}-editor.png'))
        QTimer.singleShot(1200, capture)
        app.aboutToQuit.connect(capture)
    if args.lifetime:
        QTimer.singleShot(round(args.lifetime * 1000), app.quit)
    window.show()
    record()
    return app.exec()


def assistant(args):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    import win32clipboard
    import win32gui
    from murmur import app as app_module
    from murmur import storage as storage_module
    from murmur.assistant import AskResult
    from murmur.ui import STYLE

    evidence = Evidence(args)
    evidence.data.update(
        audio_mocked=True, model_mocked=True, synthetic_credential=True,
        normal_instance_contacted=False, ui_automation_in_helper=False, clipboard_text_recorded=False,
        limitations=[
            'Audio and model responses are scripted; no microphone or external API is exercised.',
            'The session starts through a countdown rather than a real Right Alt + Space gesture.',
            'External injected UI input is ignored by the production physical-input hooks.',
            'Paste sent is a native Ctrl+V request; editor evidence must confirm the received text.',
        ],
    )
    data_dir = args.data_dir or Path(tempfile.mkdtemp(prefix=f'ask-smoke-{args.scenario}-', dir=args.output_dir))
    evidence.data['data_dir'] = str(data_dir)
    fixture_key = 'smoke-only-not-a-real-api-key'

    def fixture_credential(name, value=None):
        if value is not None:
            raise RuntimeError('Smoke credentials cannot be written.')
        return fixture_key if name == 'ask_llm' else ''

    # The settings UI dynamically checks storage.credential presence. Patch it
    # inside this isolated process as well, so initializing that UI never reads
    # the real Windows credential vault. No credential is persisted.
    app_module.credential = fixture_credential
    storage_module.credential = fixture_credential

    class ScriptedRecorder:
        def __init__(self, cfg, on_partial, on_level, cancel):
            self.raw = ''; self.duration = 0.; self.error = ''; self.started = 0.
            self.on_partial = on_partial; self.on_level = on_level; self.cancel = cancel

        def start(self):
            if self.cancel.is_set():
                raise InterruptedError()
            self.started = time.monotonic()
            self.raw = COMMANDS[args.scenario]
            self.on_partial(self.raw)
            self.on_level(.12)

        def stop(self):
            if self.cancel.is_set():
                raise InterruptedError()
            self.duration = max(0., time.monotonic() - self.started)
            return self.raw

        def abort(self):
            if self.started:
                self.duration = max(0., time.monotonic() - self.started)

    model_call = {}

    def scripted_ask(instruction, context, cfg, cancel=None, usage_sink=None):
        model_call.update(instruction=instruction, context=context, called=True)
        if cancel is not None and cancel.wait(args.model_delay):
            raise InterruptedError()
        if cancel is None:
            time.sleep(args.model_delay)
        action = 'insert' if args.scenario == 'insert' else 'answer' if args.scenario == 'answer' else 'replace'
        return AskResult(action, DRAFT if action == 'insert' else ANSWER if action == 'answer' else REPLACEMENT)

    app_module.Recorder = ScriptedRecorder
    app_module.ask = scripted_ask
    app = QApplication(sys.argv[:1])
    app.setStyle('Fusion')
    app.setApplicationName('MurMur Ask Isolated Smoke Assistant')
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(STYLE)
    store = storage_module.Store(data_dir)
    store.config.update(
        demo=False, save_audio=False, startup=False, retention=0,
        ask_llm_url='https://smoke.example.com/v1', ask_llm_model='scripted-smoke-model',
        # Native monitoring stays enabled. Only the automation helper's global
        # shortcut actions are disabled; the countdown invokes start_ask().
        dictation_key='disabled', translation_key='disabled', selection_key='disabled', ask_key='disabled',
    )
    store.save()
    try:
        controller = app_module.Controller(app, store, listen=True)
    except Exception as exc:
        evidence.event('setup_failed', error=f'{type(exc).__name__}: {exc}', completed=True)
        store.db.close()
        return 2
    captured_session = None
    screenshot_done = False
    countdown_active = True

    def clipboard_metadata():
        return {
            'sequence': int(win32clipboard.GetClipboardSequenceNumber()),
            'owner_pid': int(app_module.windows.clipboard_owner_pid()),
            'transaction_pending': controller.clip_tx is not None,
        }

    def start():
        nonlocal captured_session, countdown_active
        countdown_active = False
        foreground = int(win32gui.GetForegroundWindow())
        title = win32gui.GetWindowText(foreground)
        evidence.data['foreground_hwnd_before'] = foreground
        evidence.data['foreground_title_before'] = title
        evidence.data['clipboard_before'] = clipboard_metadata()
        if title != args.target_title:
            evidence.event('setup_failed', error='The public smoke editor was not foreground at capture. No session was started.')
            return
        controller.start_ask()
        captured_session = controller.session
        if captured_session is None:
            evidence.event('setup_failed', error=controller.result_bubble.status.text())
            return
        try:
            context = captured_session.context
            target = captured_session.target
            evidence.event(
                'context_captured', context_state=context.state if context else 'unknown',
                captured_context=context.text if context else '', target_editable=bool(target and target.editable),
                target_hwnd=int(target.hwnd) if target else 0,
                target_uia_id=list(target.uia_id) if target else [],
                input_epoch_at_capture=controller.input_epoch, monitoring=controller.keys.monitoring,
                foreground_hwnd_after_capture=int(win32gui.GetForegroundWindow()),
            )
        finally:
            QTimer.singleShot(round(args.record_seconds * 1000), controller.stop)

    def screenshot_home():
        controller.window.grab().save(str(args.output_dir / f'{args.scenario}-home.png'))
        controller.window.navigate(3)
        if controller.window.settings_tabs.count() > 1:
            controller.window.settings_tabs.setCurrentIndex(1)
        QTimer.singleShot(250, screenshot_settings)

    def screenshot_settings():
        services = controller.window.settings_tabs.currentWidget()
        if hasattr(services, 'ensureWidgetVisible'):
            services.ensureWidgetVisible(controller.window.ask_llm_key, 0, 130)
        QTimer.singleShot(250, lambda: controller.window.grab().save(str(args.output_dir / f'{args.scenario}-settings.png')))

    def screenshot_result():
        controller.result_bubble.grab().save(str(args.output_dir / f'{args.scenario}-result.png'))

    def record(completed=False):
        nonlocal screenshot_done
        foreground = int(win32gui.GetForegroundWindow())
        if countdown_active and win32gui.GetWindowText(foreground) == args.target_title:
            # Identity-only requests let the cold COM worker initialize during
            # the countdown. No text is read before the real capture begins.
            warm_target = app_module.windows.target()
            evidence.data['uia_warmup_ready'] = bool(warm_target.uia_id)
        rows = store.rows()
        result_ready = bool(captured_session is not None and controller.session is None and rows)
        notice = controller.result_bubble.status.text()
        detail = controller.result_bubble.status.toolTip() or notice
        evidence.data.update(
            foreground_hwnd=foreground,
            foreground_preserved=foreground == evidence.data.get('foreground_hwnd_before'),
            phase=controller.session.phase if controller.session else 'idle',
            input_epoch=controller.input_epoch, monitoring=controller.keys.monitoring,
            model_call=dict(model_call), clipboard_after=clipboard_metadata(),
            result=controller.result_bubble.text, paste_notice=notice, paste_notice_detail=detail,
            paste_sent='paste sent' in notice.casefold(), capsule_status=controller.bubble.status.text(),
            capsule_notice=controller.bubble.status.toolTip(),
            result_visible=controller.result_bubble.isVisible(), preview_visible=controller.preview.isVisible(),
            history=rows, result_ready=result_ready, completed=completed,
        )
        editor_report = args.output_dir / f'{args.scenario}-editor.json'
        try:
            public_editor = json.loads(editor_report.read_text('utf-8'))
            evidence.data['editor_evidence'] = {name: public_editor.get(name) for name in
                ('pid', 'hwnd', 'text', 'read_only', 'received_replacement', 'received_draft', 'updated_at')}
        except (OSError, ValueError, TypeError):
            evidence.data['editor_evidence'] = None
        if result_ready and not any(event['name'] == 'result_ready' for event in evidence.data['events']):
            evidence.event('result_ready')
        else:
            evidence.save()
        if args.screenshots and result_ready and not screenshot_done:
            screenshot_done = True
            QTimer.singleShot(1000, screenshot_result)
            controller.window.navigate(0)
            QTimer.singleShot(250, screenshot_home)

    def finish():
        try:
            record(True)
        finally:
            timer.stop()
            try:
                controller.quit()
            finally:
                store.db.close()

    timer = QTimer(controller)
    timer.timeout.connect(record)
    timer.start(250)
    evidence.event('waiting_for_editor', start_delay=args.start_delay, lifetime=args.lifetime)
    QTimer.singleShot(round(args.start_delay * 1000), start)
    QTimer.singleShot(round(args.lifetime * 1000), finish)
    return app.exec()


def main():
    args = arguments()
    if sys.platform != 'win32':
        raise SystemExit('This helper tests native Windows UIA and clipboard integration.')
    return editor(args) if args.role == 'editor' else assistant(args)


if __name__ == '__main__':
    raise SystemExit(main())

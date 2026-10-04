from dataclasses import dataclass
import sys

from PySide6.QtCore import QObject, Signal


class HotkeyMachine:
    """Keyboard gesture arbitration; each Right Alt press has a stable token."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.down = set()
        self.active = None
        self.blocked = False
        self.external_ctrl_down = False
        self.gesture_serial = 0
        self.right_alt_gesture = 0
        self.event_gesture = 0
        self.last_source = ''
        self._dictation_trigger = None
        self._ask_keys = set()
        self._ask_gesture = 0
        self._ask_released = False

    @property
    def right_alt_enabled(self):
        # Right Alt can finish Ask even with dictation assigned elsewhere.
        return self.cfg.get('dictation_key') == 'right_alt' or self.cfg.get('ask_key', 'right_alt+space') != 'disabled'

    def chord(self, value):
        return value != 'disabled' and set(value.split('+')) == self.modifiers()

    def modifiers(self):
        names = {'left_alt':'alt', 'right_alt':'alt', 'left_ctrl':'ctrl', 'right_ctrl':'ctrl', 'left_shift':'shift', 'right_shift':'shift'}
        actual = {names.get(key, key) for key in self.down}
        if self.external_ctrl_down:
            actual.add('ctrl')
        return actual

    def block_altgr(self, source='ctrl'):
        self.event_gesture = self.right_alt_gesture if 'right_alt' in self.down else 0
        self.last_source = source
        if self.blocked:
            return None
        was = self.active
        self.blocked = True
        self.active = None
        self._dictation_trigger = None
        return 'cancel' if was else 'altgr'

    def feed(self, key, pressed):
        self.last_source = key
        self.event_gesture = self.right_alt_gesture if key == 'right_alt' or 'right_alt' in self.down else 0
        if pressed:
            if key in self.down:
                return None
            self.down.add(key)
            if key == 'right_alt':
                self.gesture_serial += 1
                self.right_alt_gesture = self.gesture_serial
                self.event_gesture = self.right_alt_gesture
            if key == 'esc':
                self.active = None
                self._dictation_trigger = None
                return 'cancel'
            if 'ctrl' in self.modifiers() and 'right_alt' in self.down:
                return self.block_altgr(key)
            if self.blocked or self._ask_keys:
                return None
            ask = self.cfg.get('ask_key', 'right_alt+space')
            # A forwarded ordinary Space/A may have replaced the selection.
            if (ask == 'right_alt+space' and key == 'space' and self.down == {'right_alt', 'space'}) or (ask == 'ctrl+shift+a' and key == 'a' and self.chord(ask)):
                self.active = 'ask'
                self._dictation_trigger = None
                self._ask_keys = set(self.down)
                self._ask_gesture = self.event_gesture
                self._ask_released = False
                return 'ask'
            unsafe_reverse_ask = ask == 'right_alt+space' and key == 'right_alt' and self.down == {'right_alt', 'space'}
            if not unsafe_reverse_ask:
                for name, event in [('selection_key', 'selection'), ('translation_key', 'translation')]:
                    if self.chord(self.cfg.get(name, 'disabled')):
                        self.active = event
                        return event
            dictation = self.cfg.get('dictation_key', 'disabled')
            if len(self.down) == 1 and ((dictation != 'disabled' and key in (dictation, 'f8')) or (key == 'right_alt' and self.right_alt_enabled)):
                self.active = 'dictation'
                self._dictation_trigger = key
                return 'pending'
            if self.active == 'dictation':
                self.active = None
                self._dictation_trigger = None
                return 'cancel'
        else:
            had = self.active
            self.down.discard(key)
            if not self.down and not self.external_ctrl_down:
                self.blocked = False
            if self._ask_keys:
                first_release = key in self._ask_keys and not self._ask_released
                if first_release:
                    self._ask_released = True
                    self.active = None
                    self.event_gesture = self._ask_gesture
                if not self._ask_keys.intersection(self.down):
                    self._ask_keys.clear()
                if first_release:
                    return 'ask_release'
                return None
            if had == 'dictation' and key == self._dictation_trigger:
                self.active = None
                self._dictation_trigger = None
                return 'release'
            if had == 'translation' and not self.chord(self.cfg.get('translation_key', 'disabled')):
                self.active = None
                return 'release'
            if had == 'selection' and not self.chord(self.cfg.get('selection_key', 'disabled')):
                self.active = None
        return None


@dataclass(frozen=True)
class NativeKeyDecision:
    key: str = ''
    pressed: bool = False
    event: str | None = None
    gesture: int = 0
    handled: bool = False
    suppress: bool = False
    # Ordered keydown replay for a reserved Alt becoming a native shortcut.
    replay: tuple = ()


class WindowsHotkeyArbiter:
    """Pure, testable decisions for the synchronous Windows hook filter."""

    REPLAY_TAG = 0x4D554D52
    PRESS = {0x100, 0x104}
    RELEASE = {0x101, 0x105}
    MODIFIERS = {'left_alt', 'right_alt', 'left_ctrl', 'right_ctrl', 'left_shift', 'right_shift'}

    def __init__(self, machine):
        self.machine = machine
        self.consumed = set()
        self.injected_ctrl = set()

    @staticmethod
    def key_name(data):
        vk = int(data.vkCode)
        names = {0xA4:'left_alt', 0xA5:'right_alt', 0xA2:'left_ctrl', 0xA3:'right_ctrl', 0xA0:'left_shift', 0xA1:'right_shift', 0x20:'space', 0x1B:'esc', 0x77:'f8', 0x78:'f9'}
        if vk in names:
            return names[vk]
        if vk in (0x11, 0x12):
            return ('right_' if int(data.flags) & 1 else 'left_') + ('ctrl' if vk == 0x11 else 'alt')
        if vk == 0x10:
            return 'right_shift' if int(getattr(data, 'scanCode', 0)) == 0x36 else 'left_shift'
        if 0x41 <= vk <= 0x5A:
            return chr(vk).lower()
        return f'vk_{vk}'

    def process(self, msg, data):
        if msg not in self.PRESS | self.RELEASE:
            return NativeKeyDecision()
        key = self.key_name(data)
        pressed = msg in self.PRESS
        flags = int(data.flags)
        injected = bool(flags & (0x10 | 0x02))
        replayed = int(getattr(data, 'dwExtraInfo', 0) or 0) == self.REPLAY_TAG
        if injected:
            if replayed or key not in ('left_ctrl', 'right_ctrl'):
                return NativeKeyDecision()
            # Windows may synthesize Ctrl for AltGr. Preserve that guard even
            # though ordinary injected input never triggers MurMur actions.
            if pressed:
                self.injected_ctrl.add(key)
            else:
                self.injected_ctrl.discard(key)
            self.machine.external_ctrl_down = bool(self.injected_ctrl)
            event = None
            replay = ()
            if pressed and 'right_alt' in self.machine.down:
                event = self.machine.block_altgr(key)
                if 'right_alt' in self.consumed:
                    self.consumed.discard('right_alt')
                    replay = ((0xA5, 1), (int(data.vkCode), flags & 1))
            if not self.machine.down and not self.machine.external_ctrl_down:
                self.machine.blocked = False
            return NativeKeyDecision(key, pressed, event, self.machine.event_gesture, False, bool(replay), replay)

        was_consumed = key in self.consumed
        event = self.machine.feed(key, pressed)
        token = self.machine.event_gesture
        replay = ()
        if pressed and key == 'right_alt' and self.machine.right_alt_enabled and not self.machine.blocked and self.machine.down == {'right_alt'}:
            self.consumed.add(key)
        if pressed and (event == 'ask' or (event == 'selection' and key == 'space' and 'right_alt' in self.consumed)):
            self.consumed.add(key)
        ordinary_shortcut = key not in self.MODIFIERS and key != 'esc' and event not in ('ask', 'selection') and not self.machine._ask_keys
        ctrl_bypass = key in ('left_ctrl', 'right_ctrl')
        if pressed and key != 'right_alt' and 'right_alt' in self.consumed and (ordinary_shortcut or ctrl_bypass):
            self.consumed.discard('right_alt')
            replay = ((0xA5, 1), (int(data.vkCode), flags & 1))
        suppress = was_consumed or key in self.consumed or bool(replay)
        if not pressed:
            self.consumed.discard(key)
        return NativeKeyDecision(key, pressed, event, token, True, suppress, replay)


def _replay_native_keydowns(keys):
    """Tagged ordered SendInput batch; it cannot re-enter arbitration."""
    import ctypes
    from pynput._util.win32 import INPUT, INPUT_union, KEYBDINPUT, SendInput
    batch = (INPUT * len(keys))(*[
        INPUT(type=INPUT.KEYBOARD, value=INPUT_union(ki=KEYBDINPUT(wVk=vk, dwFlags=extended, dwExtraInfo=WindowsHotkeyArbiter.REPLAY_TAG)))
        for vk, extended in keys
    ])
    if SendInput(len(batch), ctypes.byref(batch), ctypes.sizeof(INPUT)) != len(batch):
        raise RuntimeError('Keyboard shortcut passthrough is unavailable. Release modifier keys and try again.')


class Hotkeys(QObject):
    event = Signal(str)
    gesture = Signal(str, int)
    diagnostic = Signal(str)
    physical_input = Signal(str)

    def __init__(self, cfg):
        super().__init__()
        self.machine = HotkeyMachine(cfg)
        self.listener = None
        self.mouse_listener = None
        self.native = WindowsHotkeyArbiter(self.machine)
        self.physical_generation = 0
        self.cancel_generation = 0

    @property
    def input_guard(self):
        """Synchronous hook counters; queued Qt delivery cannot delay them."""
        return self.physical_generation, self.cancel_generation

    @property
    def monitoring(self):
        """Automatic insertion requires both physical-input hooks to be alive."""
        try:
            return bool(self.listener and self.mouse_listener and self.listener.is_alive() and self.mouse_listener.is_alive())
        except Exception:
            return False

    def start(self):
        try:
            self._start()
        except Exception:
            self.stop()
            raise RuntimeError('Keyboard or mouse monitoring could not start. Results will stay in Preview.') from None

    def _publish(self, name, pressed, result, gesture):
        if result in ('cancel', 'altgr'):
            self.cancel_generation += 1
        self.diagnostic.emit(f'{name} {"↓" if pressed else "↑"} / {result or "—"}')
        if result:
            self.event.emit(result)
            self.gesture.emit(result, gesture)
        elif pressed:
            ignored = set(WindowsHotkeyArbiter.MODIFIERS)
            if self.machine.cfg.get('dictation_key', 'disabled') != 'disabled':
                ignored.update(('f8', self.machine.cfg['dictation_key']))
            ignored.update(self.native.consumed)
            if name not in ignored:
                self._physical_input('keyboard')

    def _physical_input(self, kind):
        self.physical_generation += 1
        self.physical_input.emit(kind)

    def _start(self):
        from pynput import keyboard
        names = {keyboard.Key.alt_l:'left_alt', keyboard.Key.alt_r:'right_alt', keyboard.Key.alt_gr:'right_alt', keyboard.Key.ctrl_l:'left_ctrl', keyboard.Key.ctrl_r:'right_ctrl', keyboard.Key.shift_l:'left_shift', keyboard.Key.shift_r:'right_shift', keyboard.Key.space:'space', keyboard.Key.esc:'esc', keyboard.Key.f8:'f8', keyboard.Key.f9:'f9'}

        def handle(key, pressed):
            name = names.get(key, getattr(key, 'char', None) or str(key))
            result = self.machine.feed(name, pressed)
            self._publish(name, pressed, result, self.machine.event_gesture)

        def event_filter(msg, data):
            if sys.platform != 'win32':
                return not bool(data.flags & (0x10 | 0x02))
            decision = self.native.process(msg, data)
            if decision.handled or decision.event:
                self._publish(decision.key, decision.pressed, decision.event, decision.gesture)
            if decision.replay:
                try:
                    _replay_native_keydowns(decision.replay)
                except Exception:
                    self.diagnostic.emit('Keyboard shortcut passthrough is unavailable. Release modifier keys and try again.')
            if decision.suppress:
                self.listener.suppress_event()
            return False

        self.listener = keyboard.Listener(on_press=lambda k:handle(k, True), on_release=lambda k:handle(k, False), win32_event_filter=event_filter)
        self.listener.start()
        from pynput import mouse

        def mouse_filter(msg, data):
            if int(data.flags) & 0x03:
                return False
            if sys.platform != 'win32':
                return True
            if msg in (0x201, 0x204, 0x207, 0x20B):
                self._physical_input('mouse')
            return False

        self.mouse_listener = mouse.Listener(on_click=lambda x,y,button,pressed:self._physical_input('mouse') if pressed else None, win32_event_filter=mouse_filter)
        self.mouse_listener.start()

    def stop(self):
        for listener in (self.listener, self.mouse_listener):
            if listener:
                try:
                    listener.stop()
                except Exception:
                    pass

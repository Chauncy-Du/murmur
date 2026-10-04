"""Ask gesture ownership and native suppression, without injecting real keys."""
import copy
from types import SimpleNamespace

import pytest

from murmur.hotkeys import HotkeyMachine, Hotkeys, WindowsHotkeyArbiter
from murmur.storage import DEFAULTS


def machine(**values):
    cfg = copy.deepcopy(DEFAULTS)
    cfg['ask_key'] = 'right_alt+space'
    cfg.update(values)
    return HotkeyMachine(cfg)


def native_event(arbiter, vk, pressed=True, flags=0, extra=0, system=False):
    msg = (0x104 if pressed else 0x105) if system else (0x100 if pressed else 0x101)
    return arbiter.process(msg, SimpleNamespace(vkCode=vk, flags=flags, scanCode=0, dwExtraInfo=extra))


@pytest.mark.parametrize('first_release', ['right_alt', 'space'])
def test_ask_priority_one_release_and_stable_gesture(first_release):
    keys = machine()
    assert keys.feed('right_alt', True) == 'pending'
    token = keys.event_gesture
    assert keys.feed('space', True) == 'ask' and keys.event_gesture == token
    assert keys.feed('space', True) is None
    assert keys.feed(first_release, False) == 'ask_release' and keys.event_gesture == token
    other = 'space' if first_release == 'right_alt' else 'right_alt'
    assert keys.feed(other, False) is None
    assert keys.feed('right_alt', True) == 'pending' and keys.event_gesture == token + 1
    assert keys.feed('space', True) == 'ask'


def test_ask_does_not_rearm_until_original_keys_are_both_released():
    keys = machine()
    keys.feed('right_alt', True)
    keys.feed('space', True)
    assert keys.feed('space', False) == 'ask_release'
    assert keys.feed('space', True) is None
    assert keys.feed('space', False) is None
    assert keys.feed('right_alt', False) is None
    keys.feed('right_alt', True)
    assert keys.feed('space', True) == 'ask'


def test_left_alt_selection_and_unsafe_space_first_does_not_capture():
    keys = machine()
    keys.feed('left_alt', True)
    assert keys.feed('space', True) == 'selection'
    reverse = machine()
    assert reverse.feed('space', True) is None
    assert reverse.feed('right_alt', True) is None
    assert reverse.feed('right_alt', False) is None


def test_right_alt_remains_stop_gesture_when_dictation_disabled():
    keys = machine(dictation_key='disabled')
    assert keys.feed('right_alt', True) == 'pending'
    assert keys.feed('right_alt', False) == 'release'
    assert keys.feed('f8', True) is None


def test_non_right_alt_dictation_has_zero_token():
    keys = machine(dictation_key='f9')
    keys.feed('right_alt', True)
    keys.feed('right_alt', False)
    assert keys.feed('f9', True) == 'pending' and keys.event_gesture == 0
    assert keys.feed('f9', False) == 'release' and keys.event_gesture == 0


def test_alternative_chord_requires_modifier_first_and_no_altgr():
    keys = machine(ask_key='ctrl+shift+a')
    keys.feed('right_ctrl', True)
    keys.feed('left_shift', True)
    assert keys.feed('a', True) == 'ask' and keys.event_gesture == 0
    assert keys.feed('a', False) == 'ask_release'
    reverse = machine(ask_key='ctrl+shift+a')
    reverse.feed('a', True)
    reverse.feed('left_ctrl', True)
    assert reverse.feed('left_shift', True) is None


@pytest.mark.parametrize('release_order', [(0xA5, 0x20), (0x20, 0xA5)])
def test_native_ask_suppresses_both_key_pairs_and_repeat(release_order):
    arbiter = WindowsHotkeyArbiter(machine())
    first = native_event(arbiter, 0xA5, system=True)
    assert first.suppress and first.event == 'pending'
    second = native_event(arbiter, 0x20, system=True)
    assert second.suppress and second.event == 'ask' and second.gesture == first.gesture
    repeat = native_event(arbiter, 0x20)
    assert repeat.suppress and repeat.event is None
    release = native_event(arbiter, release_order[0], False, system=True)
    assert release.suppress and release.event == 'ask_release'
    assert native_event(arbiter, release_order[1], False, system=True).suppress
    assert not arbiter.consumed
    assert not native_event(arbiter, 0x20).suppress


def test_native_ordinary_space_is_never_delayed_or_suppressed():
    arbiter = WindowsHotkeyArbiter(machine())
    assert not native_event(arbiter, 0x20).suppress
    later = native_event(arbiter, 0xA5)
    assert later.event is None and not later.suppress
    assert not native_event(arbiter, 0xA5, False).suppress


@pytest.mark.parametrize('injected_flags', [0, 0x10, 0x02])
def test_ctrl_first_altgr_is_not_owned_or_suppressed(injected_flags):
    arbiter = WindowsHotkeyArbiter(machine())
    assert not native_event(arbiter, 0xA2, flags=injected_flags).suppress
    alt = native_event(arbiter, 0xA5)
    assert alt.event == 'altgr' and not alt.suppress
    assert native_event(arbiter, 0x20).event is None
    assert not native_event(arbiter, 0xA5, False).suppress
    native_event(arbiter, 0xA2, False, flags=injected_flags)
    native_event(arbiter, 0x20, False)
    assert not arbiter.machine.blocked


@pytest.mark.parametrize('injected_flags', [0, 0x10])
def test_ctrl_after_reserved_alt_replays_ordered_native_downs(injected_flags):
    arbiter = WindowsHotkeyArbiter(machine())
    assert native_event(arbiter, 0xA5).suppress
    ctrl = native_event(arbiter, 0xA2, flags=injected_flags)
    assert ctrl.event == 'cancel' and ctrl.suppress
    assert ctrl.replay == ((0xA5, 1), (0xA2, 0))
    assert not native_event(arbiter, 0xA5, flags=0x10, extra=arbiter.REPLAY_TAG).handled
    assert not native_event(arbiter, 0xA2, flags=0x10, extra=arbiter.REPLAY_TAG).handled
    assert not native_event(arbiter, 0xA5, False).suppress
    assert not native_event(arbiter, 0xA2, False, flags=injected_flags).suppress


def test_injected_hotkeys_cannot_trigger_or_modify_physical_gestures():
    arbiter = WindowsHotkeyArbiter(machine())
    assert not native_event(arbiter, 0xA5, flags=0x10).handled
    assert not native_event(arbiter, 0x20, flags=0x10).handled
    assert not arbiter.machine.down and arbiter.machine.gesture_serial == 0


def test_native_other_right_alt_shortcut_is_replayed_without_duplicates():
    arbiter = WindowsHotkeyArbiter(machine())
    native_event(arbiter, 0xA5)
    shortcut = native_event(arbiter, 0x58)
    assert shortcut.event == 'cancel' and shortcut.suppress
    assert shortcut.replay == ((0xA5, 1), (0x58, 0))
    assert not native_event(arbiter, 0x58, False).suppress
    assert not native_event(arbiter, 0xA5, False).suppress


def test_escape_does_not_replay_reserved_alt_into_alt_escape():
    arbiter = WindowsHotkeyArbiter(machine())
    native_event(arbiter, 0xA5)
    escape = native_event(arbiter, 0x1B)
    assert escape.event == 'cancel' and not escape.replay
    assert native_event(arbiter, 0xA5, False).suppress


def test_right_alt_selection_stays_native_safe_when_ask_disabled():
    arbiter = WindowsHotkeyArbiter(machine(ask_key='disabled'))
    assert native_event(arbiter, 0xA5).suppress
    selected = native_event(arbiter, 0x20)
    assert selected.event == 'selection' and selected.suppress
    assert native_event(arbiter, 0x20, False).suppress
    assert native_event(arbiter, 0xA5, False).suppress


def test_alternative_ask_suppresses_a_pair_but_preserves_ctrl_and_shift():
    arbiter = WindowsHotkeyArbiter(machine(ask_key='ctrl+shift+a'))
    assert not native_event(arbiter, 0xA2).suppress
    assert not native_event(arbiter, 0xA0).suppress
    assert native_event(arbiter, 0x41).suppress
    assert native_event(arbiter, 0x41, False).suppress
    assert not native_event(arbiter, 0xA2, False).suppress
    assert not native_event(arbiter, 0xA0, False).suppress


def test_filter_emits_immutable_gesture_before_native_suppression(monkeypatch):
    from pynput import keyboard, mouse
    import murmur.hotkeys as module
    listeners = []
    class Suppressed(Exception):
        pass
    class Listener:
        def __init__(self, **kwargs):
            self.options = kwargs
            listeners.append(self)
        def start(self): pass
        def stop(self): pass
        def is_alive(self): return True
        def suppress_event(self): raise Suppressed()
    monkeypatch.setattr(module.sys, 'platform', 'win32')
    monkeypatch.setattr(keyboard, 'Listener', Listener)
    monkeypatch.setattr(mouse, 'Listener', Listener)
    keys = Hotkeys(machine().cfg)
    events, gestures, physical = [], [], []
    keys.event.connect(events.append)
    keys.gesture.connect(lambda event, token: gestures.append((event, token)))
    keys.physical_input.connect(physical.append)
    keys.start()
    event_filter = listeners[0].options['win32_event_filter']
    def filtered(vk, msg):
        with pytest.raises(Suppressed):
            event_filter(msg, SimpleNamespace(vkCode=vk, flags=0, scanCode=0, dwExtraInfo=0))
    filtered(0xA5, 0x104)
    filtered(0x20, 0x104)
    filtered(0x20, 0x104)
    filtered(0xA5, 0x105)
    filtered(0x20, 0x105)
    assert events == ['pending', 'ask', 'ask_release']
    assert gestures == [('pending', 1), ('ask', 1), ('ask_release', 1)]
    assert not physical
    keys.stop()


def test_replay_uses_one_tagged_batch_without_real_sendinput(monkeypatch):
    import ctypes
    from pynput._util import win32
    from murmur.hotkeys import _replay_native_keydowns
    batches = []
    def send(count, pointer, size):
        assert size == ctypes.sizeof(win32.INPUT)
        entries = ctypes.cast(pointer, ctypes.POINTER(win32.INPUT))
        batches.append([(entries[i].value.ki.wVk, entries[i].value.ki.dwFlags, entries[i].value.ki.dwExtraInfo) for i in range(count)])
        return count
    monkeypatch.setattr(win32, 'SendInput', send)
    _replay_native_keydowns(((0xA5, 1), (0xA2, 0)))
    assert batches == [[(0xA5, 1, WindowsHotkeyArbiter.REPLAY_TAG), (0xA2, 0, WindowsHotkeyArbiter.REPLAY_TAG)]]


def test_synchronous_generations_precede_signal_slots():
    keys = Hotkeys(machine().cfg)
    physical, events, gestures = [], [], []
    keys.physical_input.connect(lambda kind: physical.append((kind, keys.input_guard)))
    keys.event.connect(lambda event: events.append((event, keys.input_guard)))
    keys.gesture.connect(lambda event, token: gestures.append((event, token, keys.input_guard)))
    keys._publish('x', True, None, 0)
    keys._physical_input('mouse')
    keys._publish('esc', True, 'cancel', 0)
    keys._publish('right_alt', True, 'altgr', 1)
    assert physical == [('keyboard', (1, 0)), ('mouse', (2, 0))]
    assert events == [('cancel', (2, 1)), ('altgr', (2, 2))]
    assert gestures == [('cancel', 0, (2, 1)), ('altgr', 1, (2, 2))]


def test_owned_shortcut_gestures_do_not_increment_physical_generation():
    keys = Hotkeys(machine().cfg)
    keys._publish('right_alt', True, 'pending', 1)
    keys._publish('space', True, 'ask', 1)
    keys.native.consumed.update({'right_alt', 'space'})
    keys._publish('space', True, None, 1)
    keys._publish('right_alt', False, 'ask_release', 1)
    assert keys.input_guard == (0, 0)
    keys._publish('x', True, None, 1)
    assert keys.input_guard == (1, 0)


def test_raw_mouse_filter_updates_guard_before_callback_dispatch(monkeypatch):
    from pynput import keyboard, mouse
    import murmur.hotkeys as module
    listeners = []
    class Listener:
        def __init__(self, **kwargs):
            self.options = kwargs
            listeners.append(self)
        def start(self): pass
        def stop(self): pass
        def is_alive(self): return True
    monkeypatch.setattr(module.sys, 'platform', 'win32')
    monkeypatch.setattr(keyboard, 'Listener', Listener)
    monkeypatch.setattr(mouse, 'Listener', Listener)
    keys = Hotkeys(machine().cfg)
    seen = []
    keys.physical_input.connect(lambda kind: seen.append((kind, keys.input_guard)))
    keys.start()
    filtered = listeners[1].options['win32_event_filter']
    assert filtered(0x201, SimpleNamespace(flags=0)) is False
    assert seen == [('mouse', (1, 0))]
    assert filtered(0x202, SimpleNamespace(flags=0)) is False
    assert filtered(0x204, SimpleNamespace(flags=1)) is False
    assert filtered(0x207, SimpleNamespace(flags=2)) is False
    assert keys.input_guard == (1, 0)
    keys.stop()

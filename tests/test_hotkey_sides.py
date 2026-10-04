import copy
from murmur.hotkeys import HotkeyMachine,Hotkeys
from murmur.storage import DEFAULTS


def test_releasing_one_control_keeps_other_control_for_altgr():
    machine=HotkeyMachine(copy.deepcopy(DEFAULTS))
    machine.feed('left_ctrl',True);machine.feed('right_ctrl',True)
    machine.feed('left_ctrl',False)
    assert machine.feed('right_alt',True)=='altgr'
    assert machine.feed('right_alt',False) is None


def test_releasing_one_shift_does_not_end_translation():
    machine=HotkeyMachine(copy.deepcopy(DEFAULTS))
    machine.feed('left_shift',True);machine.feed('right_shift',True)
    assert machine.feed('left_alt',True)=='translation'
    assert machine.feed('left_shift',False) is None
    assert machine.feed('right_shift',False)=='release'


def test_modifiers_normalize_to_configured_chord():
    cfg=copy.deepcopy(DEFAULTS);cfg['selection_key']='ctrl+shift+space'
    machine=HotkeyMachine(cfg)
    machine.feed('right_ctrl',True);machine.feed('left_shift',True)
    assert machine.feed('space',True)=='selection'


def test_disabled_dictation_also_disables_f8_backup():
    cfg=copy.deepcopy(DEFAULTS);cfg.update(dictation_key='disabled',ask_key='disabled')
    for key in ('f8','right_alt','f9'):
        machine=HotkeyMachine(cfg)
        assert machine.feed(key,True) is None and machine.feed(key,False) is None
    cfg['dictation_key']='f9';machine=HotkeyMachine(cfg)
    assert machine.feed('f8',True)=='pending' and machine.feed('f8',False)=='release'


def test_monitoring_requires_two_live_listeners_and_fails_closed():
    from types import SimpleNamespace
    keys=Hotkeys(copy.deepcopy(DEFAULTS));assert not keys.monitoring
    keys.listener=SimpleNamespace(is_alive=lambda:True);assert not keys.monitoring
    keys.mouse_listener=SimpleNamespace(is_alive=lambda:True);assert keys.monitoring
    keys.mouse_listener=SimpleNamespace(is_alive=lambda:False);assert not keys.monitoring
    def fail():raise RuntimeError('Stopped hook')
    keys.mouse_listener=SimpleNamespace(is_alive=fail);assert not keys.monitoring


def test_start_partial_failure_stops_keyboard_and_sanitizes_error(monkeypatch):
    from pynput import keyboard,mouse
    import pytest
    stopped=[]
    class Listener:
        def __init__(self,**kwargs):pass
        def start(self):pass
        def stop(self):stopped.append('keyboard')
        def is_alive(self):return True
    def fail(**kwargs):raise RuntimeError('private device or system detail')
    monkeypatch.setattr(keyboard,'Listener',Listener);monkeypatch.setattr(mouse,'Listener',fail)
    keys=Hotkeys(copy.deepcopy(DEFAULTS))
    with pytest.raises(RuntimeError,match='Results will stay in Preview') as error:keys.start()
    assert 'private' not in str(error.value) and stopped==['keyboard'] and not keys.monitoring


def test_f8_when_disabled_counts_as_physical_input(monkeypatch):
    from pynput import keyboard,mouse
    listeners=[]
    class Listener:
        def __init__(self,**kwargs):self.options=kwargs;listeners.append(self)
        def start(self):pass
        def stop(self):pass
        def is_alive(self):return True
    monkeypatch.setattr(keyboard,'Listener',Listener);monkeypatch.setattr(mouse,'Listener',Listener)
    cfg=copy.deepcopy(DEFAULTS);cfg['dictation_key']='disabled';keys=Hotkeys(cfg);inputs=[];actions=[]
    keys.physical_input.connect(inputs.append);keys.event.connect(actions.append);keys.start()
    listeners[0].options['on_press'](keyboard.Key.f8)
    assert inputs==['keyboard'] and not actions;keys.stop()

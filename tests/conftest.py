"""Unit tests require explicit synthetic microphone streams."""
import sys
from types import ModuleType
import pytest


def blocked_microphone(*args, **kwargs):
    raise AssertionError('A unit test attempted to open a real microphone. Install a synthetic stream fixture.')


# sounddevice initializes native PortAudio during import. Unit tests never need
# driver enumeration; install a test double before importing any test modules.
sounddevice=ModuleType('sounddevice')
for name in ('RawInputStream','InputStream','Stream','RawStream','rec'):
    setattr(sounddevice,name,blocked_microphone)
sounddevice.query_devices=lambda *args,**kwargs:[]
sys.modules['sounddevice']=sounddevice


@pytest.fixture(autouse=True)
def forbid_unmocked_microphone(monkeypatch):
    for name in ('RawInputStream', 'InputStream', 'Stream', 'RawStream', 'rec'):
        monkeypatch.setattr(sounddevice, name, blocked_microphone)
    monkeypatch.setattr(sounddevice, 'query_devices', lambda *args, **kwargs: [])


@pytest.fixture(autouse=True)
def dispose_offscreen_widgets_after_each_test():
    """Hidden windows still own live timers; destroy them between unit tests."""
    yield
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer
    from PySide6.QtWidgets import QApplication
    from shiboken6 import isValid

    app=QApplication.instance()
    if app is None or app.platformName()!='offscreen':
        return
    for widget in app.topLevelWidgets():
        if not isValid(widget):
            continue
        for timer in widget.findChildren(QTimer):
            timer.stop()
        widget.hide()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)

"""The recording indicator reflects audio frames, never autonomous animation."""
import os
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPropertyAnimation
from PySide6.QtTest import QTest
from PySide6.QtGui import QFontDatabase
from murmur.ui import Bubble, Wave


class Clock:
    def __init__(self):
        self.now = 0.

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True, scope='module')
def real_ui_font():
    app = QApplication.instance() or QApplication([])
    # Qt's offscreen Windows backend does not discover installed fonts itself.
    font = Path('C:/Windows/Fonts/segoeui.ttf')
    if font.is_file():
        QFontDatabase.addApplicationFont(str(font))
    return app


@pytest.fixture
def audio_wave():
    app = QApplication.instance() or QApplication([])
    clock = Clock()
    wave = Wave(clock=clock)
    wave.timer.stop()
    yield wave, clock
    wave.close()


def test_silence_and_no_input_do_not_animate(audio_wave):
    wave, clock = audio_wave
    wave.set_recording(True)
    initial = wave.grab().toImage()
    for frame in range(15):
        clock.now = frame * .1
        wave.feed_level(0.)
        wave.tick()
        assert wave.display_levels() == (0.,) * 9
        assert wave.grab().toImage() == initial
    clock.now += 2
    wave.tick()
    assert wave.grab().toImage() == initial


def test_last_nine_frames_show_their_actual_energy(audio_wave):
    wave, clock = audio_wave
    wave.set_recording(True)
    for frame in range(11):
        clock.now = frame * .1
        wave.feed_level(frame / 10)
    assert wave.display_levels() == pytest.approx(tuple(i / 10 for i in range(2, 11)))
    clock.now += .2
    wave.tick()
    assert wave.display_levels() == pytest.approx(tuple(i / 10 for i in range(2, 11)))


def test_missing_frames_fade_and_do_not_return_when_input_resumes(audio_wave):
    wave, clock = audio_wave
    wave.set_recording(True)
    wave.feed_level(.8)
    clock.now = .25
    assert wave.display_levels()[-1] == .8
    clock.now = .375
    wave.tick()
    assert wave.display_levels()[-1] == pytest.approx(.4)
    clock.now = .5
    wave.tick()
    assert wave.display_levels() == (0.,) * 9
    wave.feed_level(.2)
    assert wave.display_levels() == (0.,) * 8 + (.2,)


def test_stop_and_restart_clear_old_audio(audio_wave):
    wave, clock = audio_wave
    wave.set_recording(True)
    wave.feed_level(1.)
    wave.set_recording(False)
    assert wave.display_levels() == (0.,) * 9
    wave.feed_level(.7)
    wave.set_recording(True)
    assert wave.display_levels() == (0.,) * 9
    wave.feed_level(.3)
    wave.set_recording(True)
    assert wave.display_levels()[-1] == .3


def test_levels_are_bounded_and_nonfinite_is_silent(audio_wave):
    wave, clock = audio_wave
    wave.set_recording(True)
    for value in (-2, 2, float('nan'), float('inf')):
        wave.feed_level(value)
    assert wave.display_levels()[-4:] == (0., 1., 0., 0.)


def test_demo_is_explicit_and_switching_to_real_clears_simulation(audio_wave):
    wave, clock = audio_wave
    wave.set_recording(True, demo=True)
    clock.now = .11
    wave.tick()
    assert wave.display_levels()[-1] == Wave.DEMO_LEVELS[0]
    assert 'simulated' in wave.toolTip()
    wave.set_recording(True, demo=False)
    assert wave.display_levels() == (0.,) * 9
    clock.now += .2
    wave.tick()
    assert wave.display_levels() == (0.,) * 9


def test_bubble_repeated_recording_state_preserves_audio_history():
    app = QApplication.instance() or QApplication([])
    bubble = Bubble({'bubble_enter_motion':'none','bubble_exit_motion':'none'})
    bubble.wave.timer.stop()
    clock = Clock()
    bubble.wave._clock = clock
    bubble.state('录音', '00:01')
    bubble.wave.feed_level(.6)
    for _ in range(3):
        clock.now += .075
        bubble.state('录音', '00:02')
    assert bubble.wave.display_levels()[-1] == .6
    bubble.state('识别')
    assert bubble.wave.display_levels() == (0.,) * 9
    bubble.state('录音', demo=True)
    assert 'Demo' in bubble.status.text()
    assert 'simulated waveform' in bubble.toolTip()
    assert bubble.size().width() == 224 and bubble.size().height() == 44
    bubble.hide()


def test_bubble_lifecycle_keeps_processing_visible_without_audio_or_stop(monkeypatch):
    app = QApplication.instance() or QApplication([])
    bubble = Bubble({'bubble_enter_motion':'none','bubble_exit_motion':'none'})
    bubble.wave.timer.stop()
    clock = Clock()
    bubble.wave._clock = clock
    calls = []
    show, hide = bubble.show, bubble.hide
    monkeypatch.setattr(bubble, 'show', lambda: (calls.append('show'), show()))
    monkeypatch.setattr(bubble, 'hide', lambda: (calls.append('hide'), hide()))
    bubble.state('待机')
    assert not bubble.isVisible() and calls == []
    bubble.state('启动')
    assert bubble.isVisible() and not bubble.wave.active
    assert bubble.wave.display_levels() == (0.,) * 9
    assert not bubble.mic.isVisible() and not bubble.mic.isEnabled()
    assert bubble.progress.running
    bubble.state('启动')
    bubble.state('录音')
    assert bubble.isVisible() and bubble.wave.active
    bubble.wave.feed_level(.7)
    bubble.state('录音')
    assert bubble.wave.display_levels()[-1] == .7
    assert calls == ['show']
    cancelled = []
    bubble.cancel.connect(lambda: cancelled.append(True))
    for state in ('等待停止', '识别', '整理', 'stopping'):
        bubble.state(state)
        assert bubble.isVisible() and not bubble.wave.active
        assert bubble.progress.running and not bubble.progress.isVisible()
        assert bubble.percentage.isVisible()
        assert not bubble.mic.isVisible() and not bubble.mic.isEnabled()
        assert bubble.close.isEnabled()
        bubble.close.click()
        assert bubble.wave.display_levels() == (0.,) * 9
    assert len(cancelled) == 4
    assert calls == ['show']
    for state in ('完成', '失败', '待机', 'error', 'cancel'):
        bubble.state(state)
        assert not bubble.isVisible() and not bubble.wave.active
        assert not bubble.progress.running
        assert bubble.wave.display_levels() == (0.,) * 9
    assert calls == ['show', 'hide']
    bubble.state('Starting')
    assert bubble.isVisible() and not bubble.wave.active
    bubble.state('待机')
    assert calls == ['show', 'hide', 'show', 'hide']


@pytest.mark.parametrize('configured, expected', ((100, 200), (224, 224), (400, 360)))
def test_compact_bubble_clamps_size_and_exposes_truthful_demo(configured, expected):
    app = QApplication.instance() or QApplication([])
    bubble = Bubble({'bubble_enter_motion':'none','bubble_exit_motion':'none','bubble_width': configured})
    bubble.state('录音', '00:02', demo=True)
    app.processEvents()
    assert bubble.width() == expected and bubble.height() == 44
    assert bubble.mic.isVisible() and bubble.mic.isEnabled()
    assert 'Demo' in bubble.status.text() and 'Demo' in bubble.accessibleName()
    assert 'simulated waveform' in bubble.toolTip()
    assert bubble.close.geometry().left() < bubble.wave.geometry().left() < bubble.mic.geometry().left()
    bubble.state('识别', demo=True)
    assert 'Transcribe' in bubble.status.text()
    assert 'Demo' in bubble.status.text()
    assert bubble.percentage.text() == '0%'
    assert 'Not model-internal progress' in bubble.toolTip()
    assert bubble.wave.display_levels() == (0.,) * 9
    bubble.state('完成')


def test_processing_fallback_names_and_completed_step_percentage():
    app = QApplication.instance() or QApplication([])
    bubble = Bubble({'bubble_enter_motion':'none','bubble_exit_motion':'none'})
    bubble.state('识别')
    assert bubble.status.text() == 'Transcribe'
    assert bubble.percentage.text() == '0%'
    bubble.state('整理')
    assert bubble.status.text() == 'Organize'
    assert bubble.percentage.text() == '50%'
    assert bubble.progress.fraction == .5
    assert bubble.progress.animation.state() != QPropertyAnimation.Running
    bubble.state('完成')


def test_estimated_progress_advances_without_changing_actual_completed_steps():
    app = QApplication.instance() or QApplication([])
    bubble = Bubble({'bubble_enter_motion':'none','bubble_exit_motion':'none'})
    clock=Clock()
    bubble.progress._clock=clock
    bubble.state('识别')
    bubble.set_progress('Translate', 1, 2)
    assert bubble.status.text() == 'Translate'
    assert bubble.percentage.text() == '50%'
    for _ in range(4):
        bubble.state('整理')
        app.processEvents()
    assert bubble.status.text() == 'Translate'
    assert bubble.progress.completed_steps == 1
    assert bubble.progress.total_steps == 2
    clock.now=12
    bubble.progress.tick()
    first=bubble.progress.display_fraction
    assert .5<first<.98
    assert bubble.progress.fraction==.5
    clock.now=30
    bubble.state('整理')
    bubble.set_progress('Translate',1,2)
    bubble.progress.tick()
    assert first<bubble.progress.display_fraction<.98
    assert bubble.progress.completed_steps==1
    assert '1 of 2' in bubble.toolTip() and 'Estimated progress' in bubble.toolTip()
    assert 'Estimated progress' in bubble.accessibleName()
    bubble.state('待机')
    assert bubble.progress.fraction == 0
    assert not bubble.progress.running
    bubble.state('启动')
    assert bubble.status.text() == 'Starting' and bubble.percentage.text() == '0%'
    bubble.state('待机')


@pytest.mark.parametrize('step', ('Transcribe', 'Polish', 'Translate', 'Respond', 'Refine', 'Summarize', 'Expand', 'Edit'))
def test_processing_labels_fit_minimum_capsule_and_keep_cancel(step):
    app = QApplication.instance() or QApplication([])
    bubble = Bubble({'bubble_enter_motion':'none','bubble_exit_motion':'none','bubble_width': 156})
    bubble.state('识别')
    bubble.set_progress(step, 1, 2)
    app.processEvents()
    assert bubble.status.fontMetrics().horizontalAdvance(step) <= bubble.status.width()
    assert bubble.status.geometry().right() < bubble.percentage.geometry().left()
    assert bubble.close.geometry().right() < bubble.status.geometry().left()
    assert bubble.width() == 200 and bubble.height() == 44
    assert not bubble.mic.isVisible()
    assert bubble.close.isEnabled()
    assert bubble.windowFlags() & Qt.WindowDoesNotAcceptFocus
    assert bubble.testAttribute(Qt.WA_ShowWithoutActivating)
    cancelled = []
    bubble.cancel.connect(lambda: cancelled.append(True))
    bubble.close.click()
    assert cancelled == [True]
    bubble.state('待机')


def test_fraction_clamps_and_fill_covers_capsule_height_under_content():
    app = QApplication.instance() or QApplication([])
    bubble = Bubble({'bubble_enter_motion':'none','bubble_exit_motion':'none'})
    bubble.progress._clock=Clock()
    bubble.state('识别')
    bubble.set_progress('Transcribe', -5, 2)
    assert bubble.percentage.text() == '0%'
    bubble.set_progress('Polish', 1, 2)
    QTest.qWait(220)
    image = bubble.grab().toImage()
    dpr = image.devicePixelRatio()
    pixel = lambda x, y: image.pixelColor(round(x * dpr), round(y * dpr)).name()
    assert pixel(44, 29) == '#514269'
    assert pixel(130, 29) == '#242128'
    assert image.pixelColor(0, 0).alpha() == 0
    bubble.set_progress('Polish', 20, 2)
    assert bubble.percentage.text() == '100%'
    bubble.set_progress('Transcribe', 0, 0)
    assert bubble.percentage.text() == '0%'
    bubble.state('录音')
    assert not bubble.percentage.isVisible() and not bubble.progress.running
    assert bubble.progress.fraction == 0
    bubble.state('待机')


@pytest.mark.parametrize('kind',('Translation','Ask Anything'))
@pytest.mark.parametrize('width',(200,224,360))
def test_advanced_recording_modes_show_distinct_icon_and_fit(kind,width):
    app=QApplication.instance() or QApplication([])
    bubble=Bubble({'bubble_enter_motion':'none','bubble_exit_motion':'none','bubble_width':width})
    clock=Clock();bubble.wave._clock=clock;bubble.wave.timer.stop()
    bubble.set_session_kind(kind)
    bubble.state('录音','00:02')
    bubble.wave.feed_level(.7)
    app.processEvents()
    assert bubble.mode_mark.isVisible() and not bubble.mode_mark.pixmap().isNull()
    assert kind in bubble.accessibleName() and kind in bubble.toolTip()
    assert bubble.wave.color!='#ddd3f6'
    assert bubble.status.fontMetrics().horizontalAdvance('00:02')<=bubble.status.width()
    assert bubble.close.geometry().right()<bubble.mode_mark.geometry().left()
    assert bubble.wave.geometry().right()<bubble.status.geometry().left()
    assert bubble.status.geometry().right()<bubble.mic.geometry().left()
    levels=bubble.wave.display_levels()
    bubble.set_session_kind(kind)
    bubble.state('录音','00:03')
    assert bubble.wave.display_levels()==levels
    bubble.state('整理')
    bubble.set_progress('Respond' if kind=='Ask Anything' else 'Translate',1,2)
    app.processEvents()
    assert bubble.mode_mark.isVisible() and bubble.close.isEnabled()
    assert bubble.status.fontMetrics().horizontalAdvance(bubble.status.text())<=bubble.status.width()
    bubble.state('待机');bubble.set_session_kind('')
    assert not bubble.mode_mark.isVisible() and bubble.wave.color=='#ddd3f6'

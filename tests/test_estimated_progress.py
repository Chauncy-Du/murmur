import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from murmur.ui import Bubble


@pytest.fixture
def bubble():
    app=QApplication.instance() or QApplication([])
    value=Bubble({})
    value.progress.timer.stop()
    clock=[0.]
    value.progress._clock=lambda:clock[0]
    value.state('Transcribing')
    yield value,clock
    value.state('idle')


def test_estimates_advance_and_step_updates_never_rewind(bubble):
    value,clock=bubble
    value.set_progress('Transcribe',0,2)
    clock[0]=10;value.progress.tick()
    first=value.progress.display_fraction
    assert 0<first<.45 and value.percentage.text().endswith('%') and '~' not in value.percentage.text()
    value.set_progress('Polish',1,2)
    assert value.progress.display_fraction>=first
    clock[0]=30;value.progress.tick()
    second=value.progress.display_fraction
    assert .5<second<.98
    value.set_progress('Polish',1,2)
    value.set_progress('Polish',0,2)  # A stale stage report cannot regress progress.
    assert value.progress.display_fraction==second
    clock[0]=60;value.progress.tick()
    assert second<value.progress.display_fraction<.98
    assert value.progress.completed_steps==1
    value.set_progress('Polish',2,2)
    assert value.progress.display_fraction==1 and value.percentage.text()=='100%'


@pytest.mark.parametrize('step',('Transcribe','Polish','Translate','Respond'))
def test_long_wait_never_completes_and_remains_active(bubble,step):
    value,clock=bubble
    value.set_progress(step,0,1)
    for seconds in (1,10,60,600,3600,86400):
        clock[0]=seconds;value.progress.tick()
        assert value.progress.percentage<=98 and value.progress.estimated
        assert value.progress.fraction==0 and value.progress.completed_steps==0
    assert value.progress.running and value.progress.timer.isActive()
    assert 'Estimated progress' in value.toolTip()


@pytest.mark.parametrize('state',('idle','Failed','Recording'))
def test_cancel_error_and_recording_stop_estimate_and_reset(bubble,state):
    value,clock=bubble
    value.set_progress('Respond',0,1)
    clock[0]=30;value.progress.tick()
    assert value.progress.display_fraction>0
    value.state(state)
    assert not value.progress.running and not value.progress.timer.isActive()
    assert value.progress.display_fraction==0
    clock[0]=100;value.progress.tick()
    assert value.progress.display_fraction==0 and not value.percentage.isVisible()
    value.state('Transcribing')
    assert value.progress.display_fraction==0


def test_real_qt_timer_updates_estimate_label(bubble):
    value,clock=bubble
    value.set_progress('Translate',0,1)
    before=value.percentage.text()
    clock[0]=10
    QTest.qWait(130)
    assert value.percentage.text()!=before
    assert value.percentage.text()==f'{value.progress.percentage}%'


def test_start_stop_and_transcribe_transitions_do_not_rewind(bubble):
    value,clock=bubble
    value.state('idle');value.state('Starting')
    clock[0]=8;value.progress.tick()
    first=value.progress.display_fraction
    assert 0<first<=.12
    value.state('Stopping')
    assert value.progress.display_fraction>=first
    value.state('Transcribing')
    assert value.progress.display_fraction>=first
    clock[0]=20;value.progress.tick()
    assert value.progress.display_fraction>first


def test_polish_display_phases_are_sequential_and_repeat_updates_preserve_timing(bubble):
    value,clock=bubble
    value.set_progress('Polish',1,2)
    assert value.status.text()=='Organize'
    for seconds,label in ((12,'Refine'),(38,'Review'),(65,'Review'),(600,'Review')):
        clock[0]=seconds
        value.set_progress('Polish',1,2)
        value.progress.tick()
        assert value.status.text()==label
        assert value.percentage.text()==f'{value.progress.percentage}%'
        assert value.progress.completed_steps==1 and value.progress.fraction==.5
        assert value._progress_step=='Polish'
    assert 'estimated UI phases of one model request' in value.toolTip()
    value.set_progress('Polish',2,2)
    assert value.percentage.text()=='100%'
    value.state('idle');value.state('Refining');value.set_progress('Polish',1,2)
    assert value.status.text()=='Organize'


@pytest.mark.parametrize('step,labels',(('Translate',('Translate','Refine','Review')),('Respond',('Understand','Compose','Review'))))
def test_translation_and_ask_use_task_specific_waiting_phases(bubble,step,labels):
    value,clock=bubble
    value.set_progress(step,1,2)
    for seconds,label in zip((0,12,38),labels):
        clock[0]=seconds;value.progress.tick()
        assert value.status.text()==label
        assert value._progress_step==step

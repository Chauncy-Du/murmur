import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from murmur.ui import Bubble,Wave,ResultBubble,STYLE

_APPLICATION=QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def app():
    application=QApplication.instance() or QApplication([])
    for name in ('segoeui.ttf','segoeuib.ttf','msyh.ttc'):
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+name)
    application.setStyleSheet(STYLE)
    return application


@pytest.mark.parametrize('kind',['','Translation','Ask Anything'])
@pytest.mark.parametrize('height',[40,44,64])
def test_all_sizes_keep_concentric_actions_and_fixed_bar_pitch(kind,height):
    counts=[]
    for width in (200,224,360):
        bubble=Bubble({'bubble_width':width,'bubble_height':height,'bubble_enter_motion':'none','bubble_exit_motion':'none'})
        bubble.set_session_kind(kind);bubble.state('录音','00:02');QApplication.processEvents()
        widgets=[w for w in (bubble.close,bubble.mode_mark,bubble.wave,bubble.status,bubble.mic) if w.isVisible()]
        assert all(a.geometry().right()<b.geometry().left() for a,b in zip(widgets,widgets[1:]))
        assert abs(bubble.close.x()+bubble.close.width()/2-height/2)<=.5
        assert abs(bubble.mic.x()+bubble.mic.width()/2-(width-height/2))<=.5
        assert bubble.wave.height()==28
        positions=bubble.wave.bar_positions();counts.append(len(positions))
        assert all(b-a==Wave.BAR_PITCH for a,b in zip(positions,positions[1:]))
        bubble.hide()
    assert counts[0]<counts[1]<counts[2]


@pytest.mark.parametrize('style',Wave.STYLES)
@pytest.mark.parametrize('width',[12,40,200])
def test_each_style_uses_real_input_and_silence_then_fades(style,width):
    clock=[0.];wave=Wave(clock=lambda:clock[0]);wave.timer.stop()
    wave.setFixedSize(width,28)
    wave.set_style(style);wave.set_recording(True)
    assert not any(wave.rendered_levels())
    silent=wave.grab().toImage()
    for value in (.1,.3,.5,.7,.9,.7,.5,.3,.1):wave.feed_level(value)
    assert wave.grab().toImage()!=silent
    clock[0]=1.;assert not any(wave.rendered_levels())
    assert wave.grab().toImage()==silent
    wave.close()


def test_result_dismissal_shares_the_outer_corner_center():
    result=ResultBubble({'bubble_enter_motion':'none','bubble_exit_motion':'none'})
    result.show_result('完整结果。');QApplication.processEvents()
    rect=result.dismiss_button.geometry()
    assert rect.x()+rect.width()/2==result.width()-30
    assert rect.y()+rect.height()/2==30
    result.hide()


@pytest.mark.parametrize('height',[40,44,64])
@pytest.mark.parametrize('kind',['','Translation','Ask Anything'])
def test_progress_percentage_and_stage_fit_with_room_at_right_edge(height,kind):
    bubble=Bubble({'bubble_width':200,'bubble_height':height,'bubble_enter_motion':'none','bubble_exit_motion':'none','bubble_state_motion':False})
    bubble.set_session_kind(kind);bubble.state('Refining')
    bubble.set_progress('Respond',1,2);bubble.progress._set_display_fraction(.98)
    QApplication.processEvents()
    assert bubble.percentage.text()=='98%'
    assert bubble.percentage.fontMetrics().horizontalAdvance('100%')<=bubble.percentage.width()
    assert bubble.status.fontMetrics().horizontalAdvance(bubble.status.text())<=bubble.status.width()
    assert bubble.width()-bubble.percentage.geometry().right()-1>=12
    assert bubble.status.geometry().right()<bubble.percentage.geometry().left()
    assert bubble.close.geometry().right()<bubble.status.geometry().left()
    bubble.set_progress('Respond',2,2);QApplication.processEvents()
    assert bubble.percentage.text()=='100%'
    bubble.state('Recording','00:02');QApplication.processEvents()
    assert bubble.mode_mark.isVisible()==bool(kind)
    assert abs(bubble.mic.x()+bubble.mic.width()/2-(200-height/2))<=.5
    bubble.hide()

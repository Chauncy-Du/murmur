import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtCore import Qt,QRect,QPoint,QSize,QCoreApplication,QEvent
from PySide6.QtGui import QCursor,QFontDatabase,QBitmap,QRegion
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from murmur.ui import Bubble,ResultBubble,STYLE
from murmur.bubble_motion import placement
from murmur.storage import validated_config,Store
from murmur.dashboard import MainWindow
from murmur.settings_page import preview_bubble


@pytest.fixture(autouse=True)
def application():
    app=QApplication.instance() or QApplication([])
    for name in ('segoeui.ttf','segoeuib.ttf','msyh.ttc'):
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+name)
    app.setStyleSheet(STYLE)
    return app


@pytest.mark.parametrize('style',['pop','slide','fade','none'])
def test_entry_finishes_at_configured_geometry_without_activating(style,monkeypatch):
    bubble=Bubble({'bubble_enter_motion':style,'bubble_exit_motion':'none'})
    monkeypatch.setattr(bubble,'activateWindow',lambda:pytest.fail('Entry activated window'))
    bubble.position();target=QRect(bubble.geometry());bubble.state('录音','00:03')
    assert bubble.isVisible() and bubble.windowFlags()&Qt.WindowDoesNotAcceptFocus
    if style=='none':assert bubble.motion.enter is None
    else:
        animation=bubble.motion.enter;animation.pause();animation.setCurrentTime(110)
        if style=='pop':
            assert bubble.geometry()==target
            assert bubble.motion.entry_frame.body_rect().width()<target.width()
        animation.setCurrentTime(240)
    assert bubble.geometry()==target and bubble.windowOpacity()==1.
    bubble.hide()


@pytest.mark.parametrize('style',['burst','pop','slide','fade','none'])
def test_exit_is_inert_and_old_animation_cannot_close_new_session(style):
    bubble=Bubble({'bubble_enter_motion':'none','bubble_exit_motion':style})
    bubble.position();bubble.state('录音');bubble.hide()
    assert not bubble.isVisible()
    ghost=bubble.motion.ghost
    if style=='none':assert ghost is None
    else:
        assert ghost.isVisible() and ghost.windowFlags()&Qt.WindowTransparentForInput
        animation=bubble.motion.exit;animation.pause();animation.setCurrentTime(110)
        assert 0<ghost.alpha<1
    bubble.state('录音')
    assert bubble.motion.ghost is None and bubble.motion.exit is None and bubble.isVisible()
    QTest.qWait(260);assert bubble.isVisible()
    bubble.hide()


def test_liquid_pop_releases_from_edge_and_keeps_controls_stable():
    bubble=Bubble({'bubble_enter_motion':'pop','bubble_exit_motion':'none'})
    bubble.position();target=QRect(bubble.geometry());bubble.state('录音','00:03')
    animation=bubble.motion.enter;animation.pause();frame=bubble.motion.entry_frame
    assert frame.windowFlags()&Qt.WindowTransparentForInput
    assert frame.windowFlags()&Qt.WindowDoesNotAcceptFocus
    initial=frame.body_rect()
    assert initial.center().y()==frame.edge and initial.height()<target.height()*.1
    controls=QRect(bubble.mic.geometry())
    animation.setCurrentTime(round(animation.duration()*.50))
    stretched=frame.body_rect()
    assert stretched.height()>target.height() and stretched.center().y()<frame.edge
    assert frame.surface_path().boundingRect().bottom()>stretched.bottom()
    animation.setCurrentTime(round(animation.duration()*.70))
    assert frame.body_rect().width()>target.width()
    assert bubble.mic.geometry()==controls and bubble.geometry()==target
    animation.setCurrentTime(animation.duration())
    assert bubble.motion.entry_frame is None and bubble.windowOpacity()==1.
    bubble.hide()


def test_liquid_pop_cancellation_and_restart_remove_old_surface():
    bubble=Bubble({'bubble_enter_motion':'pop','bubble_exit_motion':'none'})
    bubble.state('录音');old=bubble.motion.entry_frame
    bubble.motion.enter.pause();bubble.motion.enter.setCurrentTime(90)
    bubble.hide()
    assert not old.isVisible() and bubble.motion.entry_frame is None
    assert bubble.motion.enter is None and bubble.windowOpacity()==1.
    bubble.state('录音');new=bubble.motion.entry_frame
    assert new is not old and new.isVisible()
    bubble.motion.stop_enter()
    assert not new.isVisible() and bubble.motion.entry_frame is None
    bubble.hide()


def test_liquid_contact_edge_fades_without_fading_settled_body():
    bubble=Bubble({'bubble_enter_motion':'pop','bubble_exit_motion':'none'})
    bubble.state('录音');bubble.motion.enter.pause();frame=bubble.motion.entry_frame
    frame.set_progress(.50)
    image=frame.grab().toImage();dpr=image.devicePixelRatio()
    x=round(frame.target.center().x()*dpr)
    def alpha(y):return image.pixelColor(x,round(y*dpr)).alpha()
    assert alpha(frame.edge-2)<alpha(frame.edge-8)<alpha(frame.body_rect().center().y())
    frame.set_progress(1.)
    settled=frame.grab().toImage()
    assert settled.pixelColor(x,round(frame.target.center().y()*dpr)).alpha()==255
    bubble.hide()


@pytest.mark.parametrize('kind',[Bubble,ResultBubble])
def test_default_burst_finishes_and_removes_inert_surface(kind):
    cfg=validated_config({})
    assert cfg['bubble_enter_motion']=='pop' and cfg['bubble_exit_motion']=='burst'
    bubble=kind(dict(cfg,bubble_enter_motion='none'))
    if kind is Bubble:bubble.state('录音')
    else:bubble.show_result('A completed result.')
    bubble.hide();frame=bubble.motion.ghost;animation=bubble.motion.exit
    animation.pause();animation.setCurrentTime(round(animation.duration()*.50))
    assert frame._progress==pytest.approx(.5) and 0<frame.alpha<1
    assert frame.windowFlags()&Qt.WindowTransparentForInput
    animation.setCurrentTime(animation.duration())
    assert bubble.motion.ghost is None and bubble.motion.exit is None
    assert not bubble.isVisible()


def test_burst_splash_uses_bounded_cached_seeds_and_disperses_outside_shell():
    bubble=Bubble({'bubble_enter_motion':'none','bubble_exit_motion':'burst'})
    bubble.state('录音');bubble.hide();animation=bubble.motion.exit;animation.pause()
    frame=bubble.motion.ghost
    seeds=frame.particles;paths=tuple(item[0] for item in frame.shards)
    assert len(seeds)==20 and len(paths)==6
    frame.set_progress(.35);image=frame.grab().toImage()
    bounds=QRegion(QBitmap.fromImage(image.createAlphaMask())).boundingRect()
    assert bounds.top()<frame.target.top()*image.devicePixelRatio()-3
    frame.set_progress(.60);frame.grab()
    assert frame.particles is seeds and all(a is b[0] for a,b in zip(paths,frame.shards))
    frame.set_progress(1.)
    assert QRegion(QBitmap.fromImage(frame.grab().toImage().createAlphaMask())).isEmpty()
    animation.setCurrentTime(animation.duration())


@pytest.mark.parametrize('cfg',[{'bubble_position':'top'},{'bubble_follow_mouse':True}])
def test_liquid_pop_non_bottom_placement_has_local_origin(cfg):
    bubble=Bubble(dict(cfg,bubble_enter_motion='pop',bubble_exit_motion='none'))
    bubble.state('录音');frame=bubble.motion.entry_frame
    assert 0<=frame.edge-frame.target.bottom()<=21
    bubble.hide()


def test_state_and_voice_motion_switches_are_independent():
    bubble=Bubble({'bubble_enter_motion':'none','bubble_state_motion':False,'bubble_wave_motion':False})
    bubble.state('录音');assert bubble.wave.active and not bubble.wave.timer.isActive()
    bubble.state('识别');assert bubble._state_animation is None
    bubble.cfg['bubble_state_motion']=True;bubble.state('整理')
    assert bubble._state_animation is not None and bubble.contents.graphicsEffect().opacity()<1
    bubble._state_animation.setCurrentTime(240)
    assert bubble.contents.graphicsEffect() is None
    bubble.state('完成')


@pytest.mark.parametrize('anchor',['top','bottom','left','right','top-left','top-right','bottom-left','bottom-right'])
def test_all_anchors_clamp_to_negative_origin_screen(anchor,monkeypatch):
    rect=QRect(-1200,-100,1000,700)
    class Screen:
        def availableGeometry(self):return rect
    monkeypatch.setattr(QApplication,'screens',lambda:[Screen()])
    cfg={'bubble_position':anchor,'bubble_offset':24}
    positioned=placement(cfg,QSize(224,44))
    assert rect.contains(positioned)
    if 'left' in anchor:assert positioned.left()==rect.left()+24
    if 'right' in anchor:assert positioned.right()==rect.right()-24
    if anchor.startswith('top'):assert positioned.top()==rect.top()+24
    if anchor.startswith('bottom'):assert positioned.bottom()==rect.bottom()-24
    assert rect.contains(placement(dict(cfg,bubble_offset=9000),QSize(224,44)))


def test_follow_uses_pointer_display_flips_at_edges_and_pauses_for_click(monkeypatch):
    rect=QRect(-800,0,800,600)
    class Screen:
        def availableGeometry(self):return rect
    screen=Screen()
    monkeypatch.setattr(QApplication,'screens',lambda:[screen])
    monkeypatch.setattr(QApplication,'screenAt',lambda point:screen)
    pointer=QPoint(-10,590)
    monkeypatch.setattr(QCursor,'pos',lambda:pointer)
    cfg={'bubble_follow_mouse':True,'bubble_cursor_offset':24,'bubble_enter_motion':'none','bubble_exit_motion':'none'}
    positioned=placement(cfg,QSize(224,44))
    assert rect.contains(positioned) and positioned.right()<pointer.x() and positioned.bottom()<pointer.y()
    bubble=Bubble(cfg);bubble.state('录音')
    pointer=bubble.geometry().center();before=QRect(bubble.geometry())
    bubble.motion.track();assert bubble.geometry()==before
    pointer=QPoint(-700,100)
    bubble.motion.track();assert bubble.geometry()!=before
    bubble.hide();assert not bubble.motion.follow.isActive()


def test_preferences_validate_and_round_trip_without_changing_other_settings(tmp_path):
    cfg=validated_config({'bubble_width':340,'bubble_height':60,'bubble_result_width':620,
        'bubble_follow_mouse':True,'bubble_enter_motion':'fade','bubble_exit_motion':'none',
        'bubble_state_motion':False,'bubble_wave_motion':False,'bubble_motion_duration':420,'bubble_position':'top-right'})
    store=Store(tmp_path);store.config.update(cfg);store.save();store.db.close()
    reopened=Store(tmp_path)
    assert reopened.config['bubble_width']==340 and reopened.config['bubble_follow_mouse']
    assert reopened.config['bubble_state_motion'] is False and reopened.config['bubble_position']=='top-right'
    invalid=validated_config({'bubble_motion_duration':True,'bubble_height':999,'bubble_enter_motion':'unknown','bubble_follow_mouse':'yes'})
    assert invalid['bubble_motion_duration']==240 and invalid['bubble_height']==44
    assert invalid['bubble_enter_motion']=='pop' and invalid['bubble_follow_mouse'] is False
    reopened.db.close()


def test_preview_uses_unsaved_draft_and_stops_when_leaving_or_recording(tmp_path,monkeypatch):
    from murmur import storage
    monkeypatch.setattr(storage,'credential',lambda *args:'')
    store=Store(tmp_path);window=MainWindow(store);window.navigate(3);window.settings_tabs.setCurrentIndex(3)
    window.fields['bubble_width'].setValue(320)
    window.fields['bubble_wave_motion'].setChecked(False)
    window.fields['bubble_wave_style'].setCurrentIndex(window.fields['bubble_wave_style'].findData('dots'))
    preview_bubble(window);preview=window._appearance_preview
    assert preview.capsule.cfg['bubble_width']==320 and store.config['bubble_width']==224
    assert not preview.capsule.wave.timer.isActive() and preview.capsule.wave.demo
    assert preview.capsule.wave.style=='dots'
    window.set_session_state('录音','听写')
    assert not window.bubble_preview_button.isEnabled() and not preview.capsule.isVisible()
    window.set_session_state('idle');preview_bubble(window);preview=window._appearance_preview
    preview.advance();preview.advance();preview.advance()
    assert preview.result.isVisible() and preview.result.demo
    window.settings_tabs.setCurrentIndex(0)
    assert not preview.result.isVisible() and not preview.timer.isActive()
    preview.dispose();window.hide();store.db.close()


def test_large_controls_fit_minimum_size_and_long_status_wraps():
    bubble=Bubble({'bubble_width':200,'bubble_height':40,'bubble_enter_motion':'none'})
    bubble.set_session_kind('Translation');bubble.state('录音','00:03');QApplication.processEvents()
    assert bubble.close.width()==32 and bubble.mic.iconSize().width()==22
    for widget in (bubble.close,bubble.mode_mark,bubble.wave,bubble.status,bubble.mic):
        assert bubble.contents.rect().contains(widget.geometry())
    assert bubble.status.fontMetrics().horizontalAdvance('00:03')<=bubble.status.width()
    result=ResultBubble({'bubble_enter_motion':'none'})
    result.show_result('完整结果。',status='The target changed or could not be confirmed · Copy to use')
    QApplication.processEvents()
    assert result.status.wordWrap() and result.dismiss_button.width()==32
    assert result.status.geometry().right()<result.dismiss_button.geometry().left()
    long_status='Review wording: '+('Unfamiliar technical term · '*100)
    result.show_result('完整结果。',status=long_status);QApplication.processEvents()
    assert len(result.status.text())<len(long_status) and result.status.toolTip()==long_status
    assert result.contents.rect().contains(result.copy_button.geometry())
    assert result.copy_button.mapTo(result.contents,QPoint(0,0)).y()+result.copy_button.height()<=result.contents.height()
    bubble.hide();result.hide()

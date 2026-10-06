import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import threading
import pytest
from PySide6.QtCore import Qt,QAbstractAnimation,QPoint,QEvent,QPointF
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtGui import QFontDatabase,QMouseEvent
from murmur import storage,release_check
from murmur.dashboard import MainWindow
from murmur.ui import STYLE
from murmur.system_resources import cpu_percent,ResourceSampler


@pytest.fixture
def window(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);app.setStyleSheet(STYLE)
    for name in ('segoeui.ttf','segoeuib.ttf'):QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+name)
    monkeypatch.setattr(storage,'credential',lambda *args:'')
    store=storage.Store(tmp_path);w=MainWindow(store);w.show();app.processEvents()
    yield w
    if hasattr(w,'token_dialog'):w.token_dialog.hide()
    w.hide();store.db.close()


def test_counters_account_for_idle_in_kernel_and_reset():
    assert cpu_percent(None,(10,20,30)) is None
    assert cpu_percent((10,20,30),(30,60,70))==75
    assert cpu_percent((10,20,30),(1,2,3)) is None
    assert cpu_percent((10,20,30),(10,20,30)) is None


def test_native_sampler_returns_plausible_memory_without_subprocesses():
    sample=ResourceSampler().sample()
    if os.name=='nt':
        assert 0<=sample['memory_percent']<=100 and sample['memory_total_gb']>0
        assert sample['process_mb']>0


def test_calendar_halo_delayed_details_and_leave(window):
    calendar=window.calendar;QApplication.processEvents()
    rect,day,count=calendar.cells[-1]
    assert rect.width()>=12
    QApplication.sendEvent(calendar,QMouseEvent(QEvent.MouseMove,rect.center(),QPointF(calendar.mapToGlobal(rect.center().toPoint())),Qt.NoButton,Qt.NoButton,Qt.NoModifier));QTest.qWait(100)
    assert calendar.hover_day==day and calendar.get_hover_strength()>0
    QTest.mouseClick(calendar,Qt.LeftButton,pos=rect.center().toPoint())
    assert window.stack.currentIndex()==0 and window.day_summary_row.isHidden()
    assert calendar.detail_panel is None
    QTest.qWait(2100)
    assert calendar.detail_panel.isVisible() and '0 sessions' in calendar.detail_text.text()
    assert calendar.detail_panel.parentWidget() is window
    QApplication.sendEvent(calendar,QEvent(QEvent.Leave))
    assert not calendar.detail_panel.isVisible() and not calendar.dwell.isActive()
    QTest.qWait(210)
    assert calendar.hover_day is None and calendar.get_hover_strength()>0
    QTest.qWait(1600)
    assert calendar.hover_day is None and calendar.get_hover_strength()==0
    assert not calendar.frame_timer.isActive()


def test_calendar_trail_preserves_crossed_tiles_and_ripples_expire(window):
    calendar=window.calendar;calendar.ensure_base()
    first=calendar.cells[70];second=calendar.cells[105]
    def move(cell):
        point=cell[0].center()
        QApplication.sendEvent(calendar,QMouseEvent(QEvent.MouseMove,point,QPointF(calendar.mapToGlobal(point.toPoint())),Qt.NoButton,Qt.NoButton,Qt.NoModifier))
    move(first);QTest.qWait(100);before=calendar._energies[first[1]]
    move(second);QTest.qWait(80)
    assert 0<calendar._energies[first[1]]<before
    assert calendar._energies[second[1]]>0
    for _ in range(6):QTest.mouseClick(calendar,Qt.LeftButton,pos=second[0].center().toPoint())
    assert len(calendar._ripples)==4 and window.stack.currentIndex()==0
    QApplication.sendEvent(calendar,QEvent(QEvent.Leave));QTest.qWait(1900)
    assert not calendar._ripples and not calendar._energies and not calendar.frame_timer.isActive()
    assert not window.calendar_card.motion_enabled
    QTest.mouseClick(window.calendar_card,Qt.LeftButton)
    assert window.calendar_card.get_pulse()==0 and window.calendar_card.get_hover()==0


def test_history_cache_keeps_cards_but_new_records_and_search_refresh(window):
    for i in range(30):window.store.add(f'fixture-{i}','听写','Public sample','Public result',1,1,False)
    window.navigate(1);QApplication.processEvents()
    first_card=window.history_body.itemAt(1).widget()
    window.navigate(0);window.navigate(1);QApplication.processEvents()
    assert window.history_body.itemAt(1).widget() is first_card
    assert window._history_total==30 and len(window.current_rows)<30
    for _ in range(100):
        if not window._history_pending:break
        QTest.qWait(10)
    bar=window.stack.widget(1).verticalScrollBar()
    for _ in range(10):
        QTest.qWait(80);bar.setValue(bar.maximum());QApplication.processEvents()
        if window.history_top_button.isVisible():break
    assert window.history_top_button.isVisible()
    window.history_top_button.click();QTest.qWait(260)
    assert bar.value()==0 and window.history_top_button.isHidden()
    window.store.add('new','听写','Distinctive public sample','New result',1,1,False)
    window.navigate(0);window.navigate(1);QApplication.processEvents()
    assert window._history_total==31 and len(window.current_rows)<31
    window.search.setText('Distinctive');QTest.qWait(260)
    assert len(window.current_rows)==1 and window.current_rows[0]['raw']=='Distinctive public sample'


def test_history_loads_only_viewport_then_scrolls_and_preserves_full_text(window):
    text=('Full public session text with enough words to wrap naturally. '*18)+'END OF SESSION'
    for i in range(52):window.store.add(f'batch-{i}','听写',text,text,1,1,False)
    window.navigate(1);QTest.qWait(180)
    first_card=window.history_body.itemAt(1).widget()
    from PySide6.QtWidgets import QLabel
    excerpt=next(x for x in first_card.findChildren(QLabel) if x.text()==text)
    assert excerpt.wordWrap() and excerpt.height()>excerpt.fontMetrics().lineSpacing()*3
    loaded=len(window.current_rows)
    assert 0<loaded<10 and window._history_total==52
    QTest.qWait(150);assert len(window.current_rows)==loaded
    bar=window.stack.widget(1).verticalScrollBar();bar.setValue(bar.maximum());QTest.qWait(180)
    assert len(window.current_rows)>loaded and len(window.current_rows)<52
    assert window.history_body.itemAt(1).widget() is first_card
    assert not window.history_top_button.icon().isNull() and window.history_top_button.text()==''
    window.navigate(0);count=window.history_body.count();QTest.qWait(100)
    assert window.history_body.count()==count and not window._history_render_timer.isActive()
    window.navigate(1);QTest.qWait(100)
    assert window.history_body.itemAt(1).widget() is first_card
    window.search.setText('No such public transcript');QTest.qWait(260)
    assert window.current_rows==[] and not window._history_pending


def test_corners_are_transparent_and_metric_click_shimmers_without_changing_totals(window):
    image=window.grab().toImage()
    for x,y in ((0,0),(image.width()-1,0),(0,image.height()-1),(image.width()-1,image.height()-1)):
        assert image.pixelColor(x,y).alpha()==0
    value=window.metric_values[0];before=value.text()
    QTest.mouseClick(value.parentWidget(),Qt.LeftButton);QTest.qWait(80)
    assert value.shine_animation.state()==QAbstractAnimation.Running and value.text()==before
    QTest.qWait(650);assert value.shine_animation.state()==QAbstractAnimation.Stopped


def test_home_resource_timer_is_visible_only_and_config_uses_saved_values(window):
    assert window.resource_timer.isActive()
    cfg=window.store.config;cfg.update(llm_model='saved-model',ollama_auto=False,llm_url='https://user:private@example.com/v1?key=secret')
    window.fields['llm_model'].setText('unsaved-model');window.refresh_configuration()
    assert 'saved-model' in window.config_labels['llm'].toolTip()
    assert 'private' not in window.config_labels['llm'].toolTip() and 'secret' not in window.config_labels['llm'].toolTip()
    window.navigate(1);assert not window.resource_timer.isActive()
    window.navigate(0);assert window.resource_timer.isActive()
    window.hide();assert not window.resource_timer.isActive()


def test_resource_bars_and_startup_states_are_truthful(window):
    assert window.badge.isHidden()
    assert set(window.resource_bars)=={'cpu','memory','gpu'}
    window.apply_resources(dict(cpu_percent=25,memory_percent=60,memory_used_gb=19.2,memory_total_gb=32,process_mb=120,
                                gpu_percent=50,gpu_used_gb=4,gpu_total_gb=8))
    assert window.resource_bars['cpu'].value==25 and window.resource_bars['gpu'].value==50
    assert window.resource_labels['memory'].text()=='120 MB'
    assert 'MurMur + child workers' in window.resource_labels['cpu'].toolTip()
    assert 'System RAM' not in window.resource_labels['memory'].toolTip()
    assert window.resource_labels['gpu'].text()=='4.0/8 GB'
    window.apply_resources(dict(cpu_percent=20,memory_percent=60,memory_used_gb=19.2,memory_total_gb=32,process_mb=120))
    assert window.resource_bars['gpu'].value is None and window.resource_labels['gpu'].text()=='N/A'
    window._availability_generation=3
    window.apply_availability((2,'llm','active','Old response'));assert window.config_dots['llm'].state=='pending'
    window.apply_availability((3,'llm','warning','Model not listed'));assert window.config_dots['llm'].state=='warning'
    window.set_speech_readiness(True)
    window.apply_availability((3,'asr','warning','Files only'));assert window.config_dots['asr'].state=='active'


def test_initial_availability_checks_are_async_and_do_not_change_config(window,monkeypatch):
    from murmur import service_availability
    before=dict(window.store.config);calls=[]
    monkeypatch.setattr(service_availability,'probe',lambda kind,cfg:(calls.append(kind) or 'active','Fixture catalog check'))
    window.enable_saved_service_checks()
    for _ in range(100):
        if all(dot.state=='active' for dot in window.config_dots.values()):break
        QTest.qWait(10)
    assert calls==['asr','llm','ask'] and window.store.config==before
    assert all(dot.state=='active' for dot in window.config_dots.values())


def test_token_arrow_supports_keyboard_and_counts(window):
    window.store.record_usage(dict(request_id='public',local=True,total_tokens=500,cost_usd=0))
    window.token_insight_button.setFocus();QTest.keyClick(window.token_insight_button,Qt.Key_Space);QApplication.processEvents()
    assert window.token_dialog.isVisible()
    assert window.token_split.local==500 and window.token_split.external==0
    for value in window.token_values.values():
        assert value.height()>=value.fontMetrics().height()
        assert window.token_dialog.rect().contains(value.mapTo(window.token_dialog,value.rect().bottomRight()))


def test_configuration_surface_stays_home_and_hover_settles(window):
    QTest.mouseMove(window.config_card,window.config_card.rect().center());QTest.qWait(170)
    assert window.config_card.animation.state()==QAbstractAnimation.State.Stopped
    QTest.mouseClick(window.config_card,Qt.LeftButton)
    assert window.stack.currentIndex()==0


def test_release_check_is_async_coalesced_and_cache_expires(window,monkeypatch):
    gate=threading.Event();calls=[]
    def check(current):
        calls.append(current);gate.wait(2);return release_check.select_release([{'tag_name':'v0.5.0'}],current)
    monkeypatch.setattr(release_check,'check_releases',check)
    window.request_release_check();window.request_release_check()
    assert window._release_busy and not window.release_check_button.isEnabled()
    gate.set()
    for _ in range(100):
        if not window._release_busy:break
        QTest.qWait(10)
    assert window._release_result.state=='update' and len(calls)==1
    timestamp=window._release_checked_at;window.request_release_check()
    assert len(calls)==1 and window._release_checked_at==timestamp
    window._release_checked_at-=901;window.request_release_check()
    for _ in range(100):
        if not window._release_busy:break
        QTest.qWait(10)
    assert len(calls)==2


def test_history_export_includes_unloaded_matching_sessions(window,tmp_path,monkeypatch):
    import json
    from murmur import dashboard
    for i in range(40):window.store.add(f'export-{i}','test','Public raw','Public full text',1,1,False)
    window.navigate(1);QTest.qWait(160)
    assert len(window.current_rows)<40
    path=tmp_path/'export.json'
    monkeypatch.setattr(dashboard.QFileDialog,'getSaveFileName',lambda *a:(str(path),''))
    window.export_history()
    assert len(json.loads(path.read_text(encoding='utf-8')))==40


def test_shortcut_and_configuration_surfaces_shimmer_without_navigation(window):
    for surface,values in ((window.config_card,window.config_shimmers),(window.shortcuts_card,window.shortcut_shimmers)):
        QTest.mouseClick(surface,Qt.LeftButton);QTest.qWait(70)
        assert window.stack.currentIndex()==0
        assert all(0<value.get_shine()<1 for value in values)
    from PySide6.QtWidgets import QToolButton
    settings=next(x for x in window.config_card.findChildren(QToolButton) if x.toolTip()=='Configure services')
    QTest.mouseClick(settings,Qt.LeftButton)
    assert window.stack.currentIndex()==3
    window.navigate(0)
    settings=next(x for x in window.shortcuts_card.findChildren(QToolButton) if x.toolTip()=='Edit shortcuts')
    QTest.mouseClick(settings,Qt.LeftButton)
    assert window.stack.currentIndex()==3


def test_resource_click_shimmers_without_changing_usage_or_navigating(window):
    window.resource_timer.stop();window.resources_ready.disconnect(window.apply_resources)
    before={key:(window.resource_labels[key].text(),bar.value) for key,bar in window.resource_bars.items()}
    QTest.mouseClick(window.resource_card,Qt.LeftButton);QTest.qWait(90)
    assert window.stack.currentIndex()==0
    assert all(0<item.get_shine()<1 for item in window.resource_shimmers)
    assert before=={key:(window.resource_labels[key].text(),bar.value) for key,bar in window.resource_bars.items()}
    QTest.qWait(700)
    assert all(item.shine_animation.state()==QAbstractAnimation.Stopped for item in window.resource_shimmers)


def test_token_surface_only_arrow_opens_details(window):
    before=(window.home_local_tokens.text(),window.home_external_tokens.text())
    QTest.mouseClick(window.usage_card,Qt.LeftButton);QTest.qWait(80)
    assert not hasattr(window,'token_dialog') or not window.token_dialog.isVisible()
    assert all(0<item.get_shine()<1 for item in window.usage_shimmers)
    QTest.mouseClick(window.home_local_tokens,Qt.LeftButton);QTest.qWait(80)
    assert not hasattr(window,'token_dialog') or not window.token_dialog.isVisible()
    assert before==(window.home_local_tokens.text(),window.home_external_tokens.text())
    QTest.mouseClick(window.token_insight_button,Qt.LeftButton)
    assert window.token_dialog.isVisible()

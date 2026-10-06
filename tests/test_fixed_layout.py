"""Fixed app geometry, Settings mode and Home insights remain usable."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtCore import Qt,QSize,QAbstractAnimation,QEvent,QPointF,QPoint
from PySide6.QtGui import QFontDatabase,QMouseEvent
from PySide6.QtWidgets import QApplication, QInputDialog, QDialog
from PySide6.QtTest import QTest
from murmur import storage
from murmur.dashboard import MainWindow
from murmur.ui import STYLE

@pytest.fixture
def window(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    # The Windows offscreen plugin does not discover system Segoe UI fonts.
    # Use the actual app font so fallback glyph widths cannot create overflow.
    for font in ('segoeui.ttf','segoeuib.ttf'):
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+font)
    monkeypatch.setattr(storage,'credential',lambda *args:'')
    s=storage.Store(tmp_path)
    w=MainWindow(s);w.setStyleSheet(STYLE);w.show();app.processEvents()
    yield w
    for dialog in w.service_test_dialogs.values():dialog.hide()
    if hasattr(w,'token_dialog'):w.token_dialog.hide()
    w.hide();s.db.close()

@pytest.mark.parametrize('attempt',[(640,400),(1400,1000)])
def test_main_window_cannot_resize_or_maximize(window,attempt):
    size=QSize(940,600)
    assert window.minimumSize()==window.maximumSize()==size
    assert not window.windowFlags() & Qt.WindowMaximizeButtonHint
    assert window.windowFlags() & Qt.FramelessWindowHint
    window.resize(*attempt);QApplication.processEvents()
    assert window.size()==size


def test_sidebar_highlight_slides_and_empty_status_collapses(window):
    sidebar=window.main_sidebar
    start=sidebar.get_top();window.navigate(1)
    assert sidebar.slide.state()==QAbstractAnimation.Running
    QTest.qWait(80)
    assert start<sidebar.get_top()<window.nav_buttons[1].y()
    window.navigate(2);QTest.qWait(220)
    assert sidebar.get_top()==window.nav_buttons[2].y()
    assert window.nav_buttons[2].isChecked() and window.nav_buttons[2].property('cutout')
    assert window.nav_buttons[3].property('settingsEntry')
    from PySide6.QtWidgets import QWidget
    assert not isinstance(window.home_status,QWidget)
    window.home_status.setText('Transcribing…')
    assert window.home_status.text()=='Transcribing…'
    window.home_status.clear();assert window.home_status.text()==''


def test_header_drag_uses_global_logical_coordinates_and_releases_capture(window):
    original=window.pos();global_start=window.mapToGlobal(QPoint(35,25));delta=QPoint(45,30)
    press=QMouseEvent(QEvent.MouseButtonPress,QPointF(35,25),QPointF(global_start),Qt.LeftButton,Qt.LeftButton,Qt.NoModifier)
    QApplication.sendEvent(window.centralWidget(),press)
    assert window.window_drag.offset is not None
    move=QMouseEvent(QEvent.MouseMove,QPointF(35,25),QPointF(global_start+delta),Qt.NoButton,Qt.LeftButton,Qt.NoModifier)
    QApplication.sendEvent(window,move)
    assert window.pos()==original+delta
    release=QMouseEvent(QEvent.MouseButtonRelease,QPointF(35,25),QPointF(global_start+delta),Qt.LeftButton,Qt.NoButton,Qt.NoModifier)
    QApplication.sendEvent(window,release)
    assert window.window_drag.offset is None
    assert window.centralWidget().objectName()=='windowShell'
    assert 'border:2px' in window.centralWidget().styleSheet()

def test_settings_replaces_main_sidebar_and_returns_to_previous_page(window):
    window.navigate(2);window.navigate(3);QTest.qWait(180)
    assert window.main_sidebar.isHidden() and window.settings_nav_buttons[0].isVisible()
    assert window.settings_close_button.isVisible() and window.save_button.isVisible()
    window.settings_tabs.setCurrentIndex(4)
    QTest.mouseClick(window.settings_close_button,Qt.LeftButton)
    assert window.stack.currentIndex()==2 and window.main_sidebar.isVisible()
    window.open_shortcut_settings()
    assert window.stack.currentIndex()==3 and window.settings_tabs.currentIndex()==2

def test_home_activity_values_and_shortcut_caps_follow_saved_data(window):
    s=window.store;s.config['dictation_key']='f9';s.config['selection_key']='ctrl+shift+space'
    s.add('public-fixture','听写','Public sample','Public result',12,1,False)
    window.refresh();QApplication.processEvents()
    assert [w.text() for w in window.activity_values]==['1','1','1']
    assert [cap.text() for cap in window.quick_keycaps['dictation_key'] if not cap.isHidden()]==['F9']
    assert [cap.text() for cap in window.quick_keycaps['selection_key'] if not cap.isHidden()]==['Ctrl','Shift','Space']
    assert window.stack.widget(0).verticalScrollBar().maximum()==0
    assert window.stack.widget(0).horizontalScrollBar().maximum()==0
    window.filter_day(s.rows()[0]['time'][:10]);QApplication.processEvents()
    assert not window.calendar_legend.isHidden() and window.day_summary_row.isHidden()
    assert window.stack.widget(0).verticalScrollBar().maximum()==0

def test_usage_dialog_is_fixed_and_home_shows_actual_metadata(window):
    window.store.record_usage(dict(request_id='public-usage',local=False,total_tokens=7,cost_usd=.03))
    window.refresh_token_insights()
    assert window.home_external_tokens.text()=='7'
    assert window.home_external_tokens.accessibleName()=='External: 7 tokens'
    assert window.home_cost_hint.text()=='$0.03'
    assert '$0.030000 USD' in window.home_cost_hint.toolTip()
    window.show_token_insights();dialog=window.token_dialog
    assert dialog.minimumSize()==dialog.maximumSize()==QSize(480,320)
    dialog.resize(600,500);QApplication.processEvents()
    assert dialog.size()==QSize(480,320)
    window.store.record_usage(dict(request_id='public-large-local',local=True,total_tokens=1250000,cost_usd=0))
    window.store.record_usage(dict(request_id='public-large-external',local=False,total_tokens=4565432,cost_usd=None))
    window.refresh_token_insights();QApplication.processEvents()
    assert window.home_local_tokens.text()=='1.2M'
    assert window.home_external_tokens.text()=='4.6M'
    assert '4,565,439' in window.home_external_tokens.toolTip()
    assert window.token_values['external_tokens'].text()=='4,565,439'
    assert '1 unpriced calls' in window.home_cost_hint.toolTip()
    for value in (window.home_local_tokens,window.home_external_tokens,window.home_cost_hint):
        assert value.fontMetrics().horizontalAdvance(value.text())<=value.contentsRect().width()
    assert window.stack.widget(0).verticalScrollBar().maximum()==0
    assert window.stack.widget(0).horizontalScrollBar().maximum()==0

def test_add_word_dialog_is_fixed_and_accepts_text(window,monkeypatch):
    seen=[]
    def accept(dialog):
        assert dialog.minimumSize()==dialog.maximumSize()==QSize(360,150)
        assert not dialog.windowFlags() & Qt.WindowMaximizeButtonHint
        dialog.resize(900,500)
        assert dialog.size()==QSize(360,150)
        dialog.setTextValue('Public term')
        seen.append(dialog.windowTitle())
        return QDialog.Accepted
    monkeypatch.setattr(QInputDialog,'exec',accept)
    window.new_word()
    assert seen==['Add word']
    assert any(row['word']=='Public term' for row in window.store.words())

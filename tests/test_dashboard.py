import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from murmur.dashboard import MainWindow
from murmur.storage import Store

def test_four_pages_and_compact_sizes(tmp_path):
    app=QApplication.instance() or QApplication([]);window=MainWindow(Store(tmp_path))
    assert window.stack.count()==4;assert window.width()==920;assert window.settings_tabs.count()==5
    assert 'hotwords' not in window.fields
    assert window.fields['bubble_width'].value()==224
    for index in range(4):window.navigate(index);app.processEvents()
    window.hide()

def test_calendar_filters_history(tmp_path):
    app=QApplication.instance() or QApplication([]);s=Store(tmp_path);s.add('one','听写','原文','文字',60,1,True)
    day=s.rows()[0]['time'][:10];window=MainWindow(s);window.filter_day(day)
    assert len(window.current_rows)==1;window.filter_day('2000-01-01');assert not window.current_rows;window.hide()

def test_word_acceptance_updates_hotwords(tmp_path):
    app=QApplication.instance() or QApplication([]);s=Store(tmp_path);window=MainWindow(s)
    from PySide6.QtWidgets import QPushButton
    b=QPushButton();window.accept_word({'word':'COMSOL'},b)
    assert 'COMSOL' in s.config['hotwords'];assert not b.isEnabled();window.hide()

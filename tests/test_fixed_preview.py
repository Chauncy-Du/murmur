"""The editor is fixed; floating result animation remains independently sized."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import Qt, QSize, QPoint
from PySide6.QtWidgets import QApplication
from murmur.ui import Preview


@pytest.fixture
def preview():
    app=QApplication.instance() or QApplication([])
    window=Preview()
    yield window
    window.hide()


def test_editor_size_is_enforced_before_and_after_show(preview):
    expected=QSize(680,440)
    assert preview.minimumSize()==expected and preview.maximumSize()==expected
    for size in ((320,240),(1000,800)):
        preview.resize(*size)
        assert preview.size()==expected
    preview.show_text('Fixture original','Fixture result')
    QApplication.processEvents()
    preview.resize(920,680)
    assert preview.size()==expected
    assert preview.raw.width()>0 and preview.result.height()>0


def test_fixed_editor_retains_title_movement_and_close_without_maximize(preview):
    flags=preview.windowFlags()
    assert flags & Qt.WindowTitleHint and flags & Qt.WindowSystemMenuHint
    assert flags & Qt.WindowCloseButtonHint and flags & Qt.MSWindowsFixedSizeDialogHint
    assert not flags & Qt.WindowMaximizeButtonHint
    assert not flags & Qt.FramelessWindowHint
    assert not preview.isSizeGripEnabled()
    preview.show_text('Fixture original','Fixture result')
    preview.move(QPoint(60,70))
    assert preview.pos()==QPoint(60,70)
    preview.close()
    assert not preview.isVisible()


def test_fixed_editor_scrolls_long_content_without_changing_geometry(preview):
    text='Fixture sentence with a long result.\n'*100
    preview.show_text(text,text)
    QApplication.processEvents()
    assert preview.size()==QSize(680,440)
    assert preview.raw.toPlainText()==text and preview.result.toPlainText()==text
    assert preview.raw.verticalScrollBar().maximum()>0
    assert preview.result.verticalScrollBar().maximum()>0


def test_fixed_editor_busy_close_still_requests_cancel(preview):
    cancelled=[]
    preview.cancel.connect(lambda:cancelled.append(True))
    preview.show_text('Fixture original','Fixture result')
    preview.set_session_state('整理','润色')
    preview.close()
    assert cancelled==[True] and preview.isVisible()
    assert preview.size()==QSize(680,440)
    preview.set_session_state(None)
    preview.close()
    assert not preview.isVisible()

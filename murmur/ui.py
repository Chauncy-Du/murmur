"""Shared dark desktop components; domain mode identifiers remain unchanged."""
import math
import re
import time
from collections import deque
from PySide6.QtCore import Qt, QTimer, Signal, Property, QPointF, QRectF, QRect, QSize, QPropertyAnimation, QParallelAnimationGroup, QEasingCurve, QLocale
from PySide6.QtGui import QColor, QPainter, QPen, QIcon, QPixmap, QPainterPath, QTextOption, QDoubleValidator
from PySide6.QtWidgets import *

STYLE = '''
QWidget {font-family:"Segoe UI";font-size:13px;color:#f1f1f4;}
QMainWindow,QDialog,QWidget#page {background:#1c1c1f;}
QFrame#sidebar {background:#242427;border-radius:14px;}
QFrame#card {background:#29292d;border:1px solid #323238;border-radius:12px;}
QLabel#title {font-size:26px;font-weight:600;}
QLabel#muted {color:#a4a4ae;}
QLabel#brand {font-size:19px;font-weight:600;}
QLabel#metric {font-size:27px;font-weight:600;}
QLabel#eyebrow {font-size:11px;color:#a4a4ae;}
QPushButton {background:#303035;border:1px solid #3a3a41;border-radius:7px;padding:5px 11px;min-height:18px;}
QPushButton:hover {background:#3a3a41;border-color:#494952;}
QPushButton:pressed {background:#252529;}
QPushButton:focus {border-color:#b9aafa;}
QPushButton#primary {background:#c7b8fa;color:#211b32;border:1px solid #c7b8fa;font-weight:600;}
QPushButton#primary:hover {background:#daceff;border-color:#daceff;}
QPushButton#primary:pressed {background:#b8a4ed;}
QPushButton#primary:focus {border:1px solid #faf7ff;}
QPushButton#primary:disabled {background:#302c37;color:#8a8197;border-color:#3b3543;}
QPushButton#nav {text-align:left;border:1px solid transparent;background:transparent;padding:8px 11px;}
QPushButton#nav:hover {background:#2f2f34;}
QPushButton#nav:pressed {background:#28282e;}
QPushButton#nav:checked {background:#37373e;color:#ffffff;}
QPushButton#nav[keyboardFocus="true"]:focus {border-color:#8c7eb7;}
QPushButton:disabled {background:#26262b;color:#777780;border-color:#303036;}
QLineEdit,QTextEdit,QPlainTextEdit,QComboBox,QSpinBox {background:#242428;border:1px solid #3a3a42;border-radius:7px;padding:6px;selection-background-color:#675986;}
QLineEdit:focus,QTextEdit:focus,QPlainTextEdit:focus,QComboBox:focus,QSpinBox:focus {border-color:#b2a0ec;}
QLineEdit:disabled,QComboBox:disabled,QSpinBox:disabled {color:#777780;}
QComboBox {padding-right:26px;}
QComboBox::drop-down {width:22px;border:0;}
QComboBox QAbstractItemView {background:#29292e;color:#f1f1f4;selection-background-color:#494050;border:1px solid #45454d;outline:0;}
QGroupBox {background:#29292d;border:1px solid #36363c;border-radius:10px;margin-top:14px;padding:12px;font-weight:600;}
QGroupBox::title {subcontrol-origin:margin;left:12px;padding:0 4px;}
QScrollArea {border:0;background:transparent;}
QScrollArea > QWidget > QWidget {background:transparent;}
QScrollBar:vertical {background:transparent;width:6px;margin:2px;}
QScrollBar::handle:vertical {background:#484850;border-radius:3px;min-height:24px;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {background:transparent;}
QTabWidget::pane {border:0;}
QTabBar::tab {background:transparent;color:#a4a4ae;padding:9px 11px;border-bottom:2px solid transparent;}
QTabBar::tab:selected {color:#f1f1f4;border-bottom-color:#bba8fa;}
QTabBar::tab:hover {color:#dcd6ec;}
QToolTip {background:#33333a;color:#f1f1f4;border:1px solid #4b4b55;padding:5px;}
QMenu {background:#29292e;border:1px solid #41414a;border-radius:7px;padding:5px;}
QMenu::item {padding:7px 18px;border-radius:4px;}
QMenu::item:selected {background:#484050;}
QCheckBox {spacing:8px;padding:3px 0;}
QCheckBox::indicator {width:16px;height:16px;border-radius:4px;border:1px solid #676771;background:#242428;}
QCheckBox::indicator:checked {background:#c7b8fa;border:1px solid #c7b8fa;}
QCheckBox::indicator:hover {border-color:#c7b8fa;}
QCheckBox::indicator:focus {border:2px solid #eee6ff;}
QToolButton {background:transparent;border:1px solid transparent;border-radius:5px;color:#a4a4ae;padding:3px;}
QToolButton:hover {background:#393940;color:#f1f1f4;}
QToolButton:pressed {background:#29292f;}
QToolButton:focus {border-color:#b2a0ec;}
QToolButton::menu-indicator {image:none;width:0;}
'''


def line_icon(name, size=16, color='#b7b7c3'):
    """Draw crisp, consistently weighted icons without platform font glyphs."""
    pix = QPixmap(size * 2, size * 2)
    pix.setDevicePixelRatio(2)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 24, size / 24)
    p.setPen(QPen(QColor(color), 1.65, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)

    def line(x1, y1, x2, y2):
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def path(points):
        shape = QPainterPath(QPointF(*points[0]))
        for xy in points[1:]:
            shape.lineTo(QPointF(*xy))
        p.drawPath(shape)

    if name == 'home':
        path([(3, 11), (12, 3.5), (21, 11)])
        path([(5.5, 9), (5.5, 20), (10, 20), (10, 14), (14, 14), (14, 20), (18.5, 20), (18.5, 9)])
    elif name == 'history':
        p.drawArc(QRectF(4, 4, 16, 16), -45 * 16, 285 * 16)
        path([(3.5, 4.5), (3.5, 10), (8.5, 10)])
        path([(12, 7), (12, 12), (15.5, 14)])
    elif name == 'dictionary':
        p.drawRoundedRect(QRectF(5, 3.5, 14, 17), 1.5, 1.5)
        line(8, 3.5, 8, 20.5)
        line(11, 8, 16, 8)
        line(11, 11, 16, 11)
        line(11, 14, 14, 14)
    elif name == 'settings':
        p.drawEllipse(QRectF(8.5, 8.5, 7, 7))
        for i in range(8):
            a = i * math.pi / 4
            line(12 + 7 * math.cos(a), 12 + 7 * math.sin(a), 12 + 9 * math.cos(a), 12 + 9 * math.sin(a))
        p.drawEllipse(QRectF(5, 5, 14, 14))
    elif name in ('mic', 'record'):
        p.drawRoundedRect(QRectF(9, 3, 6, 12), 3, 3)
        p.drawArc(QRectF(6, 7, 12, 12), 180 * 16, 180 * 16)
        line(12, 19, 12, 22)
        line(8.5, 22, 15.5, 22)
    elif name == 'stop':
        p.setBrush(QColor(color))
        p.drawRoundedRect(QRectF(7, 7, 10, 10), 2, 2)
    elif name == 'close':
        line(7, 7, 17, 17)
        line(7, 17, 17, 7)
    elif name == 'copy':
        p.drawRoundedRect(QRectF(8, 8, 12, 13), 2, 2)
        path([(15, 5), (15, 3), (4, 3), (4, 16), (5.5, 16)])
    elif name == 'more':
        p.setBrush(QColor(color))
        for x in (5, 12, 19):
            p.drawEllipse(QRectF(x - .8, 11.2, 1.6, 1.6))
    elif name in ('export', 'download'):
        path([(5, 15), (5, 20), (19, 20), (19, 15)])
        line(12, 3, 12, 15)
        path([(8, 11), (12, 15), (16, 11)])
    elif name in ('plus', 'add'):
        line(12, 5, 12, 19)
        line(5, 12, 19, 12)
    elif name == 'translate':
        line(3, 6, 14, 6)
        line(8.5, 3, 8.5, 6)
        path([(5, 8), (8, 12), (13, 16)])
        path([(12, 6), (10, 12), (4, 16)])
        path([(12, 21), (17, 10), (22, 21)])
        line(14, 17, 20, 17)
    elif name == 'edit':
        path([(5, 16), (16.5, 4.5), (20, 8), (8.5, 19.5), (4, 20), (5, 16)])
        line(14, 7, 17.5, 10.5)
    elif name == 'search':
        p.drawEllipse(QRectF(4, 4, 12, 12))
        line(14.5, 14.5, 20, 20)
    elif name == 'info':
        p.drawEllipse(QRectF(3, 3, 18, 18))
        line(12, 11, 12, 17)
        p.drawPoint(QPointF(12, 7))
    elif name == 'chart':
        path([(4, 4), (4, 20), (21, 20)])
        line(8, 15, 8, 18)
        line(13, 10, 13, 18)
        line(18, 6, 18, 18)
    elif name == 'tokens':
        p.drawEllipse(QRectF(3, 7, 14, 14))
        p.drawArc(QRectF(7, 3, 14, 14), -25 * 16, 245 * 16)
        line(10, 10.5, 10, 17.5)
    elif name == 'check':
        path([(5, 12), (10, 17), (19, 7)])
    elif name in ('arrow_left', 'arrow_right', 'chevron_down'):
        points = {'arrow_left': [(15, 6), (9, 12), (15, 18)], 'arrow_right': [(9, 6), (15, 12), (9, 18)], 'chevron_down': [(6, 9), (12, 15), (18, 9)]}
        path(points[name])
    else:
        for x, h in zip((4, 8, 12, 16, 20), (5, 11, 17, 11, 5)):
            line(x, 12 - h / 2, x, 12 + h / 2)
    p.end()
    result = QIcon(pix)
    disabled = QPixmap(pix.size())
    disabled.setDevicePixelRatio(2)
    disabled.fill(Qt.transparent)
    painter = QPainter(disabled)
    painter.setOpacity(.38)
    painter.drawPixmap(0, 0, pix)
    painter.end()
    result.addPixmap(disabled, QIcon.Disabled)
    return result


class NavigationButton(QPushButton):
    """Show focus for keyboard use without making a mouse selection look doubled."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setProperty('keyboardFocus', False)

    def keyboard_focus(self, enabled):
        self.setProperty('keyboardFocus', bool(enabled))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def focusInEvent(self, event):
        self.keyboard_focus(event.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason))
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self.keyboard_focus(False)
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        self.keyboard_focus(True)
        super().keyPressEvent(event)


def button(text, callback=None, primary=False, navigation=False):
    b = NavigationButton(text) if navigation else QPushButton(text)
    b.setCursor(Qt.PointingHandCursor)
    if primary:
        b.setObjectName('primary')
    if callback:
        b.clicked.connect(callback)
    return b


def label(text, kind=None):
    w = QLabel(text)
    w.setTextFormat(Qt.PlainText)
    w.setWordWrap(True)
    if kind:
        w.setObjectName(kind)
    return w


class CompactComboBox(QComboBox):
    """A visible chevron regardless of the system palette or Windows theme."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.selected_summaries = {}
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(10)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet('QComboBox::down-arrow {image:none;width:0;height:0;}')

    def paintEvent(self, event):
        summary = self.selected_summaries.get(self.currentData()) if self.selected_summaries else None
        if summary:
            option = QStyleOptionComboBox()
            self.initStyleOption(option)
            option.currentText = summary
            painter = QStylePainter(self)
            painter.drawComplexControl(QStyle.CC_ComboBox, option)
            painter.drawControl(QStyle.CE_ComboBoxLabel, option)
            painter.end()
        else:
            super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor('#a4a4ae' if self.isEnabled() else '#686872'), 1.3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        center = QPointF(self.width() - 13, self.height() / 2)
        shape = QPainterPath(center + QPointF(-3, -1.5))
        shape.lineTo(center + QPointF(0, 1.5))
        shape.lineTo(center + QPointF(3, -1.5))
        p.drawPath(shape)


class CheckedBox(QCheckBox):
    """A compact switch retaining QCheckBox state, keyboard, and accessibility."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet('QCheckBox::indicator,QCheckBox::indicator:checked,QCheckBox::indicator:focus {width:32px;height:18px;border:0;background:transparent;}')

    def paintEvent(self, event):
        super().paintEvent(event)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        rect = QRectF(self.style().subElementRect(QStyle.SE_CheckBoxIndicator, option, self))
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(.45)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor('#bba8ef' if self.isChecked() else '#4b4b56'))
        p.drawRoundedRect(rect, 9, 9)
        x = rect.right() - 15 if self.isChecked() else rect.left() + 3
        p.setBrush(QColor('#fcfaff' if self.isChecked() else '#c6c6cf'))
        p.drawEllipse(QRectF(x, rect.top() + 3, 12, 12))
        if self.hasFocus():
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor('#f2eaff'), 1))
            p.drawRoundedRect(rect.adjusted(.5, .5, -.5, -.5), 8.5, 8.5)


class CompactSpinBox(QSpinBox):
    """Quiet chevrons; Qt still handles ranges, stepping, and text editing."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setStyleSheet('QSpinBox {padding-right:24px;}QSpinBox::up-button,QSpinBox::down-button {width:20px;border:0;background:transparent;}QSpinBox::up-arrow,QSpinBox::down-arrow {image:none;width:0;height:0;}')

    def paintEvent(self, event):
        super().paintEvent(event)
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for control, flag, direction in ((QStyle.SC_SpinBoxUp, QAbstractSpinBox.StepUpEnabled, -1), (QStyle.SC_SpinBoxDown, QAbstractSpinBox.StepDownEnabled, 1)):
            rect = self.style().subControlRect(QStyle.CC_SpinBox, option, control, self)
            center = QRectF(rect).center()
            available = self.isEnabled() and bool(self.stepEnabled() & flag)
            p.setPen(QPen(QColor('#aaa7b6' if available else '#605e6c'), 1.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            path = QPainterPath(center + QPointF(-2.5, -direction))
            path.lineTo(center + QPointF(0, direction * 1.5))
            path.lineTo(center + QPointF(2.5, -direction))
            p.drawPath(path)


class AdvancedSection(QWidget):
    """A compact disclosure preserving all fields while they are collapsed."""
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        self.toggle = QToolButton()
        self.toggle.setText('Advanced')
        self.toggle.setCheckable(True)
        self.toggle.setArrowType(Qt.RightArrow)
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.setAccessibleName('Show advanced settings')
        layout.addWidget(self.toggle, 0, Qt.AlignLeft)
        self.content = QWidget()
        self.form = QFormLayout(self.content)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setHorizontalSpacing(18)
        self.form.setVerticalSpacing(9)
        self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addWidget(self.content)
        self.content.hide()
        self.toggle.toggled.connect(self.set_expanded)

    def set_expanded(self, expanded):
        self.content.setVisible(expanded)
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.toggle.setAccessibleName('Hide advanced settings' if expanded else 'Show advanced settings')


def dark_titlebar(widget):
    import sys
    if sys.platform != 'win32':
        return
    import ctypes
    try:
        setter = ctypes.windll.dwmapi.DwmSetWindowAttribute
        setter.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        hwnd = ctypes.c_void_p(int(widget.winId()))
        enabled = ctypes.c_int(1)
        if setter(hwnd, 20, ctypes.byref(enabled), 4):
            setter(hwnd, 19, ctypes.byref(enabled), 4)
        background = ctypes.c_uint(0x1f1c1c)
        setter(hwnd, 35, ctypes.byref(background), 4)
    except (AttributeError, OSError):
        pass


def icon():
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor('#8d77ce'))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(1, 1, 62, 62, 18, 18)
    p.setPen(QPen(Qt.white, 5, Qt.SolidLine, Qt.RoundCap))
    for i, h in enumerate((13, 25, 36, 25, 13)):
        p.drawLine(17 + i * 8, 32 - h // 2, 17 + i * 8, 32 + h // 2)
    p.end()
    return QIcon(pix)


class Wave(QWidget):
    """Nine actual 100 ms audio levels; only demo mode creates sample levels."""
    DEMO_LEVELS = (.08, .18, .38, .62, .34, .12, .04, .22, .48, .74, .42, .16)
    STALE_AFTER = .25
    FADE_DURATION = .25

    def __init__(self, clock=None):
        super().__init__()
        self.setFixedSize(40, 20)
        self._clock = clock or time.monotonic
        self._history = deque([0.] * 9, maxlen=9)
        self._last_frame = None
        self._demo_at = None
        self._demo_index = 0
        self.active = False
        self.demo = False
        self.setToolTip('Microphone level · last 0.9 seconds')
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(50)

    def set_recording(self, active, demo=False):
        active, demo = bool(active), bool(demo)
        if (active, demo) == (self.active, self.demo):
            return
        self.active, self.demo = active, demo
        self._history = deque([0.] * 9, maxlen=9)
        self._last_frame = None
        self._demo_at = self._clock() if active and demo else None
        self._demo_index = 0
        self.setToolTip('Demo · simulated waveform' if demo else 'Microphone level · last 0.9 seconds')
        self.update()

    def feed_level(self, level):
        if not self.active or self.demo:
            return
        level = float(level)
        self._append_level(max(0., min(1., level)) if math.isfinite(level) else 0.)

    def _append_level(self, level):
        now = self._clock()
        # Do not resurrect old audio when frames resume after an interruption.
        if self._last_frame is not None and now - self._last_frame > self.STALE_AFTER:
            self._history = deque(self.display_levels(), maxlen=9)
        self._history.append(level)
        self._last_frame = now
        self.update()

    def display_levels(self):
        if not self.active or self._last_frame is None:
            return (0.,) * 9
        age = max(0., self._clock() - self._last_frame)
        factor = max(0., 1. - max(0., age - self.STALE_AFTER) / self.FADE_DURATION)
        return tuple(level * factor for level in self._history)

    def tick(self):
        if self.active and self.demo:
            now = self._clock()
            if now - self._demo_at >= .1:
                self._append_level(self.DEMO_LEVELS[self._demo_index % len(self.DEMO_LEVELS)])
                self._demo_index += 1
                self._demo_at = now
        if self.active:
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor('#eeeaf5' if self.active else '#80778f'), 2.6, Qt.SolidLine, Qt.RoundCap))
        for i, level in enumerate(self.display_levels()):
            h = level * 16
            x = 3 + i * 4.2
            if h:
                p.drawLine(QPointF(x, 10 - h / 2), QPointF(x, 10 + h / 2))
            else:
                p.drawPoint(QPointF(x, 10))


class ProcessingMark(QWidget):
    """Event-based step progress, painted by the capsule behind its content."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(0, 0)
        self.hide()
        self.running = False
        self.completed_steps = 0
        self.total_steps = 1
        self.fraction = 0.
        self._display_fraction = 0.
        self.animation = QPropertyAnimation(self, b'display_fraction', self)
        self.animation.setDuration(180)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)

    def _get_display_fraction(self):
        return self._display_fraction

    def _set_display_fraction(self, value):
        self._display_fraction = max(0., min(1., float(value)))
        if self.parentWidget() is not None:
            self.parentWidget().update()

    display_fraction = Property(float, _get_display_fraction, _set_display_fraction)

    @property
    def percentage(self):
        return int(round(self.fraction * 100))

    def set_progress(self, completed_steps, total_steps, *, animate=True):
        self.total_steps = max(1, int(total_steps))
        self.completed_steps = max(0, min(self.total_steps, int(completed_steps)))
        target = self.completed_steps / self.total_steps
        if target == self.fraction and self.animation.state() == QPropertyAnimation.Running:
            return
        self.fraction = target
        self.animation.stop()
        if animate and self.running and target != self._display_fraction:
            self.animation.setStartValue(self._display_fraction)
            self.animation.setEndValue(target)
            self.animation.start()
        else:
            self._set_display_fraction(target)

    def set_running(self, running):
        self.running = bool(running)
        if not self.running:
            self.animation.stop()
            self._set_display_fraction(self.fraction)


class Bubble(QWidget):
    toggle = Signal()
    ask = Signal()
    cancel = Signal()
    open_main = Signal()
    STATE_NAMES = {'待机': 'Ready', 'idle': 'Ready', 'ready': 'Ready', '启动': 'Starting', 'startup': 'Starting', 'starting': 'Starting', '录音': 'Recording', 'recording': 'Recording', '等待停止': 'Stopping', 'waiting': 'Stopping', 'stopping': 'Stopping', '停止': 'Stopping', '识别': 'Transcribing', 'transcribing': 'Transcribing', 'recognizing': 'Transcribing', '整理': 'Refining', 'refining': 'Refining', '完成': 'Done', 'done': 'Done', 'result': 'Done', '失败': 'Failed', 'failed': 'Failed', 'error': 'Failed', 'cancel': 'Ready', 'cancelled': 'Ready'}

    def __init__(self, cfg):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.cfg = cfg
        self.session_kind = ''
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_actions)
        self.setFixedSize(self.configured_width(), 36)
        self._processing = False
        self._state_name = 'Ready'
        self._event_progress = False
        self._progress_step = 'Starting'
        self._detail = ''
        self._demo = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 4, 7, 4)
        layout.setSpacing(5)
        self.brand = button('', self.open_main.emit)
        self.brand.setIcon(line_icon('waveform', 13, '#c7b8fa'))
        self.brand.setToolTip('Open MurMur')
        self.brand.hide()
        self.wave = Wave()
        self.progress = ProcessingMark(self)
        self.status = QLabel('Ready')
        self.status.setStyleSheet('color:#eeeaf7;font-size:11px;')
        self.status.setMinimumWidth(0)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.percentage = QLabel('0%')
        self.percentage.setFixedWidth(29)
        self.percentage.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.percentage.setStyleSheet('color:#ddd3f6;font-size:11px;font-weight:600;')
        self.percentage.hide()
        self.mic = button('', self.toggle.emit)
        self.mic.setIcon(line_icon('mic', 13, '#ddd3f6'))
        self.mic.setToolTip('Start recording')
        self.close = button('', self.cancel.emit)
        self.close.setIcon(line_icon('close', 12, '#a4a0ad'))
        self.close.setToolTip('Cancel')
        self.close.setAccessibleName('Cancel current session')
        for w in (self.brand, self.mic, self.close):
            w.setFixedSize(22, 22)
            w.setIconSize(QSize(13, 13))
            w.setFocusPolicy(Qt.NoFocus)
            w.setStyleSheet('QPushButton{background:transparent;border:0;border-radius:7px;padding:0;min-height:0;}QPushButton:hover{background:#3e354c;}')
        layout.addWidget(self.close)
        layout.addWidget(self.wave)
        layout.addWidget(self.status, 1)
        layout.addWidget(self.percentage)
        layout.addWidget(self.mic)

    def configured_width(self):
        return max(156, min(180, int(self.cfg.get('bubble_width', 168))))

    def set_session_kind(self,kind):
        self.session_kind=kind

    def show_actions(self,point):
        menu=QMenu(self)
        action=menu.addAction('Stop Ask Anything' if self.session_kind else 'Ask Anything',self.ask.emit)
        action.setEnabled(not self.isVisible() or bool(self.session_kind) and self.wave.active)
        menu.addAction('Open MurMur',self.open_main.emit)
        menu.addAction('Cancel',self.cancel.emit)
        menu.exec(self.mapToGlobal(point))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        clip = QPainterPath()
        clip.addRoundedRect(rect, 17, 17)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor('#242128'))
        p.drawPath(clip)
        if self._processing:
            p.save()
            p.setClipPath(clip)
            p.fillRect(QRectF(rect.left(), rect.top(), rect.width() * self.progress.display_fraction, rect.height()), QColor('#514269'))
            p.restore()
        p.setPen(QPen(QColor('#625276' if self._processing else '#48404f'), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(clip)

    def set_progress(self, step, completed_steps, total_steps):
        """Report completed pipeline steps, never model-internal progress."""
        aliases = {'Transcribing': 'Transcribe', 'Refining': 'Polish', '听写': 'Polish', '翻译': 'Translate', '润色': 'Refine', '总结': 'Summarize', '扩写': 'Expand', '自定义': 'Edit', '语音指令': 'Edit'}
        step = aliases.get(str(step), str(step))
        allowed = {'Starting', 'Stopping', 'Transcribe', 'Polish', 'Translate', 'Respond', 'Refine', 'Summarize', 'Expand', 'Edit'}
        self._progress_step = step if step in allowed else 'Transcribe'
        self._event_progress = True
        self.progress.set_progress(completed_steps, total_steps)
        if self._processing:
            self._update_processing_text()
        self.update()

    def _update_processing_text(self):
        step = self._progress_step
        if self._demo:
            self.status.setText(f'<span style="font-size:11px">{step}</span><br><span style="font-size:9px;color:#c7b8fa">Demo</span>')
        else:
            self.status.setText(step)
        self.percentage.setText(f'{self.progress.percentage}%')
        tooltip = ('Demo · simulated session · ' if self._demo else '') + step
        if self._detail:
            tooltip += ' · ' + self._detail
        if self.session_kind:
            tooltip = self.session_kind + ' · ' + tooltip
        tooltip += f' · Completed processing steps: {self.progress.completed_steps} of {self.progress.total_steps} ({self.progress.percentage}%). Not model-internal progress.'
        self.status.setToolTip(tooltip)
        self.percentage.setToolTip(tooltip)
        self.status.setAccessibleName(('Demo · ' if self._demo else '') + f'{step} · {self.progress.percentage}% of processing steps complete')
        self.percentage.setAccessibleName(f'{self.progress.percentage}% of processing steps complete')
        self.setAccessibleName(self.status.accessibleName())
        self.setToolTip(tooltip)

    def position(self):
        self.setFixedSize(self.configured_width(), 36)
        screens = QApplication.screens()
        if not screens:
            return
        screen = screens[max(0, min(int(self.cfg.get('bubble_screen', 0)), len(screens) - 1))]
        rect = screen.availableGeometry()
        offset = max(0, int(self.cfg.get('bubble_offset', 48)))
        y = rect.bottom() - self.height() - offset if self.cfg.get('bubble_position', 'bottom') == 'bottom' else rect.top() + offset
        y = max(rect.top(), min(y, rect.bottom() - self.height()))
        self.move(rect.center().x() - self.width() // 2, y)

    def state(self, state, detail='', demo=False):
        name = self.STATE_NAMES.get(state, state)
        visible = name in ('Starting', 'Recording', 'Stopping', 'Transcribing', 'Refining')
        changed = name != self._state_name
        self._state_name, self._detail, self._demo = name, detail, bool(demo)
        self.wave.set_recording(name == 'Recording', demo=demo)
        self._processing = visible and name != 'Recording'
        self.progress.set_running(self._processing)
        self.percentage.setVisible(self._processing)
        self.wave.setVisible(name == 'Recording')
        self.status.setAlignment(Qt.AlignCenter if self._processing else Qt.AlignLeft | Qt.AlignVCenter)
        if not visible or name == 'Recording':
            self._event_progress = False
            self.progress.set_progress(0, 1, animate=False)
        elif changed and not self._event_progress:
            self._progress_step = {'Transcribing': 'Transcribe', 'Refining': 'Polish'}.get(name, name)
            self.progress.set_progress(1 if name == 'Refining' else 0, 2, animate=False)
        timing = re.search(r'\b\d{1,2}:\d{2}\b', detail) if self.wave.active else None
        display = timing.group() if timing else name
        if demo:
            self.status.setText(f'<span style="font-size:11px">{display}</span><br><span style="font-size:9px;color:#b5a2df">Demo</span>')
        else:
            self.status.setText(display)
        self.mic.setVisible(name == 'Recording')
        self.mic.setEnabled(name == 'Recording')
        self.mic.setIcon(line_icon('check', 13, '#fcfaff'))
        self.mic.setToolTip('Stop recording' if name == 'Recording' else 'Recording is not active')
        self.mic.setAccessibleName('Stop recording')
        tooltip = ('Demo · simulated session · ' if demo else '') + name + (' · ' + detail if detail else '')
        if self.session_kind:tooltip=self.session_kind+' · '+tooltip
        if demo and self.wave.active:
            tooltip += ' · simulated waveform'
        self.status.setToolTip(tooltip)
        self.status.setAccessibleName(('Demo · ' if demo else '') + name)
        self.setAccessibleName(self.status.accessibleName())
        self.setToolTip(self.status.toolTip())
        if self._processing:
            self._update_processing_text()
        self.update()
        if visible != self.isVisible():
            self.show() if visible else self.hide()


class ResultBubble(QWidget):
    """A selectable result beside the capsule; editing is an explicit action."""
    edit_requested = Signal(str)

    def __init__(self, cfg):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.cfg = cfg
        self.text = ''
        self._display_text = ''
        self.demo = False
        self._morph_generation = 0
        self._morph = None
        self._target_geometry = QRect()
        self.setFixedWidth(360)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSizeConstraint(QLayout.SetNoConstraint)
        self.contents = QWidget()
        outer.addWidget(self.contents)
        self.body = QVBoxLayout(self.contents)
        self.body.setSizeConstraint(QLayout.SetNoConstraint)
        self.body.setContentsMargins(12, 9, 12, 9)
        self.body.setSpacing(7)
        self.status = label('Result ready', 'muted')
        self.status.setWordWrap(False)
        self.status.setStyleSheet('font-size:11px;color:#b9aecb;')
        self.body.addWidget(self.status)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFocusPolicy(Qt.NoFocus)
        self.preview.setContextMenuPolicy(Qt.NoContextMenu)
        self.preview.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.preview.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.preview.setStyleSheet('QPlainTextEdit{border:0;background:transparent;padding:0;color:#eeeaf4;}')
        self.body.addWidget(self.preview)
        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.copy_button = button('Copy', self.copy_result)
        self.copy_button.setToolTip('Copy the full result')
        self.edit_button = button('Edit', self.edit_result)
        self.edit_button.setToolTip('Open the editor')
        self.dismiss_button = button('Dismiss', self.hide)
        for control in (self.copy_button, self.edit_button, self.dismiss_button):
            control.setFocusPolicy(Qt.NoFocus)
            control.setStyleSheet('QPushButton{padding:3px 9px;min-height:18px;}')
        actions.addWidget(self.copy_button)
        actions.addWidget(self.edit_button)
        actions.addStretch()
        actions.addWidget(self.dismiss_button)
        self.body.addLayout(actions)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor('#51465f'), 1))
        painter.setBrush(QColor('#28242e'))
        radius = 13
        if self._morph is not None and self._target_geometry.height() > 36:
            expanded = max(0., min(1., (self.height() - 36) / (self._target_geometry.height() - 36)))
            radius = 17 - 4 * expanded
        painter.drawRoundedRect(1, 1, self.width() - 2, self.height() - 2, radius, radius)

    def copy_result(self):
        if not self.text.strip():
            return
        QApplication.clipboard().setText(self.text)
        self.status.setText(('Demo · ' if self.demo else '') + 'Copied to clipboard')
        self.status.setToolTip(self.status.text())

    def show_result(self, text, *, demo=False, status='Result ready', source=None, status_summary=None):
        if not text.strip():
            self.text = self._display_text = ''
            self.hide()
            return
        self._show_content(text, text, demo=demo, status=status, source=source, status_summary=status_summary)

    def edit_result(self):
        if self.text.strip():
            self.edit_requested.emit(self.text)

    def show_error(self, message, original_text='', *, demo=False, source=None, status='Processing failed', status_summary=None):
        """Show a diagnostic, keeping recovered text separate from the message."""
        message = message.strip() or 'The operation failed. Try recording again.'
        recovered = original_text if original_text.strip() else ''
        display = message + ('\n\nOriginal transcript:\n' + recovered if recovered else '')
        self._show_content(display, recovered, demo=demo, status=status, source=source,
                           status_summary=status_summary, error_message=message)

    def _show_content(self, display_text, copy_text, *, demo, status, source, status_summary, error_message=''):
        self._cancel_morph()
        self.setFixedWidth(360)
        self.text = copy_text
        self._display_text = display_text
        self.demo = bool(demo)
        recoverable = bool(copy_text.strip())
        for control in (self.copy_button, self.edit_button):
            control.setVisible(recoverable)
            control.setEnabled(recoverable)
        self.copy_button.setToolTip('Copy the original transcript' if error_message else 'Copy the full result')
        self.edit_button.setText('Review' if error_message else 'Edit')
        self.edit_button.setToolTip('Review the original transcript and retry refinement in the editor' if error_message else 'Open the editor')
        self.preview.setPlainText(display_text)
        prefix = 'Demo · ' if demo else ''
        self.status.setText(prefix + (status_summary or status))
        self.status.setToolTip(prefix + status + (' · ' + error_message if error_message else ''))
        self.status.setStyleSheet('font-size:11px;color:' + ('#e4b1ae;' if error_message else '#b9aecb;'))
        bounds = self.preview.fontMetrics().boundingRect(QRect(0, 0, self.width() - 34, 100000), Qt.TextWordWrap, display_text)
        self.preview.setFixedHeight(max(32, min(94, bounds.height() + 18)))
        self.setFixedHeight(min(180, self.body.sizeHint().height()))
        self.position()
        self._target_geometry = QRect(self.geometry())
        if source is not None:
            self.morph_from(source)
        elif not self.isVisible():
            self.show()

    def _cancel_morph(self):
        self._morph_generation += 1
        if self._morph is not None:
            self._morph.stop()
            self._morph.deleteLater()
            self._morph = None
        self.contents.setGraphicsEffect(None)

    def hide(self):
        self._cancel_morph()
        super().hide()

    def hideEvent(self, event):
        self._cancel_morph()
        super().hideEvent(event)

    def morph_from(self, source):
        if not self._display_text.strip():
            return
        start = QRect(source.geometry() if isinstance(source, QWidget) else source)
        target = QRect(self._target_geometry if not self._target_geometry.isEmpty() else self.geometry())
        self._cancel_morph()
        generation = self._morph_generation
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.setGeometry(start)
        effect = QGraphicsOpacityEffect(self.contents)
        effect.setOpacity(0.)
        self.contents.setGraphicsEffect(effect)
        animation = QParallelAnimationGroup(self)
        geometry = QPropertyAnimation(self, b'geometry', animation)
        geometry.setDuration(240)
        geometry.setStartValue(start)
        geometry.setEndValue(target)
        geometry.setEasingCurve(QEasingCurve.OutCubic)
        opacity = QPropertyAnimation(effect, b'opacity', animation)
        opacity.setDuration(240)
        opacity.setStartValue(0.)
        opacity.setEndValue(1.)
        opacity.setEasingCurve(QEasingCurve.InCubic)
        animation.addAnimation(geometry)
        animation.addAnimation(opacity)
        self._morph = animation

        def finished():
            if generation == self._morph_generation and self._morph is animation:
                self._morph = None
                self.setFixedSize(target.size())
                self.setGeometry(target)
                self.contents.setGraphicsEffect(None)
            animation.deleteLater()

        animation.finished.connect(finished)
        if not self.isVisible():
            self.show()
        animation.start()

    def position(self):
        screens = QApplication.screens()
        if not screens:
            return
        index = max(0, min(int(self.cfg.get('bubble_screen', 0)), len(screens) - 1))
        rect = screens[index].availableGeometry()
        self.setFixedWidth(min(360, rect.width() - 16))
        offset = max(0, int(self.cfg.get('bubble_offset', 48)))
        y = rect.bottom() - self.height() - offset if self.cfg.get('bubble_position', 'bottom') == 'bottom' else rect.top() + offset
        x = rect.center().x() - self.width() // 2
        self.move(max(rect.left(), min(x, rect.right() - self.width() + 1)), max(rect.top(), min(y, rect.bottom() - self.height() + 1)))


class Preview(QDialog):
    submit = Signal(str, str, str)
    replace = Signal(str)
    voice = Signal()
    cancel = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('MurMur · Edit selection')
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.WindowSystemMenuHint
                            | Qt.WindowCloseButtonHint | Qt.MSWindowsFixedSizeDialogHint)
        self.setFixedSize(680, 440)
        self.setSizeGripEnabled(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        self.title_label=label('Edit selection', 'title')
        layout.addWidget(self.title_label)
        self.notice = label('Review your changes before applying or copying.', 'muted')
        layout.addWidget(self.notice)
        row = QHBoxLayout()
        row.setSpacing(7)
        self.mode = CompactComboBox()
        for text, mode in [('Refine', '润色'), ('Translate', '翻译'), ('Summarize', '总结'), ('Expand', '扩写'), ('Custom', '自定义')]:
            self.mode.addItem(text, mode)
        self.mode.setMinimumWidth(105)
        row.addWidget(self.mode)
        self.command = QLineEdit()
        self.command.setPlaceholderText('Add an instruction…')
        row.addWidget(self.command, 1)
        self.voice_button = button('', self.voice.emit)
        self.voice_button.setIcon(line_icon('mic'))
        self.voice_button.setToolTip('Dictate an instruction')
        self.voice_button.setAccessibleName('Dictate an instruction')
        self.voice_button.setFixedWidth(34)
        row.addWidget(self.voice_button)
        self.go = button('Generate', lambda: self.submit.emit(self.raw.toPlainText(), self.mode.currentData(), self.command.text()), True)
        row.addWidget(self.go)
        layout.addLayout(row)
        texts = QHBoxLayout()
        texts.setSpacing(10)
        left = QVBoxLayout()
        right = QVBoxLayout()
        self.original_label=label('Original', 'muted')
        left.addWidget(self.original_label)
        right.addWidget(label('Preview', 'muted'))
        self.raw = QPlainTextEdit()
        self.raw.setPlaceholderText('Select text in another app, or paste it here.')
        self.result = QPlainTextEdit()
        self.result.setPlaceholderText('Your result will appear here.')
        self._replacement_allowed = False
        self._session_busy = False
        self.editor_context = 'selection'
        for edit in (self.raw, self.result):
            edit.setTabChangesFocus(True)
        left.addWidget(self.raw)
        right.addWidget(self.result)
        texts.addLayout(left)
        texts.addLayout(right)
        layout.addLayout(texts, 1)
        actions = QHBoxLayout()
        actions.addWidget(button('Cancel', self.reject))
        actions.addStretch()
        copy = button('Copy', self.copy_result)
        copy.setIcon(line_icon('copy', 14))
        self.copy_button = copy
        copy.setEnabled(False)
        actions.addWidget(copy)
        self.replace_button = button('Apply to selection', self.apply_result, True)
        self.replace_button.setEnabled(False)
        actions.addWidget(self.replace_button)
        layout.addLayout(actions)
        self.result.textChanged.connect(self.update_result_actions)

    def update_result_actions(self):
        has_result = bool(self.result.toPlainText().strip()) and not self._session_busy
        self.copy_button.setEnabled(has_result)
        self.replace_button.setEnabled(has_result and self._replacement_allowed)

    def copy_result(self):
        text = self.result.toPlainText()
        if text.strip() and not self._session_busy:
            QApplication.clipboard().setText(text)

    def apply_result(self):
        text = self.result.toPlainText()
        if text.strip() and self._replacement_allowed and not self._session_busy:
            self.replace.emit(text)

    def set_session_state(self, phase=None, mode=None):
        aliases = {'启动': 'startup', 'starting': 'startup', '录音': 'recording', '等待停止': 'stopping', 'waiting': 'stopping', '识别': 'transcribing', 'recognizing': 'transcribing', '整理': 'refining'}
        phase = aliases.get(phase, phase.lower() if isinstance(phase, str) else 'idle')
        idle = phase in ('待机', '完成', '失败', '取消', 'idle', 'ready', 'done', 'result', 'failed', 'error', 'cancel', 'cancelled', 'canceled', '')
        self._session_busy = not idle
        recording_instruction = phase in ('startup', 'recording') and mode in ('指令', '语音指令', 'instruction')
        for edit in (self.raw, self.result):
            edit.setReadOnly(not idle)
        self.mode.setEnabled(idle)
        self.command.setEnabled(idle)
        self.go.setEnabled(idle)
        self.go.setText('Generate' if idle or phase in ('startup', 'recording') else 'Processing…')
        self.voice_button.setEnabled(idle or recording_instruction)
        self.voice_button.setIcon(line_icon('stop' if recording_instruction else 'mic'))
        self.voice_button.setToolTip('Stop recording' if recording_instruction else 'Dictate an instruction' if idle else 'Wait for the current session. Esc cancels.')
        self.voice_button.setAccessibleName('Stop recording' if recording_instruction else 'Dictate an instruction')
        self.update_result_actions()

    def show_text(self, raw, result='', notice='', replace=False, show=True, assistant=False, result_edit=False):
        self.editor_context = 'assistant' if assistant else 'result' if result_edit else 'selection'
        self.title_label.setText('Ask Anything result' if assistant else 'Edit result' if result_edit else 'Edit selection')
        self.original_label.setText('Spoken request and source' if assistant else 'Original transcript' if result_edit else 'Original')
        self.setWindowTitle('MurMur · Ask Anything' if assistant else 'MurMur · Edit result' if result_edit else 'MurMur · Edit selection')
        selection_context = not (result_edit or assistant)
        self._replacement_allowed = bool(replace) and selection_context
        self.replace_button.setVisible(selection_context)
        self.raw.setPlainText(raw)
        self.result.setPlainText(result)
        self.notice.setText(notice or 'Review your changes before applying or copying.')
        self.update_result_actions()
        if show:
            self.show()
            self.raise_()
            self.activateWindow()

    def showEvent(self, event):
        super().showEvent(event)
        dark_titlebar(self)

    def reject(self):
        if self._session_busy:
            self.cancel.emit()
            return
        super().reject()


class SettingsForm(QMainWindow):
    record = Signal()
    translate = Signal()
    preview = Signal()
    save_settings = Signal(dict, dict)
    quit_requested = Signal()

    def navigate(self, index):
        previous_animation = getattr(self, '_page_animation', None)
        if previous_animation:
            previous_animation.stop()
            previous_animation.deleteLater()
            self._page_animation = None
        previous_page = getattr(self, '_animated_page', None)
        if previous_page:
            previous_page.setGraphicsEffect(None)
            self._animated_page = None
        changed = self.stack.currentIndex() != index
        self.stack.setCurrentIndex(index)
        for i, b in enumerate(self.nav_buttons):
            b.setChecked(i == index)
        self.refresh()
        if changed and self.isVisible():
            page = self.stack.currentWidget()
            effect = QGraphicsOpacityEffect(page)
            effect.setOpacity(.35)
            page.setGraphicsEffect(effect)
            animation = QPropertyAnimation(effect, b'opacity', self)
            animation.setDuration(160)
            animation.setStartValue(.35)
            animation.setEndValue(1.)
            animation.setEasingCurve(QEasingCurve.OutCubic)
            self._animated_page = page
            self._page_animation = animation

            def finished():
                if self._page_animation is animation:
                    page.setGraphicsEffect(None)
                    self._animated_page = None
                    self._page_animation = None
                animation.deleteLater()

            animation.finished.connect(finished)
            animation.start()

    def field(self, layout, key, title, kind='text', options=None):
        value = self.store.config.get(key) if kind == 'price' else self.store.config[key]
        if kind == 'bool':
            w = CheckedBox(title)
            w.setChecked(value)
            layout.addRow(w)
        elif kind == 'long':
            w = QPlainTextEdit(value)
            w.setMaximumHeight(110)
            layout.addRow(title, w)
        elif kind == 'int':
            w = CompactSpinBox()
            w.setRange(0, 3650)
            w.setValue(value)
            layout.addRow(title, w)
        elif kind == 'choice':
            w = CompactComboBox()
            for text, data in options:
                w.addItem(text, data)
            w.setCurrentIndex(max(0, w.findData(value)))
            layout.addRow(title, w)
        elif kind == 'price':
            w = QLineEdit('' if value is None else str(value))
            w.setProperty('usd_price', True)
            validator = QDoubleValidator(0., 1e12, 8, w)
            validator.setNotation(QDoubleValidator.StandardNotation)
            validator.setLocale(QLocale.c())
            w.setValidator(validator)
            w.setPlaceholderText('Optional')
            layout.addRow(title, w)
        else:
            w = QLineEdit(str(value))
            layout.addRow(title, w)
        w.setAccessibleName(title)
        if kind != 'bool':
            w.setMinimumWidth(0)
            w.setMaximumWidth(480)
        self.fields[key] = w
        return w

    def _settings_snapshot(self):
        values = {}
        for key, w in self.fields.items():
            values[key] = w.isChecked() if isinstance(w, QCheckBox) else w.currentData() if isinstance(w, QComboBox) else w.value() if isinstance(w, QSpinBox) else w.toPlainText() if isinstance(w, QPlainTextEdit) else self.price_value(w) if w.property('usd_price') else w.text().strip()
        values['prompts'] = {k: w.toPlainText() for k, w in self.prompt_fields.items()}
        secrets = {}
        for name, attribute in [('asr', 'asr_key'), ('llm', 'llm_key'), ('ask_llm', 'ask_llm_key'), ('ali_appkey', 'ali_appkey'), ('ali_token', 'ali_token')]:
            field = getattr(self, attribute, None)
            secrets[name] = field.text() if field is not None else ''
        return values, secrets

    @staticmethod
    def price_value(field):
        try:
            value = float(field.text())
            return value if math.isfinite(value) and value >= 0 else None
        except ValueError:
            return None

    def validate_price_fields(self):
        for field in self.fields.values():
            if field.property('usd_price') and field.text().strip() and not field.hasAcceptableInput():
                self.settings_status.setText('Enter a non-negative USD price in Advanced, or leave it blank.')
                return False
        return True

    def save(self):
        update = getattr(self, 'update_settings_actions', None)
        if update and not update():
            self.settings_status.setText('Finish the current session or connection test first.')
            return
        if not self.validate_price_fields():
            return
        self.save_settings.emit(*self._settings_snapshot())

    def clear_keys(self):
        update = getattr(self, 'update_settings_actions', None)
        if update and not update():
            self.settings_status.setText('Finish the current session or connection test first.')
            return
        from .storage import credential, credential_lock
        failed = False
        with credential_lock:
            for name in ('asr', 'llm', 'ask_llm', 'ali_appkey', 'ali_token', 'ali_access_key_id', 'ali_access_key_secret', 'ali_token_expiry', 'asr_openai_key', 'asr_groq_key', 'asr_http_key'):
                try:
                    credential(name, '')
                except Exception:
                    failed = True
        for attribute in ('asr_key', 'llm_key', 'ask_llm_key', 'ali_appkey', 'ali_token', 'asr_http_key'):
            field = getattr(self, attribute, None)
            if field is not None:
                field.clear()
        if hasattr(self, '_http_asr_keys'):
            self._http_asr_keys={key:'' for key in self._http_asr_keys}
        refresh = getattr(self, 'update_credential_status', None)
        if refresh:
            refresh()
        invalidate = getattr(self, 'invalidate_service_test', None)
        if invalidate:
            for kind in ('asr', 'llm', 'ask'):
                invalidate(kind)
        if not failed:
            QMessageBox.information(self, 'MurMur', 'Saved API keys, AppKeys, AccessKeys and access tokens have been removed.')
        else:
            QMessageBox.warning(self, 'API keys', 'Could not remove all saved credentials. Try again.')

    def clear_ask_key(self):
        update = getattr(self, 'update_settings_actions', None)
        if update and not update():
            self.settings_status.setText('Finish the current session or connection test first.')
            return
        from .storage import credential, credential_lock
        failed = False
        with credential_lock:
            try:credential('ask_llm', '')
            except Exception:failed = True
        field = getattr(self, 'ask_llm_key', None)
        if field is not None:
            previous = field.blockSignals(True)
            try:field.clear()
            finally:field.blockSignals(previous)
        refresh = getattr(self, 'update_credential_status', None)
        if refresh:refresh()
        invalidate = getattr(self, 'invalidate_service_test', None)
        if invalidate:invalidate('ask')
        self.settings_status.setText('Could not remove the Ask Anything key. Try again.' if failed else 'Ask Anything key removed.')

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def showEvent(self, event):
        super().showEvent(event)
        dark_titlebar(self)

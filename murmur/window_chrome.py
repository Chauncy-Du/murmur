"""In-content window controls and a sliding sidebar cutout."""
from PySide6.QtCore import Qt,QObject,QEvent,Property,QPropertyAnimation,QEasingCurve,QTimer,QSize
from PySide6.QtGui import QPainter,QPainterPath,QColor
from PySide6.QtWidgets import QFrame,QWidget,QHBoxLayout,QToolButton,QApplication,QAbstractButton,QComboBox,QAbstractSpinBox,QLineEdit,QAbstractItemView,QScrollBar
from .ui import line_icon


def window_controls(window):
    if not hasattr(window,'corner_controls'):window.corner_controls=CornerControls(window)
    # Keep title/account content clear of the fixed corner controls.
    reserve=QWidget();reserve.setFixedSize(52,24);return reserve


class CornerControls(QWidget):
    def __init__(self,window):
        super().__init__(window.centralWidget());self.setFixedSize(52,24)
        row=QHBoxLayout(self);row.setContentsMargins(0,0,0,0);row.setSpacing(2)
        for name,tip,callback in (('minimize','Minimize MurMur',window.showMinimized),('close','Hide MurMur to tray',window.close)):
            b=QToolButton();b.setFixedSize(24,24);b.setIcon(line_icon(name,13));b.setToolTip(tip);b.setAccessibleName(tip)
            b.clicked.connect(callback);row.addWidget(b)
        window.centralWidget().installEventFilter(self)
        self.place()
    def place(self):
        self.move(self.parentWidget().width()-self.width()-8,8);self.raise_()
    def eventFilter(self,watched,event):
        if event.type() in (QEvent.Resize,QEvent.Show,QEvent.LayoutRequest):self.place()
        return super().eventFilter(watched,event)


class WindowDrag(QObject):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.offset=None
        QApplication.instance().installEventFilter(self)

    def finish(self):
        self.offset=None
        if QWidget.mouseGrabber() is self.window:self.window.releaseMouse()

    def eventFilter(self,watched,event):
        if not isinstance(watched,QWidget) or watched.window() is not self.window:return False
        kind=event.type()
        if watched is self.window and kind in (QEvent.Hide,QEvent.WindowDeactivate):self.finish()
        if kind==QEvent.MouseButtonPress and event.button()==Qt.LeftButton:
            point=self.window.mapFromGlobal(event.globalPosition().toPoint())
            if point.y()>82:return False
            current=watched
            while current and current is not self.window:
                if isinstance(current,(QAbstractButton,QComboBox,QAbstractSpinBox,QLineEdit,QAbstractItemView,QScrollBar)):return False
                current=current.parentWidget()
            # Keep the entire drag in Qt logical coordinates. Do not enter a
            # second native window-move loop or install a separate drag cursor.
            self.offset=event.globalPosition().toPoint()-self.window.pos()
            self.window.grabMouse();return True
        if kind==QEvent.MouseMove and self.offset is not None:
            if not event.buttons() & Qt.LeftButton:self.finish();return False
            self.window.move(event.globalPosition().toPoint()-self.offset);return True
        if kind==QEvent.MouseButtonRelease and event.button()==Qt.LeftButton and self.offset is not None:self.finish();return True
        return False


class NavigationSidebar(QFrame):
    def __init__(self):
        super().__init__();self._top=0.;self.active=None
        self.slide=QPropertyAnimation(self,b'highlightTop',self);self.slide.setDuration(190);self.slide.setEasingCurve(QEasingCurve.OutCubic)

    def get_top(self):return self._top
    def set_top(self,value):self._top=value;self.update()
    highlightTop=Property(float,get_top,set_top)

    def select(self,button,animate=True):
        self.slide.stop();self.active=button;target=float(button.y())
        if animate and self.isVisible() and self._top:
            self.slide.setStartValue(self._top);self.slide.setEndValue(target);self.slide.start()
        else:self.set_top(target)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.active:self.select(self.active,False)

    def paintEvent(self,event):
        super().paintEvent(event)
        if not self.active:return
        x=8.;right=float(self.width());top=self._top;bottom=top+self.active.height();r=12.
        path=QPainterPath();path.moveTo(right,top-r);path.quadTo(right,top,right-r,top)
        path.lineTo(x+r,top);path.quadTo(x,top,x,top+r);path.lineTo(x,bottom-r);path.quadTo(x,bottom,x+r,bottom)
        path.lineTo(right-r,bottom);path.quadTo(right,bottom,right,bottom+r);path.closeSubpath()
        painter=QPainter(self);painter.setRenderHint(QPainter.Antialiasing);painter.fillPath(path,QColor('#1c1c1f'))


class ScrollToTop(QToolButton):
    """Viewport overlay, visible only after scrolling; one short scroll animation."""
    def __init__(self,scroll):
        super().__init__(scroll.viewport());self.scroll=scroll
        self.setFixedSize(36,36);self.setIcon(line_icon('rocket',20,'#dfd0ff'));self.setIconSize(QSize(20,20));self.setCursor(Qt.PointingHandCursor)
        self.setToolTip('Back to top');self.setAccessibleName('Back to top of history')
        self.setStyleSheet('QToolButton {font-size:20px;border-radius:18px;background:#403747;border:1px solid #685776;color:#dfd0ff;} QToolButton:hover {background:#574565;border-color:#c7b8fa;}')
        self.motion=QPropertyAnimation(scroll.verticalScrollBar(),b'value',self);self.motion.setDuration(220);self.motion.setEasingCurve(QEasingCurve.OutCubic)
        self.clicked.connect(self.go_top);scroll.verticalScrollBar().valueChanged.connect(self.sync)
        scroll.verticalScrollBar().rangeChanged.connect(self.sync);scroll.viewport().installEventFilter(self);self.hide()
    def eventFilter(self,watched,event):
        if event.type()==QEvent.Resize:self.sync()
        return super().eventFilter(watched,event)
    def sync(self,*args):
        viewport=self.scroll.viewport();self.move(viewport.width()-self.width()-16,viewport.height()-self.height()-16)
        self.setVisible(self.scroll.verticalScrollBar().value()>max(120,viewport.height()//2));self.raise_()
    def go_top(self):
        self.motion.stop();self.motion.setStartValue(self.scroll.verticalScrollBar().value());self.motion.setEndValue(0);self.motion.start()

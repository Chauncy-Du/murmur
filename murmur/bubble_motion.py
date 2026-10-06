"""Non-activating floating placement and cancellable bubble motion."""
from PySide6.QtCore import QObject,Qt,QTimer,QRect,QPoint,QPropertyAnimation,QParallelAnimationGroup,QEasingCurve,Property,Slot
from PySide6.QtGui import QCursor,QPainter
from PySide6.QtWidgets import QApplication,QWidget
from shiboken6 import isValid


def number(cfg,key,default,low,high):
    value=cfg.get(key,default)
    return max(low,min(high,value)) if type(value) is int else default


def duration(cfg):return number(cfg,'bubble_motion_duration',240,120,500)


def placement(cfg,size,cursor=None):
    """Clamp to the chosen screen, or the cursor's screen when following."""
    screens=QApplication.screens()
    if not screens:return QRect(QPoint(0,0),size)
    cursor=cursor if cursor is not None else QCursor.pos()
    follow=cfg.get('bubble_follow_mouse',False)
    screen=(QApplication.screenAt(cursor) if follow else None) or screens[number(cfg,'bubble_screen',0,0,len(screens)-1)]
    bounds=screen.availableGeometry()
    w,h=min(size.width(),bounds.width()),min(size.height(),bounds.height())
    offset=number(cfg,'bubble_offset',20,0,3650)
    if follow:
        gap=number(cfg,'bubble_cursor_offset',24,12,160)
        x,y=cursor.x()+gap,cursor.y()+gap
        if x+w>bounds.right()+1:x=cursor.x()-gap-w
        if y+h>bounds.bottom()+1:y=cursor.y()-gap-h
    else:
        anchor=cfg.get('bubble_position','bottom')
        x=bounds.center().x()-w//2
        y=bounds.top()+offset if anchor.startswith('top') else bounds.bottom()+1-h-offset
        if anchor in ('left','right'):y=bounds.center().y()-h//2
        if 'left' in anchor:x=bounds.left()+offset
        if 'right' in anchor:x=bounds.right()+1-w-offset
    x=max(bounds.left(),min(x,bounds.right()+1-w))
    y=max(bounds.top(),min(y,bounds.bottom()+1-h))
    return QRect(x,y,w,h)


def compact(rect,style):
    if style=='fade':return QRect(rect)
    if style=='slide':
        screen=QApplication.screenAt(rect.center())
        dy=-12 if screen and rect.center().y()>screen.availableGeometry().center().y() else 12
        return rect.translated(0,dy)
    w,h=round(rect.width()*.86),round(rect.height()*.86)
    return QRect(rect.center().x()-w//2,rect.center().y()-h//2,w,h)


class _ExitFrame(QWidget):
    """An inert snapshot fades out while the real controls close immediately."""
    def __init__(self,pixmap,rect):
        super().__init__(None,Qt.Tool|Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint|Qt.WindowDoesNotAcceptFocus|Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.pixmap=pixmap;self._alpha=1.
        self.setGeometry(rect)
    def get_alpha(self):return self._alpha
    def set_alpha(self,value):self._alpha=value;self.update()
    alpha=Property(float,get_alpha,set_alpha)
    def paintEvent(self,event):
        painter=QPainter(self);painter.setOpacity(self._alpha)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawPixmap(self.rect(),self.pixmap)


class FloatingMotion(QObject):
    def __init__(self,widget):
        super().__init__(widget)
        self.widget=widget;self.enter=None;self.exit=None;self.ghost=None;self.target=None;self.skip_exit=False
        self.follow=QTimer(self);self.follow.setInterval(32);self.follow.timeout.connect(self.track)
        widget.destroyed.connect(self.dispose)

    def stop_enter(self):
        if self.enter:
            self.enter.stop();self.enter.deleteLater();self.enter=None
        if self.target is not None:
            self.widget.setFixedSize(self.target.size());self.widget.setGeometry(self.target)
        self.widget.setWindowOpacity(1.)

    def stop_exit(self):
        # QObject destruction may run after Python-side attributes are cleared.
        animation=getattr(self,'exit',None);ghost=getattr(self,'ghost',None)
        if animation and isValid(animation):animation.stop();animation.deleteLater()
        if ghost and isValid(ghost):ghost.hide();ghost.deleteLater()
        self.exit=None;self.ghost=None

    @Slot()
    def dispose(self):
        self.stop_exit()

    def show(self):
        self.stop_exit();self.stop_enter()
        target=QRect(self.widget.geometry());self.target=target
        style=self.widget.cfg.get('bubble_enter_motion','pop')
        if self.widget.isVisible() or style=='none':
            QWidget.show(self.widget);self.follow.start();return
        self.widget.setMinimumSize(0,0);self.widget.setMaximumSize(16777215,16777215)
        self.widget.setGeometry(compact(target,style));self.widget.setWindowOpacity(0.)
        group=QParallelAnimationGroup(self)
        for obj,key,start,end in ((self.widget,b'geometry',self.widget.geometry(),target),(self.widget,b'windowOpacity',0.,1.)):
            animation=QPropertyAnimation(obj,key,group);animation.setDuration(duration(self.widget.cfg))
            animation.setStartValue(start);animation.setEndValue(end);animation.setEasingCurve(QEasingCurve.OutCubic)
            group.addAnimation(animation)
        self.enter=group
        def finished():
            if self.enter is group:
                self.enter=None;self.widget.setFixedSize(target.size());self.widget.setGeometry(target)
                self.widget.setWindowOpacity(1.);self.follow.start()
            group.deleteLater()
        group.finished.connect(finished)
        QWidget.show(self.widget);group.start()

    def hide(self):
        self.follow.stop();self.stop_exit()
        visible=self.widget.isVisible()
        style=self.widget.cfg.get('bubble_exit_motion','pop')
        # Stop enter before taking a full, settled frame. The live widget is
        # hidden immediately, so cancellation and copy can never leave controls.
        self.stop_enter()
        ghost=_ExitFrame(self.widget.grab(),QRect(self.widget.geometry())) if visible and style!='none' and not self.skip_exit else None
        self.skip_exit=False
        QWidget.hide(self.widget)
        if ghost is None:return
        self.ghost=ghost
        group=QParallelAnimationGroup(self)
        for obj,key,start,end in ((ghost,b'geometry',ghost.geometry(),compact(ghost.geometry(),style)),(ghost,b'alpha',1.,0.)):
            animation=QPropertyAnimation(obj,key,group);animation.setDuration(duration(self.widget.cfg))
            animation.setStartValue(start);animation.setEndValue(end);animation.setEasingCurve(QEasingCurve.InCubic)
            group.addAnimation(animation)
        self.exit=group
        def finished():
            if self.exit is group:self.stop_exit()
        group.finished.connect(finished);ghost.show();group.start()

    def track(self):
        widget=self.widget
        if not widget.isVisible():self.follow.stop();return
        if not widget.cfg.get('bubble_follow_mouse',False) or self.enter is not None:return
        cursor=QCursor.pos()
        # Keep buttons still while the cursor is inside the bubble.
        if widget.geometry().contains(cursor):return
        target=placement(widget.cfg,widget.size(),cursor)
        screen=QApplication.screenAt(cursor)
        if screen and not screen.availableGeometry().contains(widget.geometry()):
            widget.setFixedSize(target.size());widget.setGeometry(target);self.target=QRect(target);return
        current=widget.pos();end=target.topLeft()
        point=QPoint(round(current.x()+(end.x()-current.x())*.45),round(current.y()+(end.y()-current.y())*.45))
        # A screen change snaps to the new display rather than traversing gaps.
        if not target.adjusted(-100,-100,100,100).contains(current):point=end
        widget.move(point);self.target=QRect(widget.geometry())

"""Quiet desktop interactions: short hover animations, no idle repaint loop."""
from PySide6.QtCore import Qt,Property,QPropertyAnimation,QEasingCurve,QRectF,QEvent,Signal,QObject
from PySide6.QtGui import QColor,QPainter,QPen,QPainterPath,QLinearGradient,QPixmap
from PySide6.QtWidgets import QFrame,QPushButton,QWidget,QLabel


class SessionStatus(QObject):
    """Controller status storage without a visual widget or layout footprint."""
    def __init__(self,parent=None):
        super().__init__(parent);self._text=''

    def setText(self,text):
        self._text=text

    def text(self):return self._text

    def clear(self):self.setText('')


class Surface(QFrame):
    activated=Signal()
    def __init__(self,interactive=False,parent=None):
        super().__init__(parent);self._hover=0.;self._pulse=0.;self.interactive=interactive;self.motion_enabled=True
        self.animation=QPropertyAnimation(self,b'hover',self);self.animation.setDuration(140)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.setAttribute(Qt.WA_Hover)
        self.pulse_animation=QPropertyAnimation(self,b'pulse',self);self.pulse_animation.setDuration(320)
        self.pulse_animation.setStartValue(1.);self.pulse_animation.setEndValue(0.)

    def get_pulse(self):return self._pulse
    def set_pulse(self,value):self._pulse=value;self.update()
    pulse=Property(float,get_pulse,set_pulse)

    def make_action(self,callback,name):
        self.interactive=True;self.activated.connect(callback)
        self.setCursor(Qt.PointingHandCursor);self.setFocusPolicy(Qt.StrongFocus);self.setAccessibleName(name)

    def mouseReleaseEvent(self,event):
        if self.motion_enabled and event.button()==Qt.LeftButton:self.pulse_animation.stop();self.pulse_animation.start()
        if self.interactive and event.button()==Qt.LeftButton and self.rect().contains(event.position().toPoint()):self.activated.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self,event):
        if self.interactive and event.key() in (Qt.Key_Return,Qt.Key_Enter,Qt.Key_Space):
            self.activated.emit();event.accept();return
        super().keyPressEvent(event)

    def get_hover(self):return self._hover
    def set_hover(self,value):self._hover=value;self.update()
    hover=Property(float,get_hover,set_hover)

    def event(self,event):
        if self.motion_enabled and event.type() in (QEvent.HoverEnter,QEvent.HoverLeave):
            self.animation.stop();self.animation.setStartValue(self._hover)
            self.animation.setEndValue(1. if event.type()==QEvent.HoverEnter else 0.);self.animation.start()
        return super().event(event)

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(43+round(self._hover*5),41+round(self._hover*5),48+round(self._hover*7)))
        p.setPen(QPen(QColor('#b2a0ec') if self.hasFocus() else QColor(61+round(self._hover*25),57+round(self._hover*20),69+round(self._hover*32)),1))
        p.drawRoundedRect(QRectF(.5,.5,self.width()-1,self.height()-1),10,10)
        if self._pulse:
            color=QColor('#c7b8fa');color.setAlpha(int(115*self._pulse));p.setPen(QPen(color,1));p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(.5,.5,self.width()-1,self.height()-1),10,10)


class ShimmerLabel(QLabel):
    """A single short animation paints light through the number glyphs."""
    def __init__(self,text='',parent=None):
        super().__init__(text,parent);self._shine=0.
        self.shine_animation=QPropertyAnimation(self,b'shine',self);self.shine_animation.setDuration(650)
        self.shine_animation.setStartValue(0.);self.shine_animation.setEndValue(1.)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
    def get_shine(self):return self._shine
    def set_shine(self,value):self._shine=value;self.update()
    shine=Property(float,get_shine,set_shine)
    def shimmer(self):self.shine_animation.stop();self.shine_animation.start()
    def paintEvent(self,event):
        super().paintEvent(event)
        if not 0<self._shine<1:return
        rect=self.contentsRect();metrics=self.fontMetrics();width=metrics.horizontalAdvance(self.text())
        x=rect.x()
        if self.alignment() & Qt.AlignRight:x=rect.x()+rect.width()-width
        elif self.alignment() & Qt.AlignHCenter:x=rect.x()+(rect.width()-width)/2
        position=x-40+(width+80)*self._shine
        gradient=QLinearGradient(position-28,0,position+28,0)
        gradient.setColorAt(0,QColor(255,255,255,0));gradient.setColorAt(.5,QColor(255,255,255,235));gradient.setColorAt(1,QColor(255,255,255,0))
        path=QPainterPath();path.addText(x,rect.y()+(rect.height()-metrics.height())/2+metrics.ascent(),self.font(),self.text())
        painter=QPainter(self);painter.setRenderHint(QPainter.Antialiasing);painter.fillPath(path,gradient)


class ShimmerIcon(ShimmerLabel):
    """Sweep light through the existing icon alpha, preserving its silhouette."""
    def paintEvent(self,event):
        QLabel.paintEvent(self,event)
        pixmap=self.pixmap()
        if not 0<self._shine<1 or pixmap.isNull():return
        overlay=QPixmap(pixmap.size());overlay.setDevicePixelRatio(pixmap.devicePixelRatio())
        overlay.fill(Qt.transparent)
        painter=QPainter(overlay);painter.drawPixmap(0,0,pixmap)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        width=pixmap.width()/pixmap.devicePixelRatio()
        height=pixmap.height()/pixmap.devicePixelRatio()
        position=-8+(width+16)*self._shine
        gradient=QLinearGradient(position-7,0,position+7,0)
        gradient.setColorAt(0,QColor(255,255,255,0));gradient.setColorAt(.5,QColor(255,255,255,235));gradient.setColorAt(1,QColor(255,255,255,0))
        painter.fillRect(QRectF(0,0,width,height),gradient);painter.end()
        painter=QPainter(self);painter.drawPixmap(self.contentsRect().topLeft(),overlay)


class HoverButton(QPushButton):
    """Native button hit-testing, keyboard behavior and focus; animated fill."""
    def __init__(self,text,parent=None):
        super().__init__(text,parent);self._hover=0.
        self.motion=QPropertyAnimation(self,b'hover',self);self.motion.setDuration(120)
        self.motion.setEasingCurve(QEasingCurve.OutCubic)
        self.setCursor(Qt.PointingHandCursor)

    def get_hover(self):return self._hover
    def set_hover(self,value):
        self._hover=value
        primary=self.objectName()=='primary'
        a,b=((199,184,250),(218,206,255)) if primary else ((48,48,53),(62,60,70))
        fill='rgb('+','.join(str(round(x+(y-x)*value)) for x,y in zip(a,b))+')'
        self.setStyleSheet(f'QPushButton:enabled{{background:{fill};}}QPushButton:pressed{{background:'+('#b8a4ed' if primary else '#252529')+';}')
    hover=Property(float,get_hover,set_hover)

    def enterEvent(self,event):
        self.motion.stop();self.motion.setStartValue(self._hover);self.motion.setEndValue(1.);self.motion.start()
        super().enterEvent(event)

    def leaveEvent(self,event):
        self.motion.stop();self.motion.setStartValue(self._hover);self.motion.setEndValue(0.);self.motion.start()
        super().leaveEvent(event)


class UsageSplit(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.setFixedHeight(8);self.local=0;self.external=0

    def set_counts(self,local,external):
        self.local=max(0,local);self.external=max(0,external);self.update()
        self.setAccessibleName(f'Local {local:,} tokens; external {external:,} tokens')

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        rect=QRectF(0,0,self.width(),8);p.setPen(Qt.NoPen);p.setBrush(QColor('#3c3547'));p.drawRoundedRect(rect,4,4)
        total=self.local+self.external
        if not total:return
        from PySide6.QtGui import QPainterPath
        clip=QPainterPath();clip.addRoundedRect(rect,4,4);p.setClipPath(clip)
        p.fillRect(rect,QColor('#798798'));p.fillRect(QRectF(0,0,self.width()*self.local/total,8),QColor('#c7b8fa'))


class ResourceBar(QWidget):
    def __init__(self,color,parent=None):
        super().__init__(parent);self.setFixedHeight(5);self.value=None;self.color=QColor(color)
        self._shine=0.;self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.shine_animation=QPropertyAnimation(self,b'shine',self);self.shine_animation.setDuration(650)
        self.shine_animation.setStartValue(0.);self.shine_animation.setEndValue(1.)

    def get_shine(self):return self._shine
    def set_shine(self,value):self._shine=value;self.update()
    shine=Property(float,get_shine,set_shine)
    def shimmer(self):self.shine_animation.stop();self.shine_animation.start()

    def set_value(self,value):
        self.value=None if value is None else max(0.,min(100.,value));self.update()

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing);p.setPen(Qt.NoPen)
        p.setBrush(QColor('#403b48'));p.drawRoundedRect(QRectF(0,0,self.width(),5),2.5,2.5)
        if self.value is not None and self.value>0:
            p.setBrush(self.color);p.drawRoundedRect(QRectF(0,0,self.width()*self.value/100,5),2.5,2.5)
        if 0<self._shine<1:
            clip=QPainterPath();clip.addRoundedRect(QRectF(0,0,self.width(),5),2.5,2.5);p.setClipPath(clip)
            position=-24+(self.width()+48)*self._shine
            gradient=QLinearGradient(position-24,0,position+24,0)
            gradient.setColorAt(0,QColor(255,255,255,0));gradient.setColorAt(.5,QColor(255,255,255,170));gradient.setColorAt(1,QColor(255,255,255,0))
            p.fillRect(self.rect(),gradient)


class StatusDot(QWidget):
    COLORS={'pending':'#a59abc','active':'#9ecdb2','warning':'#ddb575','error':'#da8d9b','off':'#746d7b'}
    def __init__(self,parent=None):
        super().__init__(parent);self.setFixedSize(9,9);self.state='pending'
    def set_state(self,state,detail):
        self.state=state;self.setToolTip(detail);self.setAccessibleName(detail);self.update()
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing);p.setPen(Qt.NoPen)
        color=QColor(self.COLORS[self.state]);glow=QColor(color);glow.setAlpha(40)
        p.setBrush(glow);p.drawEllipse(QRectF(0,0,9,9));p.setBrush(color);p.drawEllipse(QRectF(2,2,5,5))

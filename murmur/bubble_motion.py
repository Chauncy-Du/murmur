"""Non-activating floating placement and cancellable bubble motion."""
from math import hypot
from PySide6.QtCore import QObject,Qt,QTimer,QRect,QRectF,QPoint,QPointF,QPropertyAnimation,QParallelAnimationGroup,QEasingCurve,Property,Slot
from PySide6.QtGui import QCursor,QPainter,QPainterPath,QColor,QPen,QImage,QLinearGradient
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


def _smooth(start,end,value):
    t=max(0.,min(1.,value));return start+(end-start)*t*t*(3.-2.*t)


class _LiquidFrame(_ExitFrame):
    """An input-transparent surface grows from the work-area edge.

    Keep the actual controls at their final size: only this painted surface
    stretches, so labels and buttons never reflow during the emergence.
    """
    def __init__(self,pixmap,target,cfg):
        screen=QApplication.screenAt(target.center())
        bounds=screen.availableGeometry() if screen else target.adjusted(0,0,0,20)
        # Cursor-follow and non-bottom placements emerge locally instead of
        # stretching a tether across the entire display.
        bottom=not cfg.get('bubble_follow_mouse',False) and cfg.get('bubble_position','bottom').startswith('bottom')
        self.edge=bounds.bottom()+1 if bottom else min(bounds.bottom()+1,target.bottom()+21)
        frame=target.adjusted(-12,-12,12,max(12,self.edge-target.bottom()))
        super().__init__(pixmap,frame)
        self.target=QRectF(target.translated(-frame.x(),-frame.y()))
        self.edge-=frame.y();self._progress=0.

    def get_progress(self):return self._progress
    def set_progress(self,value):self._progress=value;self.update()
    progress=Property(float,get_progress,set_progress)

    def body_rect(self):
        t=self._progress;r=self.target
        # Birth, stretch, release, squash, settle. Smooth interpolation has
        # zero velocity at each turning point, keeping the rebound soft.
        keys=((0.,.18,.08,0.),(.22,.46,.66,.32),(.50,.88,1.16,1.04),
              (.70,1.045,.94,1.025),(.86,.985,1.025,1.),(1.,1.,1.,1.))
        for a,b in zip(keys,keys[1:]):
            if t<=b[0]:
                u=(t-a[0])/(b[0]-a[0])
                w=_smooth(a[1],b[1],u)*r.width();h=_smooth(a[2],b[2],u)*r.height()
                rise=_smooth(a[3],b[3],u)
                cy=self.edge+(r.center().y()-self.edge)*rise
                return QRectF(r.center().x()-w/2,cy-h/2,w,h)
        return QRectF(r)

    def surface_path(self):
        body=self.body_rect().adjusted(1,1,-1,-1)
        path=QPainterPath();path.addRoundedRect(body,body.height()/2,body.height()/2)
        t=self._progress
        if t<.64:
            # A flared foot becomes a narrow neck, then retracts into the
            # bubble. Union eliminates an internal seam at the attachment.
            release=_smooth(0.,1.,(t-.50)/.14)
            pinch=_smooth(0.,1.,(t-.26)/.38)
            cx=body.center().x();join=body.bottom()-.5
            end=_smooth(self.edge,body.bottom(),release)
            half=body.width()*.24*(1.-release)
            waist=body.width()*.07*(1.-pinch)
            foot=self.target.width()*.24*(1.-pinch)
            neck=QPainterPath();neck.moveTo(cx-half,join)
            neck.cubicTo(cx-waist,join,cx-waist,end,cx-foot,end)
            neck.lineTo(cx+foot,end)
            neck.cubicTo(cx+waist,end,cx+waist,join,cx+half,join)
            neck.closeSubpath();path=path.united(neck)
        return path

    def paintEvent(self,event):
        # Mask the entire painted surface, including its outline, so the
        # contact foot blends into the edge instead of leaving a hard seam.
        dpr=self.devicePixelRatioF()
        layer=QImage(round(self.width()*dpr),round(self.height()*dpr),QImage.Format_ARGB32_Premultiplied)
        layer.setDevicePixelRatio(dpr);layer.fill(Qt.transparent)
        painter=QPainter(layer);painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        surface=self.surface_path()
        painter.setOpacity(_smooth(0.,1.,self._progress/.16))
        painter.setPen(QPen(QColor('#51465f'),1));painter.setBrush(QColor('#242128'))
        painter.drawPath(surface)
        # Snapshot crossfades after release, while the shell is settling.
        painter.setClipPath(surface)
        painter.setOpacity(_smooth(0.,1.,(self._progress-.48)/.38))
        painter.drawPixmap(self.body_rect(),self.pixmap,QRectF(self.pixmap.rect()))
        if self._progress<.64:
            painter.setClipping(False);painter.setOpacity(1.)
            painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            mask=QLinearGradient(0,self.edge-14,0,self.edge)
            mask.setColorAt(0,QColor(255,255,255,255))
            mask.setColorAt(1,QColor(255,255,255,round(_smooth(0.,255.,(self._progress-.50)/.14))))
            painter.fillRect(self.rect(),mask)
        painter.end()
        output=QPainter(self);output.drawImage(0,0,layer)


class _BurstFrame(_ExitFrame):
    """A bounded, analytic splash: cached rim geometry and 20 liquid beads.

    One property animation supplies time. Seeds and paths are built once;
    painting uses closed-form ballistic positions, with no particle widgets,
    simulations, per-particle timers, or frame-dependent random sampling.
    """
    def __init__(self,pixmap,target):
        frame=target.adjusted(-56,-64,56,40)
        super().__init__(pixmap,frame)
        self.target=QRectF(target.translated(-frame.x(),-frame.y()))
        self._progress=0.
        r=self.target
        self.shell=QPainterPath();self.shell.addRoundedRect(r.adjusted(1,1,-1,-1),r.height()/2-1,r.height()/2-1)
        self.particle_pen=QPen(QColor('#b6a2cc'));self.particle_pen.setCapStyle(Qt.RoundCap)
        self.particle_brush=QColor('#b6a2cc')
        self.shard_pen=QPen(QColor('#8e7aa3'),1.1);self.shard_pen.setCapStyle(Qt.RoundCap)
        self.particles=[];self.shards=[]
        for i in range(20):
            # Low-discrepancy jitter spreads the beads without uniform dashes.
            f=(i+.18+(i*7%11)/15)/20
            point=self.shell.pointAtPercent(f)
            nx=(point.x()-r.center().x())/(r.width()/2)
            ny=(point.y()-r.center().y())/(r.height()/2)
            length=hypot(nx,ny) or 1.;nx/=length;ny/=length
            speed=24+(i*13%25)
            vx=nx*speed+ny*((i%3)-1)*9
            vy=ny*speed*.72-15-(i*7%13)
            radius=1.25+(i*7%9)*.18
            delay=.07+(i*3%7)*.012
            lifetime=.60+(i*5%7)*.025
            self.particles.append((point.x(),point.y(),vx,vy,radius,delay,lifetime))
            if i in (1,4,8,11,15,18):
                path=QPainterPath()
                for j in range(5):
                    sample=self.shell.pointAtPercent(max(0.,min(1.,f-.014+j*.007)))
                    sample-=point
                    if j==0:path.moveTo(sample)
                    else:path.lineTo(sample)
                self.shards.append((path,point.x(),point.y(),vx*.65,vy*.65,(-1 if i%2 else 1)*35))
        self.particles=tuple(self.particles);self.shards=tuple(self.shards)

    def get_progress(self):return self._progress
    def set_progress(self,value):
        self._progress=value;self._alpha=1.-_smooth(0.,1.,value);self.update()
    progress=Property(float,get_progress,set_progress)

    def paintEvent(self,event):
        t=self._progress;r=self.target
        painter=QPainter(self);painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        swell=_smooth(1.,1.065,t/.20)
        if t<.43:
            opening=_smooth(0.,1.,(t-.10)/.33)
            hole=QPainterPath();hole.addEllipse(r.center(),r.width()*.62*opening,r.height()*.86*opening)
            painter.save()
            painter.translate(r.center());painter.scale(swell,swell);painter.translate(-r.center())
            painter.setClipPath(self.shell.subtracted(hole))
            painter.setOpacity(1.-_smooth(0.,1.,(t-.06)/.37))
            painter.drawPixmap(r,self.pixmap,QRectF(self.pixmap.rect()));painter.restore()
        # Short curved skin pieces release first, then give way to liquid beads.
        opacity=_smooth(0.,.65,(t-.08)/.10)*(1.-_smooth(0.,1.,(t-.20)/.36))
        if opacity>.005:
            painter.setOpacity(opacity);painter.setPen(self.shard_pen);painter.setBrush(Qt.NoBrush)
            flight=max(0.,(t-.08)/.65)
            for path,x,y,vx,vy,spin in self.shards:
                painter.save();painter.translate(x+vx*flight,y+vy*flight+12*flight*flight)
                painter.rotate(spin*flight);painter.drawPath(path);painter.restore()
        painter.setBrush(self.particle_brush)
        for x,y,vx,vy,radius,delay,lifetime in self.particles:
            u=(t-delay)/lifetime
            if not 0.<u<1.:continue
            opacity=_smooth(0.,1.,u/.10)*(1.-_smooth(0.,1.,(u-.30)/.70))
            size=radius*(1.-u*.65)
            px=x+vx*u;py=y+vy*u+18*u*u
            painter.setOpacity(opacity)
            # A short rounded streak makes the initial ejection legible.
            if u<.52:
                trail=3.*(1.-u/.52)
                self.particle_pen.setWidthF(size*1.05);painter.setPen(self.particle_pen)
                painter.drawLine(QPointF(px,py),QPointF(px-vx*trail/48,py-(vy+36*u)*trail/48))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(px,py),size,size*.82)


class FloatingMotion(QObject):
    def __init__(self,widget,liquid=False):
        super().__init__(widget)
        self.widget=widget;self.enter=None;self.exit=None;self.ghost=None;self.target=None;self.skip_exit=False
        self.liquid=liquid;self.entry_frame=None
        self.follow=QTimer(self);self.follow.setInterval(32);self.follow.timeout.connect(self.track)
        widget.destroyed.connect(self.dispose)

    def stop_enter(self):
        if self.enter:
            self.enter.stop();self.enter.deleteLater();self.enter=None
        self.clear_entry_frame()
        if self.target is not None:
            self.widget.setFixedSize(self.target.size());self.widget.setGeometry(self.target)
        self.widget.setWindowOpacity(1.)

    def clear_entry_frame(self):
        frame=getattr(self,'entry_frame',None)
        if frame and isValid(frame):frame.hide();frame.deleteLater()
        self.entry_frame=None

    def stop_exit(self):
        # QObject destruction may run after Python-side attributes are cleared.
        animation=getattr(self,'exit',None);ghost=getattr(self,'ghost',None)
        if animation and isValid(animation):animation.stop();animation.deleteLater()
        if ghost and isValid(ghost):ghost.hide();ghost.deleteLater()
        self.exit=None;self.ghost=None

    @Slot()
    def dispose(self):
        self.clear_entry_frame()
        self.stop_exit()

    def show(self):
        self.stop_exit();self.stop_enter()
        target=QRect(self.widget.geometry());self.target=target
        style=self.widget.cfg.get('bubble_enter_motion','pop')
        if self.widget.isVisible() or style=='none':
            QWidget.show(self.widget);self.follow.start();return
        if style=='pop' and self.liquid:
            self.show_liquid(target);return
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

    def show_liquid(self,target):
        frame=_LiquidFrame(self.widget.grab(),target,self.widget.cfg)
        self.entry_frame=frame
        self.widget.setWindowOpacity(0.)
        QWidget.show(self.widget)
        animation=QPropertyAnimation(frame,b'progress',self)
        animation.setDuration(duration(self.widget.cfg));animation.setStartValue(0.);animation.setEndValue(1.)
        animation.setEasingCurve(QEasingCurve.Linear);self.enter=animation
        def finished():
            if self.enter is animation:
                self.enter=None;self.widget.setWindowOpacity(1.)
                self.clear_entry_frame();self.follow.start()
            animation.deleteLater()
        animation.finished.connect(finished);frame.show();animation.start()

    def hide(self):
        self.follow.stop();self.stop_exit()
        visible=self.widget.isVisible()
        style=self.widget.cfg.get('bubble_exit_motion','burst')
        # Stop enter before taking a full, settled frame. The live widget is
        # hidden immediately, so cancellation and copy can never leave controls.
        self.stop_enter()
        frame_type=_BurstFrame if style=='burst' else _ExitFrame
        ghost=frame_type(self.widget.grab(),QRect(self.widget.geometry())) if visible and style!='none' and not self.skip_exit else None
        self.skip_exit=False
        QWidget.hide(self.widget)
        if ghost is None:return
        self.ghost=ghost
        if style=='burst':
            animation=QPropertyAnimation(ghost,b'progress',self)
            animation.setDuration(duration(self.widget.cfg));animation.setStartValue(0.);animation.setEndValue(1.)
            animation.setEasingCurve(QEasingCurve.Linear);self.exit=animation
            def finished():
                if self.exit is animation:self.stop_exit()
            animation.finished.connect(finished);ghost.show();animation.start();return
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

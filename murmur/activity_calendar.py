"""Calendar halo and delayed, in-window day details; no idle rendering or I/O."""
import calendar
from datetime import date,timedelta
from math import hypot,exp
from time import monotonic
from PySide6.QtCore import Qt,Signal,QRectF,QPointF,QTimer
from PySide6.QtGui import QColor,QPainter,QPen,QPainterPath,QRadialGradient,QPixmap
from PySide6.QtWidgets import QWidget,QFrame,QVBoxLayout,QLabel


class ActivityCalendar(QWidget):
    day_clicked=Signal(str)  # Compatibility; calendar clicks do not change pages or metrics.
    PALETTE=['#434048','#4c3c69','#6b5193','#9570c4','#c7b8fa']
    GAP=3

    def __init__(self):
        super().__init__();self.daily={};self.summaries={};self.cells=[];self.end=date.today()
        self.selected_day=date.today();self.hover_day=None
        self.setFixedHeight(140);self.setMouseTracking(True)
        self._source=None;self._glow_point=None;self._energies={};self._ripples=[];self._base=None;self._base_key=None
        self.frame_timer=QTimer(self);self.frame_timer.setTimerType(Qt.PreciseTimer);self.frame_timer.setInterval(16)
        self.frame_timer.timeout.connect(self.advance_motion);self._last_frame=monotonic()
        self.dwell=QTimer(self);self.dwell.setTimerType(Qt.PreciseTimer);self.dwell.setSingleShot(True);self.dwell.setInterval(2000);self.dwell.timeout.connect(self.show_details)
        self.detail_panel=None
        self.setAccessibleName('Activity calendar. Hover over a day for two seconds to see its totals.')

    def get_hover_strength(self):return max(self._energies.values(),default=0.)

    def dismiss_details(self):
        self.dwell.stop()
        if self.detail_panel:self.detail_panel.hide()

    def wake_motion(self):
        if not self.frame_timer.isActive():
            self._last_frame=monotonic();self.frame_timer.start()

    def hover(self,day):
        if day==self.hover_day:return
        self.dismiss_details();self.hover_day=day
        self._source=next((rect.center() for rect,d,_ in self.cells if d==day),None)
        if self._source is not None:self._glow_point=QPointF(self._source)
        if day is not None:self.dwell.start()
        self.wake_motion()

    def advance_motion(self):
        now=monotonic();dt=min(.05,max(.001,now-self._last_frame));self._last_frame=now
        self._ripples=[wave for wave in self._ripples if now-wave[1]<.85]
        unsettled=False
        for rect,day,_ in self.cells:
            target=0. if self._source is None else max(0.,1.-hypot(rect.center().x()-self._source.x(),rect.center().y()-self._source.y())/(self._step*2.6))**2
            previous=self._energies.get(day,0.)
            value=target+(previous-target)*exp(-dt/(.075 if target>previous else .30))
            if value>.004:self._energies[day]=value
            else:self._energies.pop(day,None)
            if abs(value-target)>.004:unsettled=True
        self.update()
        if not unsettled and not self._ripples:self.frame_timer.stop()

    def set_data(self,daily,summaries=None):
        self.daily=daily;self.summaries=summaries or {};self._base=None;self.update()

    def shift(self,weeks):
        self.clear_motion();self.end=min(date.today(),self.end+timedelta(weeks=weeks));self._base=None;self.update()

    def show_details(self):
        if self.hover_day is None or not self.isVisible():return
        if self.detail_panel is None:
            self.detail_panel=QFrame(self.window());self.detail_panel.setObjectName('calendarDetails')
            self.detail_panel.setAttribute(Qt.WA_TransparentForMouseEvents)
            self.detail_panel.setStyleSheet('QFrame#calendarDetails {background:#302b3a;border:1px solid #78668f;border-radius:9px;} QLabel {font-size:12px;background:transparent;}')
            body=QVBoxLayout(self.detail_panel);body.setContentsMargins(12,10,12,10);body.setSpacing(6)
            self.detail_title=QLabel();self.detail_title.setStyleSheet('font-weight:600;color:#ded0ff;');body.addWidget(self.detail_title)
            self.detail_text=QLabel();body.addWidget(self.detail_text)
            self.detail_panel.setFixedWidth(268)
        self.detail_title.setText(self.hover_day.strftime('%b %d, %Y'))
        self.detail_text.setText(self.summaries.get(self.hover_day,'0 sessions · 0 characters\n0s · 0 / min'))
        self.detail_panel.adjustSize()
        rect=next((r for r,d,_ in self.cells if d==self.hover_day),QRectF())
        point=self.mapTo(self.window(),rect.bottomRight().toPoint())+QPointF(10,8).toPoint()
        point.setX(min(max(12,point.x()),self.window().width()-self.detail_panel.width()-12))
        point.setY(min(max(12,point.y()),self.window().height()-self.detail_panel.height()-12))
        self.detail_panel.move(point);self.detail_panel.show();self.detail_panel.raise_()

    def ensure_base(self):
        key=(self.width(),self.height(),self.devicePixelRatioF(),self.end)
        if self._base is not None and key==self._base_key:return
        self._base_key=key;dpr=self.devicePixelRatioF()
        self._base=QPixmap(round(self.width()*dpr),round(self.height()*dpr));self._base.setDevicePixelRatio(dpr);self._base.fill(Qt.transparent)
        p=QPainter(self._base);p.setRenderHint(QPainter.Antialiasing);font=self.font();font.setPixelSize(12);p.setFont(font)
        self.cells=[];left,top=24.,6.;columns=26
        size=max(8.,min(14.,(self.width()-left-18-25*self.GAP)/26));step=size+self.GAP;self._step=step
        stride=(self.width()-left-size-18)/25
        start=self.end-timedelta(days=(self.end.weekday()+1)%7+25*7)
        maximum=max(self.daily.values(),default=1);first=min(self.daily,default=start)
        for r,text in enumerate(('S','M','T','W','T','F','S')):
            p.setPen(QColor('#9696a2'));p.drawText(0,int(top+r*step+size/2+4),text)
        for c in range(columns):
            sunday=start+timedelta(weeks=c)
            if c==0 or sunday.month!=(sunday-timedelta(weeks=1)).month:
                p.setPen(QColor('#9696a2'));p.drawText(int(left+c*stride),int(top+7*step+11),calendar.month_abbr[sunday.month])
            for r in range(7):
                day=sunday+timedelta(days=r)
                if day>self.end:continue
                count=self.daily.get(day,0);level=0 if not count else max(1,min(4,int(count/maximum*4)))
                rect=QRectF(left+c*stride,top+r*step,size,size)
                p.setPen(Qt.NoPen);p.setBrush(QColor(self.PALETTE[level]));p.drawRoundedRect(rect,3,3)
                if day<first:
                    p.save();clip=QPainterPath();clip.addRoundedRect(rect,3,3);p.setClipPath(clip);p.fillRect(rect,QColor('#353438'))
                    p.setPen(QPen(QColor('#4b494f'),.6))
                    for stripe in range(-16,33,4):p.drawLine(rect.topLeft()+QPointF(stripe,size),rect.topLeft()+QPointF(stripe+size,0))
                    p.restore()
                self.cells.append((rect,day,count))

        p.end()

    def paintEvent(self,event):
        self.ensure_base();p=QPainter(self);p.setRenderHint(QPainter.Antialiasing);p.drawPixmap(0,0,self._base)
        p.setClipRect(QRectF(22,4,self.width()-38,self._step*7))
        now=monotonic();waves=[(point,self._step*(.5+6.5*(now-start)/.85),max(0.,1.-(now-start)/.85)**2) for point,start in self._ripples]
        if self._glow_point is not None and self._energies:
            glow=QRadialGradient(self._glow_point,self._step*2.6);color=QColor('#b79cf1');color.setAlpha(int(32*self.get_hover_strength()))
            glow.setColorAt(0,color);glow.setColorAt(1,QColor(183,156,241,0));p.setPen(Qt.NoPen);p.setBrush(glow)
            p.drawEllipse(self._glow_point,self._step*2.6,self._step*2.6)
        for rect,day,_ in self.cells:
            strength=self._energies.get(day,0.)
            for point,radius,fade in waves:
                distance=hypot(rect.center().x()-point.x(),rect.center().y()-point.y())
                strength=max(strength,max(0.,1.-abs(distance-radius)/(self._step*.65))*fade*.85)
            if strength>.004:
                fill=QColor('#d8c3ff');fill.setAlpha(round(105*strength));p.setPen(Qt.NoPen);p.setBrush(fill);p.drawRoundedRect(rect,3,3)
                edge=QColor('#e5dbff');edge.setAlpha(round(175*strength));p.setPen(QPen(edge,1));p.setBrush(Qt.NoBrush);p.drawRoundedRect(rect.adjusted(-.5,-.5,.5,.5),3,3)
        for point,radius,fade in waves:
            p.setBrush(Qt.NoBrush);color=QColor('#c9afff');color.setAlpha(round(18*fade));p.setPen(QPen(color,5));p.drawEllipse(point,radius,radius)
            color.setAlpha(round(100*fade));p.setPen(QPen(color,1.2));p.drawEllipse(point,radius,radius)

    def mouseMoveEvent(self,event):
        self.ensure_base();day=next((d for rect,d,_ in self.cells if rect.contains(event.position())),None)
        self.hover(day)
        if day is not None:
            self._source=QPointF(event.position())
            self._glow_point=QPointF(self._source)
            # Preserve crossed tiles even when input arrives faster than a frame.
            for rect,d,_ in self.cells:
                amount=max(0.,1.-hypot(rect.center().x()-self._source.x(),rect.center().y()-self._source.y())/(self._step*2.6))**2*.25
                if amount>.004:self._energies[d]=max(self._energies.get(d,0.),amount)
            self.wake_motion()

    def clear_motion(self):
        self.dismiss_details();self.hover_day=None;self._source=self._glow_point=None;self._energies.clear();self._ripples.clear();self.frame_timer.stop()

    def leaveEvent(self,event):self.hover(None);super().leaveEvent(event)
    def hideEvent(self,event):self.clear_motion();super().hideEvent(event)
    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:
            self.ensure_base()
            if any(rect.contains(event.position()) for rect,_,_ in self.cells):
                self._ripples.append((QPointF(event.position()),monotonic()));self._ripples=self._ripples[-4:];self.wake_motion()
        event.accept()

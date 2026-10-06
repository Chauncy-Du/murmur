"""A cancellable synthetic sequence that previews unsaved appearance choices."""
from PySide6.QtCore import QObject,QTimer,QEvent,Slot
from .ui import Bubble,ResultBubble
from shiboken6 import isValid


class AppearancePreview(QObject):
    def __init__(self,window,cfg):
        super().__init__(window);self.window=window;self.index=0
        self.capsule=Bubble(cfg);self.result=ResultBubble(cfg)
        self.capsule.cancel.connect(self.stop);self.capsule.toggle.connect(self.advance)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.advance)
        window.installEventFilter(self)
        window.settings_tabs.currentChanged.connect(self.category_changed)
        window.destroyed.connect(self.dispose)
        self.capsule.position();self.capsule.state('录音','0:03',True)
        self.timer.start(1800)

    def category_changed(self,index):
        if index!=3:self.stop()

    def eventFilter(self,watched,event):
        if watched is self.window and event.type() in (QEvent.Hide,QEvent.Close):self.stop()
        return False

    def advance(self):
        self.timer.stop();self.index+=1
        if self.index==1:
            self.capsule.set_progress('Transcribe',0,2);self.capsule.state('识别','Appearance preview',True)
            self.timer.start(1100)
        elif self.index==2:
            self.capsule.set_progress('Polish',1,2);self.capsule.state('整理','Appearance preview',True)
            self.timer.start(1100)
        elif self.index==3:
            self.result.show_result('Your spoken ideas, clearly written.\n语音化为文字，让思路清晰可见。',demo=True,status='Appearance preview · No recording',source=self.capsule)
            self.capsule.state('完成');self.timer.start(2500)
        else:self.stop()

    def stop(self):
        self.timer.stop();self.index=4
        self.capsule.state('完成');self.result.hide()

    @Slot()
    def dispose(self):
        for name in ('capsule','result'):
            widget=getattr(self,name,None)
            if widget and isValid(widget):widget.motion.stop_exit();widget.deleteLater()

    def replace(self):
        self.stop();self.dispose();self.window.removeEventFilter(self);self.deleteLater()

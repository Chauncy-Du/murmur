"""Read-only, background file-size accounting for the application's data folder."""
from dataclasses import dataclass
import os
from pathlib import Path
import stat
import threading
import queue

from PySide6.QtCore import Qt,QRectF,QTimer
from PySide6.QtGui import QColor,QPainter,QPainterPath
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel
from .ui import button,label


@dataclass(frozen=True)
class StorageSnapshot:
    history: int = 0
    recordings: int = 0
    other: int = 0
    unavailable: int = 0

    @property
    def total(self):return self.history+self.recordings+self.other


def scan_storage(root):
    """Count file lengths, including SQLite sidecars; never read file contents.

    Directory links/junctions and reparse files are not followed. Vanishing or
    unreadable files make the snapshot partial rather than a claimed zero.
    """
    root=Path(root)
    totals={'history':0,'recordings':0,'other':0};unavailable=0
    pending=[(root,False)]
    while pending:
        directory,audio=pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        info=entry.stat(follow_symlinks=False)
                        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
                            unavailable+=1;continue
                        if stat.S_ISDIR(info.st_mode):
                            pending.append((Path(entry.path),audio or directory==root and entry.name.casefold()=='audio'))
                        elif stat.S_ISREG(info.st_mode):
                            category='recordings' if audio else 'history' if directory==root and entry.name in ('history.db','history.db-wal','history.db-shm','history.db-journal') else 'other'
                            totals[category]+=info.st_size
                    except OSError:unavailable+=1
        except FileNotFoundError:
            unavailable+=1
        except OSError:unavailable+=1
    return StorageSnapshot(**totals,unavailable=unavailable)


def byte_text(value):
    if value<1024:return f'{value:,} B'
    amount=float(value)
    for unit in ('KiB','MiB','GiB','TiB'):
        amount/=1024
        if amount<1024 or unit=='TiB':return f'{amount:.1f} {unit}'


def percent_text(value,total):
    if not total or not value:return '0%'
    share=value/total*100
    return '<0.1%' if share<.1 else f'{share:.1f}%'


PARTS=(('history','History & text','#b9a7f2'),('recordings','Recordings','#7bd1bf'),('other','Other data','#e5bb7e'))


class StorageBar(QWidget):
    def __init__(self):
        super().__init__();self.snapshot=StorageSnapshot();self.setFixedHeight(12)
        self.setAccessibleName('Local data storage proportions')

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.Antialiasing)
        rect=QRectF(0,0,self.width(),self.height())
        path=QPainterPath();path.addRoundedRect(rect,6,6)
        painter.fillPath(path,QColor('#38333f'));painter.setClipPath(path)
        total=self.snapshot.total
        if total:
            left=0.
            for key,_,color in PARTS:
                width=getattr(self.snapshot,key)/total*self.width()
                painter.fillRect(QRectF(left,0,width,self.height()),QColor(color));left+=width


class LocalStorageUsage(QWidget):
    def __init__(self,root):
        super().__init__();self.root=Path(root);self._busy=False;self._results=queue.Queue()
        self.setMinimumWidth(0)
        body=QVBoxLayout(self);body.setContentsMargins(0,4,0,0);body.setSpacing(9)
        header=QHBoxLayout();header.addWidget(label('Storage used'),1)
        self.total_label=label('Measuring…');self.total_label.setStyleSheet('font-weight:600;')
        header.addWidget(self.total_label)
        self.refresh_button=button('Refresh',self.refresh)
        self.refresh_button.setToolTip('Measure local data again')
        header.addWidget(self.refresh_button);body.addLayout(header)
        self.bar=StorageBar();body.addWidget(self.bar)
        self.part_labels={}
        for key,title,color in PARTS:
            row=QHBoxLayout();row.setSpacing(8)
            dot=QLabel();dot.setFixedSize(8,8);dot.setStyleSheet(f'background:{color};border-radius:4px;')
            row.addWidget(dot);row.addWidget(label(title,'muted'),1)
            value=label('—');share=label('—','muted');share.setMinimumWidth(48);share.setAlignment(Qt.AlignRight|Qt.AlignVCenter)
            row.addWidget(value);row.addWidget(share);body.addLayout(row)
            self.part_labels[key]=(value,share)
        self.notice=label('Stored files in your data folder.','muted');self.notice.setStyleSheet('font-size:11px;');self.notice.setWordWrap(True)
        self.notice.setToolTip(str(self.root)+'\nHistory & text includes the history database, indexes, metadata and journal files. File lengths are measured, not free drive capacity or NTFS allocated clusters. Linked folders are not followed.')
        body.addWidget(self.notice)
        self.poll=QTimer(self);self.poll.setInterval(50);self.poll.timeout.connect(self.receive)
        self.timer=QTimer(self);self.timer.setInterval(5000);self.timer.timeout.connect(self.refresh)

    def showEvent(self,event):
        super().showEvent(event)
        if self._busy:self.poll.start()
        else:self.refresh()
        self.timer.start()

    def hideEvent(self,event):
        self.timer.stop();self.poll.stop();super().hideEvent(event)

    def refresh(self):
        if self._busy:return
        self._busy=True;self.refresh_button.setEnabled(False)
        root=self.root;results=self._results
        def work():
            try:snapshot=scan_storage(root)
            except Exception:snapshot=StorageSnapshot(unavailable=1)
            # Workers retain no Qt objects and can safely finish after closure.
            results.put(snapshot)
        threading.Thread(target=work,name='murmur-data-usage',daemon=True).start()
        self.poll.start()

    def receive(self):
        try:snapshot=self._results.get_nowait()
        except queue.Empty:return
        self.poll.stop();self.set_snapshot(snapshot)

    def set_snapshot(self,snapshot):
        self._busy=False;self.refresh_button.setEnabled(True)
        self.bar.snapshot=snapshot;self.bar.update()
        self.total_label.setText(('At least ' if snapshot.unavailable else '')+byte_text(snapshot.total))
        details=[]
        for key,title,_ in PARTS:
            value=getattr(snapshot,key);size,share=self.part_labels[key]
            size.setText(byte_text(value));share.setText(percent_text(value,snapshot.total))
            size.setToolTip(f'{value:,} bytes')
            details.append(f'{title}: {byte_text(value)} ({percent_text(value,snapshot.total)})')
        self.bar.setToolTip('\n'.join(details));self.bar.setAccessibleDescription('; '.join(details))
        self.notice.setText('Some files could not be measured; proportions describe the known total.' if snapshot.unavailable else 'Stored files in your data folder.')

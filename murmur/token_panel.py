"""Usage summary with a proportional split and explicit accounting coverage."""
from PySide6.QtCore import Qt,QPropertyAnimation,QEasingCurve
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QGridLayout
from .ui import label,button,icon
from .home_page import surface
from .dashboard_widgets import UsageSplit


def create_token_panel(window):
    dialog=QDialog(window);dialog.setWindowTitle('MurMur · Token usage');dialog.setWindowIcon(icon())
    dialog.setFixedSize(480,320);dialog.setWindowFlag(Qt.MSWindowsFixedSizeDialogHint,True);dialog.setModal(False)
    layout=QVBoxLayout(dialog);layout.setContentsMargins(12,10,12,10);layout.setSpacing(5)
    title=label('Token usage','title');title.setStyleSheet('font-size:20px;');layout.addWidget(title)
    subtitle=label('Local and external models · All tracked activity','muted');subtitle.setStyleSheet('font-size:10px;');layout.addWidget(subtitle)
    window.token_values={};summary=QHBoxLayout();summary.setSpacing(12)
    for key,title in (('local_tokens','Local tokens'),('external_tokens','External tokens')):
        frame,body=surface();body.setContentsMargins(10,8,10,8);body.setSpacing(2);body.addWidget(label(title,'eyebrow'))
        value=label('0');value.setStyleSheet('font-size:21px;font-weight:600;color:'+('#c7b8fa' if key=='local_tokens' else '#a9b8cd')+';')
        value.setWordWrap(False);body.addWidget(value);window.token_values[key]=value;summary.addWidget(frame,1)
    layout.addLayout(summary)
    window.token_split=UsageSplit();layout.addWidget(window.token_split)
    cost,body=surface();body.setContentsMargins(12,8,12,8);row=QHBoxLayout();row.addWidget(label('Known external cost · USD','muted'),1)
    value=label('Not available');value.setStyleSheet('font-size:17px;font-weight:600;color:#c7b8fa;');row.addWidget(value)
    window.token_values['external_cost_usd']=value;body.addLayout(row);layout.addWidget(cost)
    coverage,body=surface();body.setContentsMargins(10,8,10,8);body.setSpacing(5);heading=label('Accounting coverage');heading.setStyleSheet('font-size:11px;');body.addWidget(heading)
    grid=QGridLayout();grid.setHorizontalSpacing(8);grid.setVerticalSpacing(0)
    for i,(key,title) in enumerate((('requests','Requests'),('estimated_tokens','Estimated tokens'),('unpriced_calls','Unpriced calls'),('missing_usage_calls','Without usage'))):
        col=QVBoxLayout();col.setSpacing(1);value=label('0');value.setStyleSheet('font-size:16px;font-weight:600;');value.setMinimumHeight(22);col.addWidget(value)
        caption=label(title,'eyebrow');caption.setStyleSheet('font-size:10px;');caption.setWordWrap(False);col.addWidget(caption);window.token_values[key]=value;grid.addLayout(col,0,i)
    body.addLayout(grid);layout.addWidget(coverage)
    window.token_notice=label('','muted');window.token_notice.setStyleSheet('font-size:10px;');layout.addWidget(window.token_notice)
    actions=QHBoxLayout();actions.addWidget(label('Audio billing is not included.','eyebrow'),1);actions.addWidget(button('Done',dialog.close));layout.addLayout(actions)
    dialog.appear=QPropertyAnimation(dialog,b'windowOpacity',dialog);dialog.appear.setDuration(140)
    dialog.appear.setStartValue(.86);dialog.appear.setEndValue(1.);dialog.appear.setEasingCurve(QEasingCurve.OutCubic)
    return dialog

"""Compact overview with a shared 12 px rhythm and 10 px surfaces."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QSizePolicy,QLabel,QToolButton,QMenu
from .ui import label,button,line_icon,CompactComboBox
from .dashboard_widgets import Surface,HoverButton,ResourceBar,StatusDot,SessionStatus,ShimmerLabel,ShimmerIcon


def surface():
    frame=Surface();frame.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Minimum)
    body=QVBoxLayout(frame);body.setContentsMargins(12,12,12,12);body.setSpacing(8)
    return frame,body


def build_home(self):
    from .dashboard import icon_button,ActivityCalendar,HOME_ACCENT
    layout=self.page('',scrollable=True)
    layout.setContentsMargins(20,12,8,6);layout.setSpacing(12)
    header=QHBoxLayout();copy=QVBoxLayout();copy.setSpacing(3)
    title=label('Speak your mind.','title');title.setStyleSheet('font-size:24px;')
    copy.addWidget(title);copy.addWidget(label('Less typing. More flow.','muted'));header.addLayout(copy,1)
    self.stats_source=CompactComboBox();self.stats_source.addItem('Your sessions',False);self.stats_source.addItem('Demo data',True)
    self.stats_source.setParent(self)
    self.stats_source.hide();self.stats_source.currentIndexChanged.connect(self.refresh)
    self.account_button=QToolButton();self.account_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon);self.account_button.setIcon(line_icon('account'))
    self.account_button.setText(getattr(self.store,'profile',{}).get('name','Personal'));self.account_button.setMaximumWidth(170)
    self.account_button.setAutoRaise(True);self.account_button.setCursor(Qt.PointingHandCursor)
    self.account_button.setStyleSheet('QToolButton {background:transparent;border:none;color:#aaa3b5;padding:4px 2px;} QToolButton:hover,QToolButton:pressed {background:transparent;color:#d6c9fa;} QToolButton:focus {border:none;color:#d6c9fa;} QToolButton::menu-indicator {image:none;width:0;}')
    self.account_button.setToolTip('Manage local accounts');self.account_button.setAccessibleName('Local account menu')
    menu=QMenu(self.account_button);menu.addAction('Manage accounts…',self.account_requested.emit);menu.addSeparator()
    demo_action=menu.addAction('Show demo activity');demo_action.setCheckable(True);demo_action.toggled.connect(lambda checked:self.stats_source.setCurrentIndex(1 if checked else 0))
    self.account_button.setMenu(menu);self.account_button.setPopupMode(QToolButton.InstantPopup);header.addWidget(self.account_button,0,Qt.AlignRight|Qt.AlignBottom)
    from .window_chrome import CornerControls
    if not hasattr(self,'corner_controls'):self.corner_controls=CornerControls(self)
    layout.addLayout(header)
    metrics=QHBoxLayout();metrics.setSpacing(12);self.metric_values=[]
    for title in ('Characters','Recording time','Characters / min','Sessions'):
        frame,body=surface();frame.setFixedHeight(84);body.setContentsMargins(12,10,12,10);body.setSpacing(4)
        value=ShimmerLabel('0');frame.make_action(value.shimmer,'Animate '+title);value.setStyleSheet('font-size:28px;font-weight:600;color:'+HOME_ACCENT+';')
        value.setMinimumWidth(0);value.setWordWrap(False);value.setAlignment(Qt.AlignRight|Qt.AlignVCenter)
        caption=label(title,'muted');caption.setAlignment(Qt.AlignLeft|Qt.AlignVCenter);caption.setAttribute(Qt.WA_TransparentForMouseEvents);caption.setStyleSheet('font-size:12px;color:#aaa3b5;');body.addWidget(caption)
        body.addWidget(value,1)
        self.metric_values.append(value);metrics.addWidget(frame,1)
    layout.addLayout(metrics)
    columns=QHBoxLayout();columns.setSpacing(12);left=QVBoxLayout();left.setSpacing(12)
    frame,body=surface();frame.motion_enabled=False;frame.setAttribute(Qt.WA_Hover,False);self.calendar_card=frame
    body.setContentsMargins(12,6,12,6);body.setSpacing(2)
    self.activity_metrics=label('');self.activity_metrics.hide();self.activity_values=[]
    streak_box=QWidget();streak_box.setFixedHeight(26);streaks=QHBoxLayout(streak_box);streaks.setContentsMargins(0,0,0,0);streaks.setSpacing(12)
    for title in ('Active days','Current streak','Longest streak'):
        col=QHBoxLayout();col.setSpacing(6);value=label('0');value.setFixedHeight(26);value.setStyleSheet('font-size:24px;font-weight:600;color:'+HOME_ACCENT+';')
        col.addWidget(value);caption=label(title,'muted');caption.setFixedHeight(24);caption.setStyleSheet('font-size:12px;');col.addWidget(caption,1)
        streaks.addLayout(col,1);self.activity_values.append(value)
    body.addWidget(streak_box)
    self.calendar=ActivityCalendar();body.addWidget(self.calendar)
    self.calendar_legend=QWidget();caption=QHBoxLayout(self.calendar_legend);caption.setContentsMargins(0,0,0,0);caption.setSpacing(4);caption.addWidget(label('Less','eyebrow'))
    for color in ActivityCalendar.PALETTE:
        dot=QLabel();dot.setFixedSize(8,8);dot.setStyleSheet(f'background:{color};border-radius:2px;');caption.addWidget(dot)
    caption.addWidget(label('More','eyebrow'));caption.addStretch();caption.addWidget(label('26 weeks','eyebrow'))
    for name,tip,weeks in (('arrow_left','Previous four weeks',-4),('arrow_right','Next four weeks',4)):
        control=icon_button(name,tip,lambda checked=False,step=weeks:self.calendar.shift(step));control.setFixedSize(22,22);caption.addWidget(control)
    body.addWidget(self.calendar_legend)
    summary=QWidget();summary.setFixedHeight(22);summary_layout=QHBoxLayout(summary);summary_layout.setContentsMargins(0,0,0,0);summary_layout.setSpacing(10)
    self.day_summary_title=label('','muted');self.day_summary_title.setStyleSheet('font-size:12px;');summary_layout.addWidget(self.day_summary_title)
    self.day_summary=label('');self.day_summary.setMinimumWidth(0);self.day_summary.setStyleSheet('font-size:12px;');summary_layout.addWidget(self.day_summary,1)
    summary_layout.addWidget(icon_button('close','Close day summary',lambda:(summary.hide(),self.calendar_legend.show())))
    self.day_summary_row=summary;body.addWidget(summary);summary.hide();left.addWidget(frame,1)
    self.config_card,body=surface()
    self.config_card.setFixedHeight(80)
    self.config_card.make_action(lambda:[value.shimmer() for value in self.config_shimmers],'Animate current configuration')
    heading=QHBoxLayout();heading.addWidget(label('Current configuration'),1)
    saved=label('Saved','eyebrow');saved.setToolTip('The configuration applied to sessions. Unsaved settings are not shown here.');heading.addWidget(saved)
    heading.addWidget(icon_button('settings','Configure services',lambda:self.navigate(3)));body.addLayout(heading)
    body.setContentsMargins(12,2,12,10);body.setSpacing(2)
    self.config_labels={};self.config_icons={};self.config_dots={};self.config_shimmers=[];services=QHBoxLayout();services.setSpacing(14)
    for key,title in (('asr','Speech'),('llm','Writing'),('ask','Ask')):
        item=QHBoxLayout();item.setSpacing(6);column=QVBoxLayout();column.setSpacing(0)
        dot=StatusDot();dot.set_state('pending','Not checked yet');item.addWidget(dot,0,Qt.AlignVCenter);self.config_dots[key]=dot
        mark=ShimmerIcon();mark.setFixedSize(18,18);item.addWidget(mark,0,Qt.AlignVCenter);self.config_icons[key]=mark
        name=ShimmerLabel(title);name.setObjectName('muted');name.setStyleSheet('font-size:12px;');name.setFixedHeight(14);column.addWidget(name)
        value=ShimmerLabel('');value.setMinimumWidth(0);value.setWordWrap(False);value.setStyleSheet('font-size:12px;')
        value.setFixedHeight(18)
        value.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred);column.addWidget(value);self.config_labels[key]=value
        self.config_shimmers.extend((mark,name,value))
        item.addLayout(column,1)
        services.addLayout(item,1)
    body.addLayout(services);left.addWidget(self.config_card);columns.addLayout(left,1)
    aside=QWidget();aside.setFixedWidth(224);right=QVBoxLayout(aside);right.setContentsMargins(0,0,0,0);right.setSpacing(12)
    shortcuts,body=surface();self.shortcuts_card=shortcuts;shortcuts.setMinimumHeight(156);body.setContentsMargins(12,8,12,8);body.setSpacing(4);heading=QHBoxLayout();heading.addWidget(label('Shortcuts'),1)
    heading.addWidget(icon_button('settings','Edit shortcuts',self.open_shortcut_settings));body.addLayout(heading)
    self.quick_keycaps={};self.shortcut_shimmers=[]
    shortcuts.make_action(lambda:[value.shimmer() for value in self.shortcut_shimmers],'Animate shortcuts')
    body.addStretch(1)
    for key,title in [('dictation_key','Dictation'),('translation_key','Translate'),('ask_key','Ask Anything'),('selection_key','Edit selection')]:
        item=QHBoxLayout();item.setSpacing(4);caption=ShimmerLabel(title);caption.setObjectName('muted');caption.setStyleSheet('font-size:12px;');self.shortcut_shimmers.append(caption);item.addWidget(caption,1)
        keys=QHBoxLayout();keys.setSpacing(4);caps=[]
        for _ in range(3):
            cap=ShimmerLabel();self.shortcut_shimmers.append(cap);cap.setWordWrap(False);cap.setStyleSheet('font-size:12px;background:#37333e;border:1px solid #4a4357;border-radius:4px;padding:2px 3px;')
            keys.addWidget(cap);caps.append(cap)
        self.quick_keycaps[key]=caps;item.addLayout(keys);body.addLayout(item)
    right.addWidget(shortcuts,1)
    usage,body=surface();self.usage_card=usage;self.usage_shimmers=[]
    usage.setFixedHeight(136);body.setContentsMargins(12,8,12,8);body.setSpacing(6)
    usage.make_action(lambda:[value.shimmer() for value in self.usage_shimmers],'Animate token usage')
    def usage_label(text,kind=None):
        value=ShimmerLabel(text)
        if kind:value.setObjectName(kind)
        self.usage_shimmers.append(value);return value
    heading=QHBoxLayout();heading.addWidget(usage_label('Token usage'),1)
    self.token_insight_button=icon_button('arrow_right','View token usage details',self.show_token_insights);heading.addWidget(self.token_insight_button);body.addLayout(heading)
    counts=QHBoxLayout();counts.setSpacing(12)
    for name,title in (('home_local_tokens','Local'),('home_external_tokens','External')):
        col=QVBoxLayout();col.setSpacing(1);col.addWidget(usage_label(title,'eyebrow'));value=usage_label('0');value.setWordWrap(False)
        value.setMinimumWidth(0);value.setStyleSheet('font-size:28px;font-weight:600;color:'+HOME_ACCENT+';');setattr(self,name,value)
        col.addWidget(value);counts.addLayout(col,1)
    body.addLayout(counts);cost=QHBoxLayout();cost.addWidget(usage_label('Known cost','eyebrow'),1)
    self.home_cost_hint=usage_label('$0');self.home_cost_hint.setStyleSheet('font-size:12px;color:'+HOME_ACCENT+';');self.home_cost_hint.setWordWrap(False)
    cost.addWidget(self.home_cost_hint);body.addLayout(cost);right.addWidget(usage);columns.addWidget(aside)
    layout.addLayout(columns,1)
    resources,body=surface();body.setContentsMargins(12,9,12,9);row=QHBoxLayout();row.setSpacing(12)
    self.resource_card=resources;self.resource_shimmers=[]
    resources.make_action(lambda:[value.shimmer() for value in self.resource_shimmers],'Animate resource usage')
    self.resource_labels={};self.resource_bars={}
    for key,title,color in (('cpu','MurMur CPU','#c7b8fa'),('memory','Memory','#9dbbc5'),('gpu','GPU memory','#b9c99b')):
        col=QVBoxLayout();col.setSpacing(0);col.setContentsMargins(0,0,0,4);top=QHBoxLayout();top.setSpacing(5)
        caption=ShimmerLabel(title);caption.setObjectName('eyebrow');caption.setStyleSheet('font-size:12px;');caption.setWordWrap(False);top.addWidget(caption,1)
        value=ShimmerLabel('—');value.setWordWrap(False);value.setStyleSheet('font-size:12px;');top.addWidget(value);self.resource_labels[key]=value;col.addLayout(top)
        bar=ResourceBar(color);col.addStretch(1);col.addWidget(bar);self.resource_bars[key]=bar;row.addLayout(col,1)
        self.resource_shimmers.extend((caption,value,bar))
    release=QVBoxLayout();release.setSpacing(2)
    self.version_label=label('Version '+self.version_text,'eyebrow');self.version_label.setStyleSheet('font-size:12px;');self.version_label.setWordWrap(False);release.addWidget(self.version_label)
    self.release_status=label('Check stable releases','muted');self.release_status.setStyleSheet('font-size:12px;')
    self.release_status.setMinimumWidth(0);self.release_status.setWordWrap(False);release.addWidget(self.release_status);row.addLayout(release)
    self.release_check_button=icon_button('refresh','Check GitHub releases',self.request_release_check);row.addWidget(self.release_check_button)
    self.release_open_button=icon_button('external','Open releases on GitHub',self.open_release_page);row.addWidget(self.release_open_button)
    body.addLayout(row);layout.addWidget(resources)
    footer=QVBoxLayout();footer.setSpacing(6);self.home_status=SessionStatus(self)
    actions=QHBoxLayout();actions.setSpacing(8)
    for name,text,callback,primary in [('record_button','Record to preview',self.record.emit,True),('translation_button','Translate',self.translate.emit,False),
                                     ('ask_button','Ask Anything',self.ask.emit,False),('edit_selection_button','Edit selection',self.preview.emit,False)]:
        control=HoverButton(text)
        if primary:control.setObjectName('primary');control.setIcon(line_icon('mic',14,'#282035'))
        control.clicked.connect(callback);setattr(self,name,control);actions.addWidget(control)
    actions.addStretch();actions.addWidget(icon_button('chart','Activity details',self.show_activity_details));actions.addWidget(icon_button('info','How insights are measured',self.explain_metrics))
    footer.addLayout(actions);layout.addLayout(footer)

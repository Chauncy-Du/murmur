"""A compact English desktop shell with local history and reviewed vocabulary."""
import calendar as calendar_names
import sqlite3
import threading
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta
from PySide6.QtCore import Qt, Signal, QPointF, QRectF, QSize, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QShortcut, QKeySequence
from PySide6.QtWidgets import *
from .ui import SettingsForm, CompactComboBox, AdvancedSection, button, label, icon, line_icon, dark_titlebar
from .insights import insights, analyze_vocabulary
from .usage import is_local_endpoint
from .storage import default_offline_model_dir

MODE_NAMES = {'听写': 'Dictation', '翻译': 'Translation', '润色': 'Refine', '总结': 'Summary', '扩写': 'Expand', '自定义': 'Custom', '语音指令': 'Voice instruction', '随便问': 'Ask Anything', '语音编辑': 'Voice edit', '问答': 'Question', '起草': 'Draft'}
ASK_MODES = {'随便问', '语音编辑', '问答', '起草'}
LANGUAGE_NAMES = {'中文': 'Chinese', '混合': 'Mixed', '英文/其他': 'English / other', '未知': 'Unknown'}
HOME_ACCENT = '#c7b8fa'


def compact_count(value):
    if value < 10000:return f'{value:,}'
    for scale, suffix in ((10**12,'T'),(10**9,'B'),(10**6,'M'),(10**3,'K')):
        if value >= scale * .99995:
            return f'{value / scale:.1f}'.rstrip('0').rstrip('.') + suffix


def compact_cost(value):
    if 0 < value < .000001:return '<$0.000001'
    if value >= 10000:return '$' + compact_count(value)
    return '$' + (f'{value:.6f}' if value < 1 else f'{value:,.2f}').rstrip('0').rstrip('.')


def human_date(value):
    day = date.fromisoformat(value[:10]) if isinstance(value, str) else value
    if day == date.today():
        return 'Today'
    if day == date.today() - timedelta(days=1):
        return 'Yesterday'
    return f'{calendar_names.month_abbr[day.month]} {day.day}, {day.year}'


def duration_text(seconds):
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        return f'{seconds // 3600}h {(seconds % 3600) // 60}m'
    if seconds >= 60:
        return f'{seconds // 60}m {seconds % 60}s'
    return f'{seconds}s'


def card():
    frame = QFrame()
    frame.setObjectName('card')
    frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 13, 16, 13)
    layout.setSpacing(6)
    return frame, layout


def icon_button(name, tooltip, callback=None):
    b = QToolButton()
    b.setIcon(line_icon(name))
    b.setIconSize(QSize(16, 16))
    b.setFixedSize(26, 26)
    b.setToolTip(tooltip)
    b.setAccessibleName(tooltip)
    b.setCursor(Qt.PointingHandCursor)
    if callback:
        b.clicked.connect(callback)
    return b


class ActivityCalendar(QWidget):
    day_clicked = Signal(str)
    PALETTE = ['#434048', '#4c3c69', '#6b5193', '#9570c4', HOME_ACCENT]
    GAP = 4

    def __init__(self):
        super().__init__()
        self.daily = {}
        self.cells = []
        self.end = date.today()
        self.setFixedHeight(140)
        self.setMouseTracking(True)
        self.hover_day = None
        self.setAccessibleName('Activity calendar. Select a day to view sessions.')

    def set_data(self, daily):
        self.daily = daily
        self.update()

    def shift(self, weeks):
        self.end = min(date.today(), self.end + timedelta(weeks=weeks))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        font = p.font()
        font.setPixelSize(10)
        p.setFont(font)
        self.cells = []
        columns = 26
        dpr = max(1., self.devicePixelRatioF())
        left, top = round(24 * dpr) / dpr, round(6 * dpr) / dpr
        gap = round(self.GAP * dpr) / dpr
        desired = (self.width() - left - (columns - 1) * gap) / columns
        size = int(max(6, min(12, desired)) * dpr) / dpr
        step = size + gap
        start = self.end - timedelta(days=(self.end.weekday() + 1) % 7 + 25 * 7)
        maximum = max(self.daily.values(), default=1)
        first_activity = min(self.daily, default=start)
        for r, text in enumerate(('S', 'M', 'T', 'W', 'T', 'F', 'S')):
            p.setPen(QColor('#9696a2'))
            p.drawText(0, int(top + r * step + size / 2 + 3), text)
        for c in range(columns):
            sunday = start + timedelta(weeks=c)
            if c == 0 or sunday.month != (sunday - timedelta(weeks=1)).month:
                p.setPen(QColor('#9696a2'))
                p.drawText(int(left + c * step), int(top + 7 * step + 13), calendar_names.month_abbr[sunday.month])
            for r in range(7):
                day = sunday + timedelta(days=r)
                if day > self.end:
                    continue
                count = self.daily.get(day, 0)
                level = 0 if not count else max(1, min(4, int(count / maximum * 4)))
                rect = QRectF(left + c * step, top + r * step, size, size)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(self.PALETTE[level]))
                p.drawRoundedRect(rect, 2.5, 2.5)
                if day < first_activity:
                    p.save()
                    clip = QPainterPath();clip.addRoundedRect(rect, 2.5, 2.5)
                    p.setClipPath(clip)
                    p.fillRect(rect, QColor('#353438'))
                    p.setPen(QPen(QColor('#4b494f'), .6))
                    for stripe in range(-12, 25, 4):
                        p.drawLine(rect.topLeft() + QPointF(stripe, size), rect.topLeft() + QPointF(stripe + size, 0))
                    p.restore()
                if day == self.hover_day:
                    p.setPen(QPen(QColor('#e5dbff'), 1))
                    p.setBrush(Qt.NoBrush)
                    p.drawRoundedRect(rect.adjusted(.5, .5, -.5, -.5), 2, 2)
                self.cells.append((rect, day, count))

    def mouseMoveEvent(self, event):
        for rect, day, count in self.cells:
            if rect.contains(event.position()):
                if self.hover_day != day:
                    self.hover_day = day;self.update()
                self.setCursor(Qt.PointingHandCursor)
                self.setToolTip(f'{human_date(day)} · {count} session' + ('' if count == 1 else 's'))
                return
        self.unsetCursor()
        self.setToolTip('')
        if self.hover_day is not None:self.hover_day = None;self.update()

    def leaveEvent(self, event):
        self.hover_day = None;self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        for rect, day, count in self.cells:
            if rect.contains(event.position()):
                self.day_clicked.emit(day.isoformat())
                return


class MainWindow(SettingsForm):
    analysis_ready = Signal(object, str)
    install_offline = Signal()
    cancel = Signal()
    service_test = Signal(str, dict, dict)
    ask = Signal()

    def __init__(self, store):
        QMainWindow.__init__(self)
        self.store = store
        self.fields = {}
        self.prompt_fields = {}
        self.service_test_controls = {'asr': [], 'llm': [], 'ask': []}
        self.service_test_results = {}
        self.service_test_success = {}
        self.service_model_metadata = {}
        self.service_test_busy = {'asr': False, 'llm': False, 'ask': False}
        self.service_test_dialogs = {}
        self._llm_provider = None
        self._llm_profiles = {}
        self._llm_profile_syncing = False
        self._llm_source_syncing = False
        self._llm_source_profiles = {}
        self._offline_engine = None
        self._offline_acceleration = None
        self._offline_model_dirs = {}
        self._offline_download_busy = False
        self.current_rows = []
        self.day_filter = ''
        self.history_limit = 60
        self.analysis_version = 0
        self._session_phase = 'idle'
        self._session_mode = None
        self.history_record_button = None
        self.escape_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self.escape_shortcut.setContext(Qt.WindowShortcut)
        self.escape_shortcut.setAutoRepeat(False)
        self.escape_shortcut.setEnabled(False)
        self.escape_shortcut.activated.connect(self.cancel.emit)
        self.setWindowTitle('MurMur')
        self.setWindowIcon(icon())
        self.setFixedSize(920, 680)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, False)
        self.setWindowFlag(Qt.MSWindowsFixedSizeDialogHint, True)
        self._settings_return_page = 0
        root = QWidget()
        root.setObjectName('page')
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(0)
        side = QFrame()
        self.main_sidebar = side
        side.setObjectName('sidebar')
        side.setFixedWidth(160)
        nav = QVBoxLayout(side)
        nav.setContentsMargins(10, 20, 10, 14)
        nav.setSpacing(6)
        brand = QHBoxLayout()
        brand.setContentsMargins(9, 0, 0, 0)
        mark = QLabel()
        mark.setPixmap(line_icon('waveform', 18, '#c7b8fa').pixmap(18, 18))
        brand.addWidget(mark)
        brand.addWidget(label('MurMur', 'brand'))
        brand.addStretch()
        nav.addLayout(brand)
        nav.addSpacing(20)
        self.stack = QStackedWidget()
        self.nav_buttons = []
        for i, (text, name) in enumerate((('Home', 'home'), ('History', 'history'), ('Dictionary', 'dictionary'))):
            b = button(text, lambda checked=False, index=i: self.navigate(index), navigation=True)
            b.setIcon(line_icon(name))
            b.setObjectName('nav')
            b.setCheckable(True)
            nav.addWidget(b)
            self.nav_buttons.append(b)
        nav.addStretch()
        self.badge = label('Demo mode', 'muted')
        self.badge.setStyleSheet('font-size:11px;padding:0 9px;')
        nav.addWidget(self.badge)
        nav.addSpacing(8)
        b = button('Settings', lambda: self.navigate(3), navigation=True)
        b.setIcon(line_icon('settings'))
        b.setObjectName('nav')
        b.setCheckable(True)
        nav.addWidget(b)
        self.nav_buttons.append(b)
        version = label('0.4.0 · Stored locally', 'muted')
        version.setStyleSheet('font-size:10px;padding:0 9px;')
        nav.addWidget(version)
        outer.addWidget(side)
        outer.addWidget(self.stack, 1)
        self.overview()
        self.history()
        self.dictionary()
        self.settings()
        self.analysis_ready.connect(self.show_analysis)
        self.navigate(0)

    def page(self, title, subtitle='', scrollable=True):
        content = QWidget()
        content.setObjectName('page')
        layout = QVBoxLayout(content)
        layout.setSizeConstraint(QLayout.SetNoConstraint if scrollable else QLayout.SetMinimumSize)
        if scrollable:
            content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        layout.setContentsMargins(24, 20, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(label(title, 'title'))
        if subtitle:
            layout.addWidget(label(subtitle, 'muted'))
        if scrollable:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(content)
            self.stack.addWidget(scroll)
        else:
            self.stack.addWidget(content)
        return layout

    def overview(self):
        layout = self.page('Speak your mind.', 'Less typing. More flow.')
        layout.setSpacing(10)
        page = layout.parentWidget()
        page.setStyleSheet('QFrame#homeInsight{background:#333137;border:1px solid #3c3942;border-radius:16px;}QFrame#homeAside{background:#2b292e;border:1px solid #343139;border-radius:14px;}QLabel#metric{font-size:22px;font-weight:600;color:'+HOME_ACCENT+';}')
        head = QHBoxLayout()
        head.addWidget(label('Insights'))
        head.addStretch()
        self.stats_source = CompactComboBox()
        self.stats_source.addItem('Your sessions', False)
        self.stats_source.addItem('Demo data', True)
        self.stats_source.setFixedWidth(138)
        self.stats_source.currentIndexChanged.connect(self.refresh)
        head.addWidget(self.stats_source)
        layout.addLayout(head)
        columns = QHBoxLayout()
        columns.setSpacing(14)
        main = QVBoxLayout()
        main.setSpacing(10)
        grid = QGridLayout()
        grid.setSpacing(10)
        self.metric_values = []
        for i, title in enumerate(('Characters', 'Recording time', 'Characters per minute', 'Sessions')):
            frame, body = card()
            frame.setObjectName('homeInsight')
            frame.setFixedHeight(68)
            body.setContentsMargins(14, 9, 14, 9)
            body.setSpacing(3)
            value = label('0', 'metric')
            body.addWidget(value)
            caption = label(title, 'muted')
            caption.setStyleSheet('font-size:11px;color:#b2acba;')
            body.addWidget(caption)
            self.metric_values.append(value)
            grid.addWidget(frame, i // 2, i % 2)
        main.addLayout(grid)
        frame, body = card()
        frame.setObjectName('homeInsight')
        body.setContentsMargins(14, 13, 14, 10)
        body.setSpacing(8)
        self.activity_metrics = label('')
        self.activity_metrics.hide()
        streaks = QHBoxLayout()
        streaks.setSpacing(12)
        self.activity_values = []
        for title in ('Active days', 'Current streak', 'Longest streak'):
            metric = QVBoxLayout()
            metric.setSpacing(2)
            value = label('0')
            value.setStyleSheet('font-size:21px;font-weight:600;color:'+HOME_ACCENT+';')
            metric.addWidget(value)
            caption = label(title, 'muted')
            caption.setStyleSheet('font-size:10px;color:#b2acba;')
            caption.setWordWrap(False)
            metric.addWidget(caption)
            streaks.addLayout(metric, 1)
            self.activity_values.append(value)
        body.addLayout(streaks)
        body.addSpacing(5)
        self.calendar = ActivityCalendar()
        self.calendar.day_clicked.connect(self.filter_day)
        body.addWidget(self.calendar)
        caption = QHBoxLayout()
        caption.setSpacing(4)
        caption.addWidget(label('Less', 'eyebrow'))
        for color in ActivityCalendar.PALETTE:
            dot = QLabel()
            dot.setFixedSize(9, 9)
            dot.setStyleSheet(f'background:{color};border-radius:2px;')
            caption.addWidget(dot)
        caption.addWidget(label('More', 'eyebrow'))
        caption.addStretch()
        note = label('26 weeks', 'muted')
        note.setStyleSheet('font-size:10px;')
        note.setWordWrap(False)
        caption.addWidget(note)
        caption.addWidget(icon_button('arrow_left', 'Previous four weeks', lambda: self.calendar.shift(-4)))
        caption.addWidget(icon_button('arrow_right', 'Next four weeks', lambda: self.calendar.shift(4)))
        body.addLayout(caption)
        main.addWidget(frame)
        main.addStretch()
        columns.addLayout(main, 1)
        aside = QWidget()
        aside.setFixedWidth(164)
        aside_layout = QVBoxLayout(aside)
        aside_layout.setContentsMargins(0, 0, 0, 0)
        aside_layout.setSpacing(12)
        shortcuts, shortcut_body = card()
        shortcuts.setObjectName('homeAside')
        shortcut_body.setContentsMargins(12, 12, 12, 12)
        shortcut_body.setSpacing(12)
        heading = QHBoxLayout()
        heading.addWidget(label('Shortcuts'), 1)
        heading.addWidget(icon_button('settings', 'Edit shortcuts', self.open_shortcut_settings))
        shortcut_body.addLayout(heading)
        self.quick_keycaps = {}
        for key, title in [('dictation_key', 'Dictation'), ('translation_key', 'Translate'), ('ask_key', 'Ask Anything'), ('selection_key', 'Edit selection')]:
            item = QVBoxLayout()
            item.setSpacing(5)
            title_label = label(title, 'muted')
            title_label.setStyleSheet('font-size:11px;color:#b6b0bf;')
            item.addWidget(title_label)
            keys = QHBoxLayout()
            keys.setSpacing(4)
            caps = []
            for _ in range(3):
                cap = QLabel()
                cap.setWordWrap(False)
                cap.setStyleSheet('font-size:10px;background:#39363e;border:1px solid #504b58;border-radius:4px;padding:2px 4px;')
                keys.addWidget(cap)
                caps.append(cap)
            keys.addStretch()
            self.quick_keycaps[key] = caps
            item.addLayout(keys)
            shortcut_body.addLayout(item)
        aside_layout.addWidget(shortcuts)
        usage, usage_body = card()
        usage.setObjectName('homeAside')
        usage_body.setContentsMargins(12, 12, 12, 12)
        usage_body.setSpacing(8)
        usage_heading = QHBoxLayout()
        usage_heading.setSpacing(2)
        usage_heading.addWidget(label('Token usage'), 1)
        self.token_insight_button = icon_button('arrow_right', 'View token usage details', self.show_token_insights)
        self.token_insight_button.setIcon(line_icon('arrow_right',14,HOME_ACCENT))
        usage_heading.addWidget(self.token_insight_button)
        usage_body.addLayout(usage_heading)
        token_counts = QHBoxLayout()
        token_counts.setSpacing(8)
        for name, title in (('home_local_tokens','Local'),('home_external_tokens','External')):
            column = QVBoxLayout()
            column.setSpacing(2)
            caption = label(title,'muted')
            caption.setStyleSheet('font-size:10px;')
            column.addWidget(caption)
            value = label('0')
            value.setWordWrap(False)
            value.setMinimumWidth(0)
            value.setStyleSheet('font-size:18px;font-weight:600;color:'+HOME_ACCENT+';')
            setattr(self,name,value)
            column.addWidget(value)
            token_counts.addLayout(column,1)
        usage_body.addLayout(token_counts)
        cost = QVBoxLayout()
        cost.setSpacing(2)
        cost_caption = label('Known API cost · USD','muted')
        cost_caption.setStyleSheet('font-size:10px;')
        cost.addWidget(cost_caption)
        self.home_cost_hint = label('$0')
        self.home_cost_hint.setWordWrap(False)
        self.home_cost_hint.setStyleSheet('font-size:14px;font-weight:600;color:'+HOME_ACCENT+';')
        cost.addWidget(self.home_cost_hint)
        usage_body.addLayout(cost)
        aside_layout.addWidget(usage)
        aside_layout.addStretch()
        columns.addWidget(aside)
        layout.addLayout(columns, 1)
        self.home_status = label('', 'muted')
        self.home_status.setStyleSheet('font-size:11px;')
        layout.addWidget(self.home_status)
        actions = QHBoxLayout()
        record = button('Record to preview', self.record.emit, True)
        record.setIcon(line_icon('mic', 14, '#282035'))
        self.record_button = record
        actions.addWidget(record)
        self.translation_button = button('Translate', self.translate.emit)
        actions.addWidget(self.translation_button)
        self.ask_button = button('Ask Anything', self.ask.emit)
        actions.addWidget(self.ask_button)
        self.edit_selection_button = button('Edit selection', self.preview.emit)
        actions.addWidget(self.edit_selection_button)
        actions.addStretch()
        actions.addWidget(icon_button('chart', 'Activity details', self.show_activity_details))
        actions.addWidget(icon_button('info', 'How insights are measured', self.explain_metrics))
        layout.addLayout(actions)

    def navigate(self, index):
        if index == 3 and self.stack.currentIndex() != 3:
            self._settings_return_page = max(0, self.stack.currentIndex())
        self.main_sidebar.setVisible(index != 3)
        super().navigate(index)

    def open_shortcut_settings(self):
        self.navigate(3)
        self.settings_tabs.setCurrentIndex(2)

    def refresh_shortcuts(self):
        keys = {'right_alt': ('Right Alt',), 'f8': ('F8',), 'f9': ('F9',), 'disabled': ('Disabled',), 'alt+shift': ('Alt', 'Shift'), 'ctrl+shift+f9': ('Ctrl', 'Shift', 'F9'), 'alt+space': ('Left Alt', 'Space'), 'ctrl+shift+space': ('Ctrl', 'Shift', 'Space'), 'right_alt+space': ('Right Alt', 'Space'), 'ctrl+shift+a': ('Ctrl', 'Shift', 'A')}
        for key, caps in self.quick_keycaps.items():
            selected = keys.get(self.store.config[key], ('Disabled',))
            for i, cap in enumerate(caps):
                cap.setVisible(i < len(selected))
                if i < len(selected):cap.setText(selected[i])

    def set_session_state(self, phase=None, mode=None):
        """Update shared recording controls; the controller remains the authority."""
        aliases = {'启动': 'startup', 'starting': 'startup', '录音': 'recording', '等待停止': 'stopping', 'waiting': 'stopping', '识别': 'transcribing', 'recognizing': 'transcribing', '整理': 'refining'}
        normalized = aliases.get(phase, phase.lower() if isinstance(phase, str) else 'idle')
        if normalized in ('待机', '完成', '失败', '取消', 'idle', 'ready', 'done', 'result', 'failed', 'error', 'cancel', 'cancelled', 'canceled', ''):
            normalized = 'idle'
        mode = {'dictation': '听写', 'translation': '翻译', 'instruction': '指令'}.get(mode, mode)
        self._session_phase = normalized
        self._session_mode = mode
        idle = normalized == 'idle'
        checking_asr = bool(self.service_test_busy['asr'])
        can_start = idle and not checking_asr
        self.escape_shortcut.setEnabled(not idle)
        recording = normalized in ('startup', 'recording')
        processing = not idle and not recording

        for control in (self.record_button, self.history_record_button):
            if control is None:
                continue
            active = recording and mode == '听写'
            control.setText('Processing…' if processing else 'Stop recording' if active else 'Record to preview')
            control.setEnabled(can_start or active)
            control.setIcon(line_icon('stop' if active else 'mic', 14, '#282035'))
            control.setToolTip('Finish recording and prepare a preview. Esc cancels.' if active else 'Wait for the current session. Esc cancels.' if not idle else 'Recording here opens a preview. Use your configured shortcut in another app to insert text safely.')
            if idle and checking_asr:
                control.setToolTip('Wait for the speech recognition check to finish.')
        translation_active = recording and mode == '翻译'
        self.translation_button.setText('Processing…' if processing and mode == '翻译' else 'Stop recording' if translation_active else 'Translate')
        self.translation_button.setEnabled(can_start or translation_active)
        self.translation_button.setToolTip('Finish the translation recording. Esc cancels.' if translation_active else 'Wait for the current session. Esc cancels.' if not idle else 'Record a translation for preview. Use the translation shortcut in another app to insert the result safely.')
        if idle and checking_asr:
            self.translation_button.setToolTip('Wait for the speech recognition check to finish.')
        self.edit_selection_button.setEnabled(idle)
        ask_active = recording and mode == '随便问'
        self.ask_button.setText('Processing…' if processing and mode == '随便问' else 'Stop recording' if ask_active else 'Ask Anything')
        self.ask_button.setEnabled((can_start and not self.service_test_busy['ask']) or ask_active)
        self.ask_button.setToolTip('Right Alt finishes Ask Anything. Esc cancels.' if ask_active else 'Ask by voice. Use Right Alt + Space in another app for selection context and automatic writing.')
        if idle:
            status = 'Checking speech recognition…' if checking_asr else 'Demo mode · Sample output stays in preview. No API requests.' if self.store.config['demo'] else 'Buttons open a preview · Use a shortcut in another app to insert safely.'
        elif recording:
            status = ('Starting recording' if normalized == 'startup' else 'Recording') + ' · Click Stop recording to finish. Esc cancels.'
            if mode == '随便问':
                status = 'Ask Anything · Right Alt or Stop recording to finish. Esc cancels.'
            elif mode not in ('听写', '翻译'):
                status = 'Voice instruction recording · Use the capsule to finish. Esc cancels.'
        else:
            status = {'stopping': 'Stopping recording…', 'transcribing': 'Transcribing…', 'refining': 'Refining your text…'}.get(normalized, 'Processing…') + ' · Esc cancels.'
        self.home_status.setText(status)
        self.update_settings_actions()

    def update_settings_actions(self):
        allowed = self._session_phase == 'idle' and not any(self.service_test_busy.values())
        hints={'save_button':'Save your current settings.',
               'remove_keys_button':'Remove saved service credentials.',
               'remove_ask_key_button':'Remove only the saved Ask Anything key.'}
        for name,hint in hints.items():
            control = getattr(self, name, None)
            if control:
                control.setEnabled(allowed)
                control.setToolTip(hint if allowed else 'Finish the current session or connection test first.')
        if hasattr(self, '_service_settings'):
            self._service_settings.refresh()
        return allowed

    def show_token_insights(self):
        if not hasattr(self, 'token_dialog'):
            self.token_dialog = QDialog(self)
            self.token_dialog.setWindowTitle('MurMur · Token usage')
            self.token_dialog.setWindowIcon(icon())
            self.token_dialog.setFixedSize(420, 330)
            self.token_dialog.setWindowFlag(Qt.MSWindowsFixedSizeDialogHint, True)
            self.token_dialog.setModal(False)
            layout = QVBoxLayout(self.token_dialog)
            layout.setContentsMargins(18, 16, 18, 16)
            layout.setSpacing(10)
            layout.addWidget(label('Token usage', 'title'))
            form = QFormLayout()
            form.setVerticalSpacing(7)
            self.token_values = {}
            for key, title in [('local_tokens', 'Local tokens'), ('external_tokens', 'External tokens'), ('external_cost_usd', 'Known external cost (USD)'), ('requests', 'Requests'), ('estimated_tokens', 'Estimated tokens'), ('unpriced_calls', 'Unpriced calls'), ('missing_usage_calls', 'Requests without usage')]:
                value = label('Not available')
                self.token_values[key] = value
                form.addRow(title, value)
            layout.addLayout(form)
            self.token_notice = label('Token counts may include estimates. Unpriced calls are listed separately.', 'muted')
            self.token_notice.setStyleSheet('font-size:11px;')
            layout.addWidget(self.token_notice)
        self.refresh_token_insights()
        self.token_dialog.show()
        dark_titlebar(self.token_dialog)
        self.token_dialog.raise_()
        self.token_dialog.activateWindow()

    def refresh_token_insights(self):
        getter = getattr(self.store, 'usage_totals', None)
        try:
            totals = getter() if getter else {}
        except Exception:
            totals = {}
        if hasattr(self,'home_local_tokens'):
            for widget,key,title in ((self.home_local_tokens,'local_tokens','Local'),(self.home_external_tokens,'external_tokens','External')):
                total=int(totals.get(key,0))
                widget.setText(compact_count(total))
                widget.setToolTip(f'{title} · {total:,} API-reported tokens. View details for complete usage.')
                widget.setAccessibleName(f'{title}: {total:,} tokens')
        if hasattr(self, 'home_external_tokens'):
            cost = totals.get('external_cost_usd')
            self.home_cost_hint.setText('Unknown' if cost is None else compact_cost(float(cost)))
            unpriced=int(totals.get('unpriced_calls',0))
            cost_detail='Unknown' if cost is None else f'${float(cost):.6f} USD'
            self.home_cost_hint.setToolTip(f'Known API cost: {cost_detail}. Excludes audio billing and {unpriced:,} unpriced calls.')
            self.home_cost_hint.setAccessibleName('Known API cost: '+cost_detail)
            self.token_insight_button.setToolTip('View token usage details'+(f' · Cost excludes {unpriced:,} unpriced calls' if unpriced else ''))
        if not hasattr(self, 'token_dialog'):return
        for key, widget in self.token_values.items():
            value = totals.get(key)
            widget.setText('Not available' if value is None else f'${float(value):.6f}' if key == 'external_cost_usd' else f'{int(value):,}')
        since = totals.get('tracked_since')
        tracked = 'Tracked since ' + str(since).split('T')[0] if since else 'Usage tracked from this version'
        self.token_notice.setText(tracked + ' · Requests without usage are excluded. Cost excludes unpriced calls.')

    def explain_metrics(self):
        QMessageBox.information(self, 'How insights are measured', 'Insights include dictation and voice translation. Demo sessions are counted separately.\n\nCharacters: non-whitespace characters in the final output.\nRecording time: from recording start to stop.\nSpeed: characters divided by recording minutes.\nActive days: dates with at least one voice session.\nCurrent streak: consecutive active days ending today or yesterday.\nProcessing time: from recording stop to result readiness.\nLanguage: estimated from the original transcript using character rules; mixed and unknown are retained.\n\nDeleting history or applying retention changes these totals. Activity details group records by local day or Monday-starting week.')

    def show_activity_details(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('MurMur · Activity details')
        dialog.setFixedSize(740, 440)
        dialog.setWindowFlag(Qt.MSWindowsFixedSizeDialogHint, True)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        row = QHBoxLayout()
        row.addWidget(label('Activity details', 'title'), 1)
        grouping = CompactComboBox()
        grouping.addItems(['Daily', 'Weekly'])
        row.addWidget(grouping)
        layout.addLayout(row)
        layout.addWidget(label(('Demo sessions' if self.stats_source.currentData() else 'Your sessions') + ' · Dictation and voice translation only', 'muted'))
        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(['Period', 'Sessions', 'Characters', 'Recorded', 'Avg. processing', 'Languages'])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        table.setStyleSheet('QTableWidget{background:#242428;border:1px solid #36363c;gridline-color:#36363c;}QHeaderView::section{background:#29292d;color:#a4a4ae;border:0;padding:7px;}')
        layout.addWidget(table, 1)
        layout.addWidget(label('Language estimates use character rules. Processing starts when recording stops.', 'muted'))

        def fill():
            grouped = defaultdict(list)
            for r in self.store.rows():
                if bool(r['demo']) != bool(self.stats_source.currentData()) or r['mode'] not in ('听写', '翻译'):
                    continue
                day = datetime.fromisoformat(r['time']).date()
                if grouping.currentIndex():
                    day -= timedelta(days=day.weekday())
                grouped[day].append(r)
            table.setRowCount(len(grouped))
            for index, (day, rows) in enumerate(sorted(grouped.items(), reverse=True)):
                chars = sum(sum(not char.isspace() for char in r['final']) for r in rows)
                languages = Counter(LANGUAGE_NAMES.get(r['language'], r['language']) for r in rows)
                values = [day.isoformat(), str(len(rows)), f'{chars:,}', duration_text(sum(r['duration'] for r in rows)), f'{sum(r["latency"] for r in rows) / len(rows):.2f}s', ', '.join(f'{k}: {v}' for k, v in languages.items())]
                for col, value in enumerate(values):
                    table.setItem(index, col, QTableWidgetItem(value))
            if not grouped:
                table.setRowCount(1)
                table.setItem(0, 0, QTableWidgetItem('No sessions yet'))
        grouping.currentIndexChanged.connect(fill)
        fill()
        dark_titlebar(dialog)
        dialog.exec()

    def history(self):
        layout = self.page('History')
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search your sessions')
        self.search.addAction(line_icon('search', 14), QLineEdit.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.reset_history_filters)
        row.addWidget(self.search, 1)
        self.history_mode = CompactComboBox()
        for text, data in [('All sessions', 'all'), ('Dictation', '听写'), ('Translation', '翻译'), ('Text edits', 'edits'), ('Ask Anything', 'ask'), ('Voice edits', '语音编辑'), ('Questions', '问答'), ('Drafts', '起草')]:
            self.history_mode.addItem(text, data)
        self.history_mode.currentIndexChanged.connect(self.reset_history_filters)
        self.history_mode.setFixedWidth(125)
        row.addWidget(self.history_mode)
        export = button('Export', self.export_history)
        export.setIcon(line_icon('export', 14))
        row.addWidget(export)
        layout.addLayout(row)
        self.filter_label = label('', 'muted')
        self.filter_label.setStyleSheet('font-size:11px;')
        layout.addWidget(self.filter_label)
        self.history_status = label('', 'muted')
        self.history_status.setStyleSheet('font-size:11px;')
        self.history_status.hide()
        layout.addWidget(self.history_status)
        self._history_feedback = QTimer(self)
        self._history_feedback.setSingleShot(True)
        self._history_feedback.timeout.connect(self.history_status.hide)
        self.history_body = QVBoxLayout()
        self.history_body.setSpacing(9)
        layout.addLayout(self.history_body)
        layout.addStretch()

    def reset_history_filters(self, *args):
        self.history_limit = 60
        self.refresh()

    def filter_day(self, day):
        self.day_filter = day
        self.history_limit = 60
        self.navigate(1)

    @staticmethod
    def clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout():
                MainWindow.clear_layout(item.layout())

    def build_history(self):
        self.history_record_button = None
        self.clear_layout(self.history_body)
        if getattr(self.store,'cleanup_warning',''):
            self.history_feedback(self.store.cleanup_warning)
        mode = self.history_mode.currentData()
        rows = [r for r in self.store.rows(self.search.text()) if (not self.day_filter or r['time'][:10] == self.day_filter) and (mode == 'all' or r['mode'] == mode or mode == 'ask' and r['mode'] in ASK_MODES or mode == 'edits' and r['mode'] not in {'听写', '翻译', *ASK_MODES})]
        self.current_rows = rows
        self.filter_label.setText(f'{human_date(self.day_filter) if self.day_filter else "All dates"} · {len(rows)} session' + ('' if len(rows) == 1 else 's'))
        if self.day_filter:
            self.history_body.addWidget(button('Clear date filter', self.clear_day), alignment=Qt.AlignLeft)
        previous = ''
        for r in rows[:self.history_limit]:
            day = r['time'][:10]
            if day != previous:
                group_label = label(human_date(day), 'muted')
                group_label.setStyleSheet('font-size:11px;padding-top:4px;')
                self.history_body.addWidget(group_label)
                previous = day
            frame, body = card()
            body.setContentsMargins(13, 9, 10, 12)
            head = QHBoxLayout()
            meta = label(r['time'][11:16] + ' · ' + MODE_NAMES.get(r['mode'], r['mode']) + (' · Demo' if r['demo'] else ''), 'muted')
            meta.setStyleSheet('font-size:11px;')
            meta.setWordWrap(False)
            head.addWidget(meta, 1)
            copy_text = r['final'] or r['raw']
            copy = icon_button('copy', 'Copy text', lambda checked=False, text=copy_text: self.copy_history_text(text))
            copy.setEnabled(bool(copy_text.strip()))
            if not copy.isEnabled():copy.setToolTip('No transcript to copy')
            head.addWidget(copy)
            more = icon_button('more', 'Session options')
            menu = QMenu(more)
            menu.addAction('Open session', lambda row=r: self.show_record(row))
            menu.addAction('Delete session', lambda row=r: self.remove_record(row))
            more.setMenu(menu)
            more.setPopupMode(QToolButton.InstantPopup)
            head.addWidget(more)
            body.addLayout(head)
            text = r['final'] or r['raw'] or 'No transcript was captured.'
            excerpt = label(text[:420] + (' …' if len(text) > 420 else ''))
            excerpt.setTextInteractionFlags(Qt.TextSelectableByMouse)
            excerpt.setMinimumWidth(0)
            excerpt.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            body.addWidget(excerpt)
            comparison = bool(r['raw'].strip() and r['final'].strip() and r['raw'] != r['final'])
            if comparison or len(text) > 420:
                full = button('Compare original and result' if comparison else 'View full text', lambda checked=False, row=r: self.show_record(row))
                full.setObjectName('history_compare' if comparison else 'history_full_text')
                full.setStyleSheet('QPushButton{background:transparent;border:1px solid transparent;color:#b9aafa;padding:2px 0;min-height:16px;}QPushButton:hover{color:#eee6ff;}QPushButton:focus{border-color:#b9aafa;}')
                full.setToolTip('Open the saved original text and processed result.' if comparison else 'Open the full result and original transcript.')
                full.setAccessibleName(('Compare original and result for session at ' if comparison else 'View full text for session at ')+r['time'])
                body.addWidget(full, alignment=Qt.AlignLeft)
            if r['error']:
                error = label(r['error'], 'muted')
                error.setStyleSheet('font-size:11px;')
                body.addWidget(error)
            self.history_body.addWidget(frame)
        if not rows:
            frame, body = card()
            body.addWidget(label('No matching sessions.' if self.search.text() or self.day_filter or mode != 'all' else 'Your next idea starts here.'))
            body.addWidget(label('Try another search or clear your filters.' if self.search.text() or self.day_filter or mode != 'all' else 'Record with the capsule or the button below. Your transcripts will appear here.', 'muted'))
            if not self.search.text() and not self.day_filter and mode == 'all':
                record = button('Record to preview', self.record.emit, True)
                record.setToolTip('Recording here opens a preview. Use your configured shortcut in another app to insert text.')
                body.addWidget(record, alignment=Qt.AlignLeft)
                self.history_record_button = record
            self.history_body.addWidget(frame)
        if len(rows) > self.history_limit:
            self.history_body.addWidget(button(f'Load more · {len(rows) - self.history_limit} remaining', self.load_more_history), alignment=Qt.AlignCenter)
        self.set_session_state(self._session_phase, self._session_mode)

    def load_more_history(self):
        self.history_limit += 60
        self.build_history()

    def clear_day(self):
        self.day_filter = ''
        self.reset_history_filters()

    def show_record(self, row):
        dialog = QDialog(self)
        dialog.setWindowTitle('MurMur · Session')
        dialog.setFixedSize(610, 420)
        dialog.setWindowFlag(Qt.MSWindowsFixedSizeDialogHint, True)
        layout = QVBoxLayout(dialog)
        tabs = QTabWidget()
        entries=[('Final output', row['final']), ('Spoken request' if row['mode'] in ASK_MODES else 'Original transcript', row['raw'])]
        if row.get('context'):entries.append(('Selected source',row['context']))
        for title, text in entries:
            edit = QPlainTextEdit(text)
            edit.setReadOnly(True)
            tabs.addTab(edit, title)
        layout.addWidget(tabs)
        layout.addWidget(label(f'{row["time"]} · Recorded {duration_text(row["duration"])} · Processed in {row["latency"]:.2f}s', 'muted'))
        dark_titlebar(dialog)
        dialog.exec()

    def remove_record(self, row):
        try:
            self.store.delete([row['id']])
        except (sqlite3.Error, OSError):
            self.history_feedback('Could not delete this session. Try again shortly.')
            return
        self.refresh()
        self.history_feedback(getattr(self.store, 'cleanup_warning', ''))

    def history_feedback(self, message, transient=False):
        self._history_feedback.stop()
        self.history_status.setText(message)
        self.history_status.setVisible(bool(message))
        if message and transient:self._history_feedback.start(1600)

    def copy_history_text(self, text):
        if not text.strip():return
        try:
            QApplication.clipboard().setText(text)
        except (OSError, RuntimeError):
            self.history_feedback('Could not copy this text. Try again.')
            return
        self.history_feedback('Copied to clipboard', transient=True)

    def export_history(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Export filtered sessions', 'MurMur-history.json', 'JSON (*.json);;CSV (*.csv)')
        if not path:
            return
        import json, csv, os, tempfile
        from pathlib import Path
        destination = Path(path)
        temporary = None
        try:
            is_csv = path.lower().endswith('.csv')
            # Keep the previous export intact until the entire new file is
            # written and closed. The same directory permits atomic replace.
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8-sig' if is_csv else 'utf-8',
                                             newline='', dir=destination.parent,
                                             prefix=f'.{destination.name}.', suffix='.tmp', delete=False) as f:
                temporary = Path(f.name)
                if is_csv:
                    fields = list(self.current_rows[0]) if self.current_rows else ['time', 'mode', 'raw', 'final', 'context']
                    writer = csv.DictWriter(f, fieldnames=fields)
                    writer.writeheader()
                    writer.writerows(self.current_rows)
                else:
                    json.dump(self.current_rows, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, destination)
        except (OSError, ValueError, TypeError, csv.Error):
            QMessageBox.warning(self, 'Export failed',
                                'Could not save the export. Check the folder permissions and available space, then try again. Your previous export is unchanged.')
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def dictionary(self):
        layout = self.page('Dictionary', 'Give your everyday terms a place of their own.')
        row = QHBoxLayout()
        self.word_filter = CompactComboBox()
        for text, source in [('All terms', 'all'), ('Added manually', '手动'), ('From analysis', '分析')]:
            self.word_filter.addItem(text, source)
        self.word_filter.setFixedWidth(145)
        self.word_filter.currentIndexChanged.connect(self.refresh_words)
        row.addWidget(self.word_filter)
        self.word_search = QLineEdit()
        self.word_search.setPlaceholderText('Search terms')
        self.word_search.addAction(line_icon('search', 14), QLineEdit.LeadingPosition)
        self.word_search.setClearButtonEnabled(True)
        self.word_search.textChanged.connect(self.refresh_words)
        row.addWidget(self.word_search, 1)
        add = button('Add word', self.new_word, True)
        add.setIcon(line_icon('plus', 14, '#282035'))
        row.addWidget(add)
        layout.addLayout(row)
        self.words_grid = QGridLayout()
        self.words_grid.setSpacing(8)
        layout.addLayout(self.words_grid)
        actions = QHBoxLayout()
        self.analyze_button = button('Analyze vocabulary', self.run_analysis)
        actions.addWidget(self.analyze_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.analysis_status = label('Local rules find recurring terms in your history. Review suggestions before adding; demo sessions are excluded.', 'muted')
        self.analysis_status.setStyleSheet('font-size:11px;')
        layout.addWidget(self.analysis_status)
        self.vocabulary_notice = label('', 'muted')
        self.vocabulary_notice.setStyleSheet('font-size:11px;')
        layout.addWidget(self.vocabulary_notice)
        self.dictionary_status = label('', 'muted')
        self.dictionary_status.setStyleSheet('font-size:11px;')
        self.dictionary_status.hide()
        layout.addWidget(self.dictionary_status)
        self.suggestions_body = QVBoxLayout()
        self.suggestions_body.setSpacing(9)
        layout.addLayout(self.suggestions_body)
        layout.addStretch()

    def new_word(self):
        dialog = QInputDialog(self)
        dialog.setWindowTitle('Add word')
        dialog.setLabelText('A term or phrase you use often')
        dialog.setWindowFlag(Qt.WindowMaximizeButtonHint, False)
        dialog.setWindowFlag(Qt.MSWindowsFixedSizeDialogHint, True)
        dialog.ensurePolished()
        dialog.setFixedSize(360, 150)
        ok = dialog.exec() == QDialog.Accepted
        text = dialog.textValue()
        dialog.deleteLater()
        if ok and text.strip():
            try:
                self.store.add_word(text)
                self.refresh_words()
            except ValueError as e:
                QMessageBox.warning(self, 'Dictionary', str(e))
            except (sqlite3.Error, OSError):
                self.dictionary_feedback('Could not save this term. Try again shortly.')

    def refresh_words(self, *args):
        if not hasattr(self, 'words_grid'):
            return
        self.clear_layout(self.words_grid)
        query = self.word_search.text().casefold()
        source = self.word_filter.currentData()
        words = [w for w in self.store.words() if query in w['word'].casefold() and (source == 'all' or w['source'] == source)]
        context_size = len(self.store.config['hotwords'])
        self.vocabulary_notice.setText(f'All terms stay in your local dictionary. Supported FunASR models receive the first 400 context characters ({context_size:,} total).')
        for i, word in enumerate(words):
            item = QFrame()
            item.setObjectName('card')
            row = QHBoxLayout(item)
            row.setContentsMargins(11, 5, 5, 5)
            text = label(word['word'])
            text.setMinimumWidth(0)
            text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            text.setToolTip('From local analysis' if word['source'] == '分析' else 'Added manually')
            row.addWidget(text, 1)
            row.addWidget(icon_button('close', 'Remove word', lambda checked=False, value=word['word']: self.remove_word(value)))
            self.words_grid.addWidget(item, i // 3, i % 3)
        for col in range(3):
            self.words_grid.setColumnStretch(col, 1)
        if not words:
            self.words_grid.addWidget(label('No matching terms.' if query or source != 'all' else 'Add a term, or analyze your vocabulary to get started.', 'muted'), 0, 0, 1, 3)
        self.dictionary_feedback(getattr(self.store, 'dictionary_warning', ''))

    def remove_word(self, word):
        try:
            self.store.delete_word(word)
        except (sqlite3.Error, OSError):
            self.dictionary_feedback('Could not remove this term. Try again shortly.')
            return
        self.refresh_words()

    def dictionary_feedback(self, message):
        self.dictionary_status.setText(message)
        self.dictionary_status.setVisible(bool(message))

    def run_analysis(self):
        rows = [r for r in self.store.rows() if not r['demo'] and r['raw'] and r['mode'] in ('听写', '翻译')]
        existing = [w['word'] for w in self.store.words()]
        if not rows:
            self.analysis_status.setText('Record a few sessions to discover recurring terms. Demo samples are excluded.')
            return
        self.analyze_button.setEnabled(False)
        self.analysis_status.setText('Finding recurring terms on this device…')
        self.analysis_version += 1
        version = self.analysis_version

        def work():
            try:
                self.analysis_ready.emit((version, analyze_vocabulary(rows, existing)), f'Analyzed {len(rows)} voice sessions')
            except Exception:
                self.analysis_ready.emit((version, []), 'Analysis failed. Please try again.')
        threading.Thread(target=work, daemon=True).start()

    def show_analysis(self, payload, status):
        version, candidates = payload
        if version != self.analysis_version:
            return
        self.analyze_button.setEnabled(True)
        self.clear_layout(self.suggestions_body)
        unit = 'suggestion' if len(candidates) == 1 else 'suggestions'
        self.analysis_status.setText(status + f' · {len(candidates)} {unit} from local rules. Review before adding.')
        for candidate in candidates:
            frame, body = card()
            row = QHBoxLayout()
            row.addWidget(label(candidate['word']), 1)
            frequency = label(f'{candidate["count"]} mentions · {candidate["sessions"]} sessions', 'muted')
            frequency.setStyleSheet('font-size:11px;')
            row.addWidget(frequency)
            add = button('Add')
            add.clicked.connect(lambda checked=False, c=candidate, b=add: self.accept_word(c, b))
            row.addWidget(add)
            body.addLayout(row)
            example = label(candidate['example'], 'muted')
            example.setToolTip('Context from the original transcript')
            body.addWidget(example)
            self.suggestions_body.addWidget(frame)
        if not candidates:
            self.suggestions_body.addWidget(label('No recurring terms found yet. You can always add a word manually.', 'muted'))

    def accept_word(self, candidate, b):
        try:
            self.store.add_word(candidate['word'], '分析')
        except (sqlite3.Error, OSError, ValueError):
            self.dictionary_feedback('Could not save this term. Try again shortly.')
            return
        b.setText('Added')
        b.setEnabled(False)
        self.refresh_words()

    def settings(self):
        from .settings_page import build_settings
        self.stack.addWidget(build_settings(self))

    def service_test_values(self):
        values, secrets = self._settings_snapshot()
        config = deepcopy(self.store.config)
        config.update(values)
        return config, secrets

    def _settings_snapshot(self):
        values,secrets=super()._settings_snapshot()
        online=self._llm_source_profiles.get(False) or self._llm_profiles.get(False)
        if online and not is_local_endpoint(online[0]):values.update(online_llm_url=online[0],online_llm_model=online[1])
        return values,secrets

    def wire_service_test_changes(self):
        groups = {
            'asr': ('asr_backend', 'asr_model', 'asr_url', 'vocabulary_id', 'offline_engine', 'offline_model_dir', 'offline_language', 'offline_threads', 'offline_acceleration', 'ali_nls_url'),
            'llm': ('ollama', 'ollama_auto', 'llm_url', 'llm_model', 'llm_input_price_per_million', 'llm_output_price_per_million', 'llm_cache_price_per_million'),
            'ask': ('ask_llm_url', 'ask_llm_model'),
        }
        for kind, keys in groups.items():
            for key in keys:
                field = self.fields[key]
                signal = field.currentIndexChanged if isinstance(field, QComboBox) else field.valueChanged if isinstance(field, QSpinBox) else field.textChanged
                signal.connect(lambda *args, service=kind: self.invalidate_service_test(service))
        for kind, names in {'asr': ('asr_key', 'ali_appkey', 'ali_token'), 'llm': ('llm_key',), 'ask': ('ask_llm_key',)}.items():
            for name in names:
                getattr(self, name).textChanged.connect(lambda *args, service=kind: self.invalidate_service_test(service))

    def invalidate_service_test(self, kind):
        self.service_model_metadata.pop(kind, None)
        if self.service_test_busy[kind]:
            self.service_test_results.pop(kind, None)
            self.service_test_success.pop(kind, None)
            self.set_service_test_state(kind, True)
            return
        self.set_service_test_state(kind, False)
        dialog = self.service_test_dialogs.get(kind)
        if dialog:
            dialog.hide()

    def add_service_test_row(self, form, kind):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        test = button('Test connection', lambda: self.request_service_test(kind))
        test.setToolTip('Test these settings without saving changes. This may send a small request to the selected service.')
        status = label('Not checked', 'muted')
        status.setStyleSheet('font-size:11px;')
        status.setWordWrap(True)
        status.setMinimumWidth(0)
        status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        details = icon_button('info', 'View connection test details', lambda: self.show_service_test_details(kind))
        details.setEnabled(False)
        layout.addWidget(test)
        layout.addWidget(status, 1)
        layout.addWidget(details)
        self.service_test_controls[kind].append((test, status, details))
        form.addRow(row)

    def request_service_test(self, kind):
        if self.service_test_busy.get(kind):
            return
        if not self.validate_price_fields():
            return
        config, secrets = self.service_test_values()
        self.set_service_test_state(kind, True)
        self.service_test.emit(kind, config, secrets)

    def set_service_test_state(self, kind, busy, summary='', detail='', success=None):
        if kind not in self.service_test_controls:
            return
        self.service_test_busy[kind] = bool(busy)
        self.update_settings_actions()
        if busy and self.service_test_results.get(kind, ('Not checked', ''))[0] == 'Not checked':
            self.service_test_results.pop(kind, None)
            self.service_test_success.pop(kind, None)
        if not busy:
            summary = 'Speech model ready' if kind == 'asr' and success and summary == 'Model loaded' else summary or 'Not checked'
            self.service_test_results[kind] = (summary, detail)
            self.service_test_success[kind] = success
        summary, detail = self.service_test_results.get(kind, ('Checking…' if busy else 'Not checked', ''))
        outcome = self.service_test_success.get(kind)
        color = '#a4a4ae' if outcome is None else '#a9cbb8' if outcome else '#dfa6ae'
        for test, status, details in self.service_test_controls[kind]:
            test.setEnabled(not busy)
            local_asr = kind == 'asr' and self.fields['asr_backend'].currentData() == 'offline'
            test.setText(('Checking' if busy else 'Test') if test.property('overviewTest') else 'Checking…' if busy else 'Load && test' if local_asr else 'Test connection')
            status.setText(summary)
            status.setToolTip(summary + ('\n' + detail if detail else ''))
            status.setStyleSheet(f'font-size:11px;color:{color};')
            details.setEnabled(bool(detail))
        dialog = self.service_test_dialogs.get(kind)
        if dialog:
            self.update_service_test_dialog(kind)
        self.set_session_state(self._session_phase, self._session_mode)
        self.update_services_overview()

    def update_service_test_dialog(self, kind):
        dialog = self.service_test_dialogs[kind]
        summary, detail = self.service_test_results.get(kind, ('Checking…' if self.service_test_busy[kind] else 'Not checked', ''))
        dialog.test_summary.setText(summary)
        dialog.test_detail.setPlainText(detail)
        dialog.test_context.setText('Last completed test; a new check is running.' if self.service_test_busy[kind] and detail else 'Uses the values currently shown in Settings.')

    def show_service_test_details(self, kind):
        if kind not in self.service_test_dialogs:
            dialog = QDialog(self)
            dialog.setWindowTitle('MurMur · ' + ('Speech recognition' if kind == 'asr' else 'Ask Anything' if kind == 'ask' else 'Text processing') + ' test')
            dialog.setFixedSize(460, 240)
            dialog.setWindowFlag(Qt.MSWindowsFixedSizeDialogHint, True)
            dialog.setWindowIcon(icon())
            dialog.setModal(False)
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(18, 16, 18, 16)
            layout.setSpacing(10)
            dialog.test_summary = label('')
            layout.addWidget(dialog.test_summary)
            note = label('Uses the values currently shown in Settings.', 'muted')
            note.setStyleSheet('font-size:11px;')
            layout.addWidget(note)
            dialog.test_context = note
            dialog.test_detail = QPlainTextEdit()
            dialog.test_detail.setReadOnly(True)
            layout.addWidget(dialog.test_detail, 1)
            close = button('Close', dialog.close)
            close.setMaximumWidth(80)
            layout.addWidget(close, 0, Qt.AlignRight)
            self.service_test_dialogs[kind] = dialog
        dialog = self.service_test_dialogs[kind]
        self.update_service_test_dialog(kind)
        dialog.show()
        dark_titlebar(dialog)
        dialog.raise_()
        dialog.activateWindow()

    def update_shortcut_hint(self, *args):
        if not hasattr(self, 'key_status'):
            return
        disabled = self.fields['dictation_key'].currentData() == 'disabled'
        self.key_status.setText('Dictation shortcuts disabled · Use the capsule to record' if disabled else 'F8 is a backup key · Press a shortcut to test it')
        self.key_status.setToolTip('Disabled turns off the primary dictation key and F8. The capsule recording button remains available.')

    def update_offline_engine(self, *args):
        if 'offline_model_dir' not in self.fields or not hasattr(self, 'offline_status'):
            return
        from .models import MODELS, model_spec
        engine = self.fields['offline_engine'].currentData()
        acceleration_field = self.fields['offline_acceleration']
        # Keep only execution modes implemented by the selected model.
        gpu_supported = bool(MODELS[engine].get('gpu_supported', False) or MODELS[engine].get('gpu_variant'))
        gpu_item = acceleration_field.model().item(acceleration_field.findData('gpu'))
        gpu_item.setEnabled(gpu_supported)
        acceleration_field.setItemText(acceleration_field.findData('gpu'), 'GPU · DirectML' if engine == 'sensevoice' else 'GPU · DirectML / Vulkan')
        if not gpu_supported and acceleration_field.currentData() != 'cpu':
            blocked = acceleration_field.blockSignals(True)
            acceleration_field.setCurrentIndex(acceleration_field.findData('cpu'))
            acceleration_field.blockSignals(blocked)
        acceleration = acceleration_field.currentData()
        info = model_spec(engine, acceleration)
        selection = (engine, acceleration)
        path = self.fields['offline_model_dir']
        if self._offline_engine is None:
            self._offline_model_dirs[selection] = path.text()
        elif (self._offline_engine, self._offline_acceleration) != selection:
            # Keep an imported/custom folder for each model while editing.
            self._offline_model_dirs[(self._offline_engine, self._offline_acceleration)] = path.text()
            path.setText(self._offline_model_dirs.get(selection, str(default_offline_model_dir(engine=engine, acceleration=acceleration))))
        self._offline_engine = engine
        self._offline_acceleration = acceleration
        path.setPlaceholderText(str(default_offline_model_dir(engine=engine, acceleration=acceleration)))
        self.offline_download.setText('Download model')
        self.offline_download.setToolTip('Download and verify ' + info['name'] + ' in the selected folder.')
        language_hint = info.get('language_hint', 'Chinese, English, Cantonese, Japanese and Korean')
        language_hint = ('SenseVoice supports ' + language_hint + '.' if engine == 'sensevoice' else info['name'].split(' (')[0] + ' detects ' + language_hint + ' automatically. The saved language preference is ignored.')
        self.offline_language_hint.setText(language_hint)
        self.fields['offline_language'].setToolTip(language_hint)
        self.offline_acceleration_hint.setText('GPU uses DirectML for the encoder and Vulkan for the decoder. Test connection checks runtime availability.' if acceleration == 'gpu' and info.get('kind') == 'gguf' else 'GPU uses DirectML. Download the GPU model files, then test this configuration.' if acceleration == 'gpu' else 'This model runs on CPU.' if gpu_supported else 'This model supports CPU execution only.')
        self.update_asr_fields()
        self.update_offline_readiness()

    def update_offline_acceleration(self, *args):
        self.update_offline_engine()

    def set_offline_download_state(self, busy):
        self._offline_download_busy = bool(busy)
        self.update_asr_fields()

    def update_offline_readiness(self, *args):
        if not hasattr(self, 'offline_status') or self._offline_download_busy:
            return
        from pathlib import Path
        from .models import model_spec, download_size
        info = model_spec(self.fields['offline_engine'].currentData(), self.fields['offline_acceleration'].currentData())
        folder_text = self.fields['offline_model_dir'].text().strip()
        folder = Path(folder_text) if folder_text else None
        def present(name):
            return bool(folder and (folder / name).is_file() and (folder / name).stat().st_size)
        try:
            required = info.get('required_files', [('model.int8.onnx', 'model.onnx'), ('tokens.txt',)])
            complete = all(any(present(name) for name in alternatives) for alternatives in required)
            vad = present('silero_vad.onnx')
        except OSError:
            complete = False
            vad = False
        if complete:
            self.offline_status.setText(info['name'] + ' files found. ' + ('Test below to verify the model.' if vad else 'Add Silero VAD for recordings longer than 30 seconds, or download the complete model.'))
        else:
            size_bytes = download_size(self.fields['offline_engine'].currentData(), self.fields['offline_acceleration'].currentData())
            size = f'{size_bytes / 1_000_000_000:.2f} GB' if size_bytes >= 1_000_000_000 else f'{round(size_bytes / 1_000_000)} MB'
            self.offline_status.setText(f"{info['name']} files are missing. One-time download: about {size}.")
        self.offline_status.setToolTip('File presence only. Use Test connection to verify and load the selected model.')
        self.update_services_overview()

    def browse_offline_model(self):
        from .models import model_spec
        info = model_spec(self.fields['offline_engine'].currentData(), self.fields['offline_acceleration'].currentData())
        current = self.fields['offline_model_dir'].text() or str(default_offline_model_dir(engine=self.fields['offline_engine'].currentData(), acceleration=self.fields['offline_acceleration'].currentData()))
        path = QFileDialog.getExistingDirectory(self, 'Choose ' + info['name'] + ' model folder', current)
        if path:
            self.fields['offline_model_dir'].setText(path)

    def update_asr_fields(self, *args):
        if not hasattr(self, 'asr_key') or not hasattr(self, 'offline_browse') or not hasattr(self, 'ali_nls_panel'):
            return
        provider = self.fields['asr_backend'].currentData()
        offline = provider == 'offline'
        online_bailian = provider == 'bailian'
        ali_nls = provider == 'ali_nls'
        self.online_asr_panel.setVisible(online_bailian)
        self.offline_asr_panel.setVisible(offline)
        self.ali_nls_panel.setVisible(ali_nls)
        for key in ('asr_model', 'asr_url', 'vocabulary_id'):
            self.fields[key].setEnabled(online_bailian)
        self.asr_key.setEnabled(online_bailian)
        self.fields['ali_nls_url'].setEnabled(ali_nls)
        self.ali_appkey.setEnabled(ali_nls)
        self.ali_token.setEnabled(ali_nls)
        for key in ('offline_engine', 'offline_model_dir', 'offline_acceleration'):
            self.fields[key].setEnabled(offline and not self._offline_download_busy)
        self.fields['offline_threads'].setEnabled(offline and not self._offline_download_busy)
        self.fields['offline_language'].setEnabled(offline and not self._offline_download_busy and self.fields['offline_engine'].currentData() == 'sensevoice')
        self.offline_browse.setEnabled(offline and not self._offline_download_busy)
        self.offline_download.setEnabled(offline and not self._offline_download_busy)
        self.update_credential_status()
        for test, _, _ in self.service_test_controls['asr']:
            test.setToolTip('Verify files and load the local speech model. No audio is recorded or sent online.' if offline else 'Check the selected online speech service without recording audio.')
            if not self.service_test_busy['asr']:
                test.setText('Test' if test.property('overviewTest') else 'Load && test' if offline else 'Test connection')
        self.update_services_overview()

    def update_llm_fields(self, *args):
        if not hasattr(self, 'llm_key') or 'llm_url' not in self.fields:
            return
        local = bool(self.fields['ollama'].currentData())
        current = (self.fields['llm_url'].text(), self.fields['llm_model'].text(),bool(self.fields['ollama_auto'].currentData()))
        if self._llm_provider is None:
            self._llm_profiles = {False: ('http://127.0.0.1:11434/v1','qwen3.5:2b',True), True: ('http://127.0.0.1:11434/v1', 'qwen3.5:2b',True)}
            self._llm_profiles[local] = current
            self._llm_provider = local
        elif local != self._llm_provider:
            self._llm_profiles[self._llm_provider] = current
            self._llm_provider = local
            self._llm_profile_syncing = True
            try:
                url, model, auto = self._llm_profiles[local]
                self.fields['llm_url'].setText(url)
                self.fields['llm_model'].setText(model)
                self.fields['ollama_auto'].setCurrentIndex(self.fields['ollama_auto'].findData(auto))
            finally:
                self._llm_profile_syncing = False
        self.llm_key.setEnabled(not local)
        self.update_llm_selection()
        self.update_llm_profile()
        self.update_credential_status()

    def update_llm_selection(self,*args):
        if not hasattr(self,'llm_key'):return
        local=bool(self.fields['ollama'].currentData()) or is_local_endpoint(self.fields['llm_url'].text())
        auto=bool(self.fields['ollama_auto'].currentData())
        self.llm_form.setRowVisible(self.fields['ollama_auto'],local)
        self.llm_form.setRowVisible(self.fields['llm_model'],not local or not auto)
        self.llm_form.setRowVisible(self.llm_key,not local)
        self.llm_key.setEnabled(not local)
        self.update_llm_profile()
        self.update_credential_status()
        self.update_services_overview()
        self.sync_llm_source()

    def sync_llm_source(self):
        if not hasattr(self, 'llm_source') or self._llm_source_syncing or self._llm_profile_syncing:
            return
        local = is_local_endpoint(self.fields['llm_url'].text())
        if not self._llm_source_profiles:
            self._llm_source_profiles = {
                True: ('http://127.0.0.1:11434/v1', 'qwen3.5:2b', True, True),
                False: (self.store.config.get('online_llm_url', 'https://api.deepseek.com/v1'),
                        self.store.config.get('online_llm_model', 'deepseek-chat'), False, False),
            }
        self._llm_source_profiles[local] = (self.fields['llm_url'].text(), self.fields['llm_model'].text(),
                                         bool(self.fields['ollama_auto'].currentData()), bool(self.fields['ollama'].currentData()))
        previous = self.llm_source.blockSignals(True)
        try:self.llm_source.setCurrentIndex(self.llm_source.findData(local))
        finally:self.llm_source.blockSignals(previous)

    def change_llm_source(self, *args):
        local = bool(self.llm_source.currentData())
        if local not in self._llm_source_profiles:
            return
        url, model, auto, protocol = self._llm_source_profiles[local]
        self._llm_source_syncing = True
        try:
            self.fields['ollama'].setCurrentIndex(self.fields['ollama'].findData(protocol))
            self.fields['llm_url'].setText(url)
            self.fields['llm_model'].setText(model)
            self.fields['ollama_auto'].setCurrentIndex(self.fields['ollama_auto'].findData(auto))
        finally:self._llm_source_syncing = False
        self.update_llm_selection()


    def set_service_model_metadata(self, kind, result):
        self.service_model_metadata.pop(kind, None)
        if result.get('success') and isinstance(result.get('model'), str):
            self.service_model_metadata[kind] = {key: result.get(key) for key in
                ('model', 'model_selection', 'response_model', 'parameter_size', 'parameter_size_source')}
        self.update_services_overview()

    def update_services_overview(self):
        if not hasattr(self, 'service_overview_models') or not all(key in self.fields for key in
                ('asr_backend', 'offline_engine', 'offline_acceleration', 'asr_model', 'llm_model', 'llm_url', 'ollama', 'ollama_auto')):
            return
        from .models import model_spec
        provider = self.fields['asr_backend'].currentData()
        if provider == 'offline':
            speech = model_spec(self.fields['offline_engine'].currentData(), self.fields['offline_acceleration'].currentData())['name']
            speech += ' · ' + self.fields['offline_acceleration'].currentData().upper() + ' · local'
        elif provider == 'bailian':
            speech = (self.fields['asr_model'].text().strip() or 'Model not specified') + ' · Bailian · online'
        else:
            speech = 'Alibaba Speech · online'
        self.service_overview_models['asr'].setText(speech)
        self.service_overview_models['asr'].setToolTip(speech + ('\n' + self.offline_status.text() if provider == 'offline' else ''))
        local = is_local_endpoint(self.fields['llm_url'].text())
        automatic = (local or bool(self.fields['ollama'].currentData())) and bool(self.fields['ollama_auto'].currentData())
        metadata = self.service_model_metadata.get('llm', {})
        name = metadata.get('model') if automatic else self.fields['llm_model'].text().strip()
        text_model = ('Auto → ' + name if name else 'Auto · test to identify model') if automatic else name or 'Model not specified'
        if metadata.get('response_model') and metadata['response_model'] != name:
            text_model += ' → ' + metadata['response_model']
        text_model += ' · ' + ('local' if local else 'online')
        if metadata.get('parameter_size') and metadata['parameter_size'].lower() not in text_model.lower():
            text_model += ' · ' + metadata['parameter_size'] + ' model tag'
        self.service_overview_models['llm'].setText(text_model)
        self.service_overview_models['llm'].setToolTip(text_model + '\n' + ('Model used by the last successful check.' if metadata else 'The model currently configured in Settings. Auto resolves an installed local model when tested or used.'))
        ask_metadata = self.service_model_metadata.get('ask', {})
        ask_model = self.fields['ask_llm_model'].text().strip() or 'Model not specified'
        if ask_metadata.get('response_model') and ask_metadata['response_model'] != ask_model:
            ask_model += ' → ' + ask_metadata['response_model']
        ask_model += ' · ' + ('local' if is_local_endpoint(self.fields['ask_llm_url'].text()) else 'online')
        self.service_overview_models['ask'].setText(ask_model)
        self.service_overview_models['ask'].setToolTip(ask_model + '\nIndependent model for Ask Anything.')
        for kind in ('asr', 'llm', 'ask'):
            summary, detail = self.service_test_results.get(kind, ('Not checked', ''))
            status = self.service_overview_status[kind]
            status.setText('No completed test yet' if self.service_test_busy[kind] and kind not in self.service_test_results
                           else 'Last test: ' + summary if self.service_test_busy[kind] else summary)
            status.setToolTip(summary + ('\n' + detail if detail else ''))
            outcome = self.service_test_success.get(kind)
            color = '#a4a4ae' if outcome is None else '#a9cbb8' if outcome else '#dfa6ae'
            status.setStyleSheet(f'font-size:11px;color:{color};')
            progress = self.service_overview_progress[kind]
            progress.setText('Checking…')
            progress.setVisible(self.service_test_busy[kind])
        if hasattr(self, '_service_settings'):
            self._service_settings.refresh()

    def update_llm_profile(self, *args):
        if self._llm_profile_syncing or self._llm_provider is None:
            return
        local = bool(self.fields['ollama'].currentData())
        url, model = self.fields['llm_url'].text().strip(), self.fields['llm_model'].text().strip()
        auto=bool(self.fields['ollama_auto'].currentData())
        self._llm_profiles[local] = (url, model,auto)
        preset = 'custom'
        if not local and url.rstrip('/') == 'https://api.deepseek.com/v1' and model == 'deepseek-flash':
            preset = 'deepseek'
        elif not local and auto and url.rstrip('/') == 'http://127.0.0.1:11434/v1':
            preset='local_auto'
        elif local and auto and url.rstrip('/') == 'http://127.0.0.1:11434/v1':
            preset='auto'
        elif local and not auto and url.rstrip('/') == 'http://127.0.0.1:11434/v1' and model in ('qwen3.5:2b', 'qwen3.5:4b', 'qwen3.5:9b'):
            preset = model.split(':')[-1]
        previous = self.llm_preset.blockSignals(True)
        try:
            self.llm_preset.setCurrentIndex(self.llm_preset.findData(preset))
        finally:
            self.llm_preset.blockSignals(previous)
        self.sync_llm_source()

    def update_credential_status(self):
        """Presence only: never populate fields or claim an online validation."""
        if not hasattr(self, 'llm_hint'):
            return
        from .storage import credential
        saved = {}
        for name in ('asr', 'llm', 'ask_llm', 'ali_appkey', 'ali_token', 'ali_access_key_id', 'ali_access_key_secret'):
            try:
                saved[name] = bool(credential(name))
            except Exception:
                saved[name] = None

        def status(title, value):
            return title + (' saved' if value else ' not saved') if value is not None else title + ' status unavailable'

        def key_guidance(value):
            return 'Leave blank to keep it.' if value else 'Enter a key, then save.' if value is not None else 'Blank fields do not replace saved credentials.'

        self.asr_hint.setText(status('Key', saved['asr']) + ' · ' + key_guidance(saved['asr']))
        access_keys = None if any(saved[name] is None for name in ('ali_access_key_id', 'ali_access_key_secret')) else saved['ali_access_key_id'] and saved['ali_access_key_secret']
        self.ali_hint.setText(' · '.join([status('AppKey', saved['ali_appkey']), status('AccessKeys', access_keys), status('Token', saved['ali_token'])]) + '\nSaved AccessKeys refresh tokens automatically; manual tokens also work.')
        local = bool(self.fields['ollama'].currentData()) or is_local_endpoint(self.fields['llm_url'].text())
        on_device = is_local_endpoint(self.fields['llm_url'].text())
        self.llm_hint.setText(('Local API · uses the endpoint in Advanced.' if on_device else
                              'Remote Ollama · sends text to the endpoint in Advanced.') if local else
                             status('Key', saved['llm']) + ' · ' + key_guidance(saved['llm']))
        self.ask_llm_hint.setText(status('Ask key',saved['ask_llm'])+' · '+key_guidance(saved['ask_llm']))
        for hint in (self.asr_hint, self.ali_hint, self.llm_hint, self.ask_llm_hint):
            hint.setToolTip('Saved means present in local Windows credentials. Service access has not been checked.')
        if not on_device:
            self.llm_hint.setToolTip(self.llm_hint.toolTip() + ' This provider receives your text.')
        self.ask_llm_hint.setToolTip(self.ask_llm_hint.toolTip()+' Ask sends your spoken request and selected source to this provider.')

    def apply_llm_preset(self, *args):
        value = self.llm_preset.currentData()
        if value == 'custom' or 'llm_url' not in self.fields:
            return
        local = value not in ('deepseek','local_auto')
        syncing = self._llm_source_syncing
        self._llm_source_syncing = True
        try:
            self.fields['ollama'].setCurrentIndex(self.fields['ollama'].findData(local))
            self.fields['ollama_auto'].setCurrentIndex(self.fields['ollama_auto'].findData(value in ('auto','local_auto')))
            self.fields['llm_url'].setText('https://api.deepseek.com/v1' if value=='deepseek' else 'http://127.0.0.1:11434/v1')
            if value not in ('auto','local_auto'):self.fields['llm_model'].setText(f'qwen3.5:{value}' if local else 'deepseek-flash')
        finally:
            self._llm_source_syncing = syncing
        self.update_llm_selection()
        self.settings_status.setText('Preset filled in. Save changes to apply it.')

    def refresh(self, *args):
        if not hasattr(self, 'settings_tabs'):
            return
        self.update_credential_status()
        self.refresh_token_insights()
        self.refresh_shortcuts()
        demo = self.store.config['demo']
        self.badge.setText('Demo mode' if demo else 'Offline ASR' if self.store.config.get('asr_backend') == 'offline' else 'Online ASR')
        if not demo and self.store.config.get('asr_backend') == 'offline':
            from .models import model_spec
            self.badge.setToolTip(model_spec(self.store.config.get('offline_engine', 'sensevoice'), self.store.config.get('offline_acceleration', 'cpu'))['name'] + ' · Recognition stays on this device.')
        else:
            self.badge.setToolTip('Demo uses sample text.' if demo else 'Speech recognition uses your selected online provider.')
        selected = [r for r in self.store.rows() if bool(r['demo']) == bool(self.stats_source.currentData())]
        data = insights(selected)
        values = [f'{data["characters"]:,}', duration_text(data['duration']), f'{data["speed"]:.0f} / min', f'{data["uses"]:,}']
        for w, value in zip(self.metric_values, values):
            w.setText(value)
        active_unit = 'day' if data['active'] == 1 else 'days'
        best_unit = 'day' if data['longest'] == 1 else 'days'
        self.activity_metrics.setText(f'{data["active"]} active {active_unit} · {data["streak"]} day streak · Best {data["longest"]} {best_unit}')
        for widget, key in zip(self.activity_values, ('active', 'streak', 'longest')):
            widget.setText(str(data[key]))
        self.calendar.set_data(data['daily'])
        self.set_session_state(self._session_phase, self._session_mode)
        if self.stack.currentIndex() == 1:
            self.build_history()
        if self.stack.currentIndex() == 2:
            self.refresh_words()

"""Compact service model choices and separate detail pages; no I/O here."""
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget
from .ui import CompactComboBox, button, label, line_icon
from .provider_icons import provider_icon


class ModelLabel(QLabel):
    """Keep full model identity for accessibility; elide only its painting."""
    def __init__(self):
        super().__init__()
        self.setMinimumWidth(0)
        self.setTextFormat(Qt.PlainText)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setStyleSheet('font-size:11px;color:#c7b8fa;')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().windowText().color())
        painter.setFont(self.font())
        painter.drawText(self.rect(), Qt.AlignLeft | Qt.AlignVCenter,
                         self.fontMetrics().elidedText(self.text(), Qt.ElideRight, self.width()))


class ServiceSettings:
    MODULES = (
        ('asr', '1 · Speech to Text', 'Turn your voice into text.'),
        ('llm', '2 · Polish', 'Clear writing in your original language.'),
        ('ask', '3 · Ask Anything', 'Questions, edits and drafts with a separate model.'),
    )

    def __init__(self, window):
        self.window = window
        self.syncing = False
        window.services_stack = QStackedWidget()
        window.services_stack.setMinimumWidth(0)
        window.services_overview = QWidget()
        landing = QVBoxLayout(window.services_overview)
        landing.setContentsMargins(0, 4, 0, 0)
        landing.setSpacing(12)
        explanation = label('Choose a model for each step. Advanced settings are saved with the rest of Settings.', 'muted')
        explanation.setStyleSheet('font-size:11px;')
        landing.addWidget(explanation)
        window.service_overview_models = {}
        window.service_overview_status = {}
        window.service_overview_progress = {}
        window.services_model_choices = {}
        window.services_advanced_buttons = {}
        window.services_cards = {}
        window.services_provider_marks = {}
        for kind, title, description in self.MODULES:
            card = QFrame()
            card.setObjectName('serviceModule')
            card.setStyleSheet('QFrame#serviceModule{background:#252429;border:1px solid #38343f;border-radius:11px;}')
            card.setMinimumWidth(0)
            body = QVBoxLayout(card)
            body.setContentsMargins(14, 12, 14, 12)
            body.setSpacing(7)
            top = QHBoxLayout()
            top.setSpacing(8)
            mark = QLabel()
            mark.setFixedSize(20, 20)
            top.addWidget(mark)
            heading = label(title)
            heading.setStyleSheet('font-size:13px;font-weight:600;')
            top.addWidget(heading, 1)
            choices = CompactComboBox()
            choices.setFixedWidth(240)
            choices.setAccessibleName(title + ' model')
            choices.setToolTip('Choose the configured model. Save changes to apply.')
            choices.currentIndexChanged.connect(lambda index, service=kind: self.choose(service))
            top.addWidget(choices)
            body.addLayout(top)
            role = label(description, 'muted')
            role.setStyleSheet('font-size:11px;')
            body.addWidget(role)
            model = ModelLabel()
            body.addWidget(model)
            bottom = QHBoxLayout()
            bottom.setSpacing(7)
            status = ModelLabel()
            status.setText('Test: Not checked')
            bottom.addWidget(status, 1)
            progress = label('', 'muted')
            progress.setStyleSheet('font-size:11px;')
            progress.hide()
            bottom.addWidget(progress)
            test = button('Test', lambda checked=False, service=kind: window.request_service_test(service))
            test.setProperty('overviewTest', True)
            test.setFixedWidth(76)
            details = button('', lambda checked=False, service=kind: window.show_service_test_details(service))
            details.setIcon(line_icon('info', 14))
            details.setFixedWidth(28)
            details.setToolTip('View test details')
            details.setAccessibleName('View ' + title + ' test details')
            details.setEnabled(False)
            advanced = button('Advanced', lambda checked=False, service=kind: self.show_details(service))
            advanced.setToolTip('Open ' + title.split(' · ')[1] + ' settings')
            bottom.addWidget(test)
            bottom.addWidget(details)
            bottom.addWidget(advanced)
            body.addLayout(bottom)
            window.service_test_controls[kind].append((test, status, details))
            window.service_overview_models[kind] = model
            window.service_overview_status[kind] = status
            window.service_overview_progress[kind] = progress
            window.services_model_choices[kind] = choices
            window.services_advanced_buttons[kind] = advanced
            window.services_cards[kind] = card
            window.services_provider_marks[kind] = mark
            landing.addWidget(card)
        landing.addStretch()
        window.services_stack.addWidget(window.services_overview)
        window.services_home = window.services_overview
        window.service_model_selectors = window.services_model_choices
        window.service_advanced_buttons = window.services_advanced_buttons
        window.services_subpages = {}
        window.service_detail_pages = {}
        window.services_detail_layouts = {}
        window.services_back_buttons = {}
        for kind, title, description in self.MODULES:
            page = QWidget()
            column = QVBoxLayout(page)
            column.setContentsMargins(0, 2, 0, 0)
            column.setSpacing(14)
            back = button('‹ Services', self.show_overview, navigation=True)
            back.setToolTip('Back to all three services')
            column.addWidget(back, 0, Qt.AlignLeft)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            content = QWidget()
            content.setObjectName('page')
            contents = QVBoxLayout(content)
            contents.setContentsMargins(0, 4, 10, 16)
            contents.setSpacing(20)
            scroll.setWidget(content)
            column.addWidget(scroll, 1)
            window.services_subpages[kind] = scroll
            window.service_detail_pages[kind] = page
            window.services_detail_layouts[kind] = contents
            window.services_back_buttons[kind] = back
            window.services_stack.addWidget(page)
        window.show_service_settings = self.show_details
        window.show_services_overview = self.show_overview
        window.service_back_buttons = window.services_back_buttons
        window.show_service_page = lambda kind: self.show_overview() if kind == 'home' else self.show_details(kind)
        window.sync_service_selectors = self.refresh

    def show_details(self, kind):
        index = [module[0] for module in self.MODULES].index(kind) + 1
        self.window.settings_tabs.setCurrentIndex(1)
        self.window.services_stack.setCurrentIndex(index)

    def show_overview(self):
        self.window.services_stack.setCurrentIndex(0)

    def populate(self, kind, items, current):
        combo = self.window.services_model_choices[kind]
        with QSignalBlocker(combo):
            combo.clear()
            for title, value, model in items:
                combo.addItem(provider_icon(model, 20), title, value)
            combo.setCurrentIndex(max(0, combo.findData(current)))
        combo.setToolTip(combo.currentText() + ' · Save changes to apply.')
        self.window.services_provider_marks[kind].setPixmap(provider_icon(items[max(0, combo.currentIndex())][2], 20).pixmap(20, 20))

    def refresh(self):
        w = self.window
        if self.syncing or not all(key in w.fields for key in ('asr_backend', 'offline_engine', 'llm_model', 'llm_url', 'ask_llm_model')):
            return
        from .models import model_spec
        from .usage import is_local_endpoint
        self.syncing = True
        try:
            provider = w.fields['asr_backend'].currentData()
            engine = w.fields['offline_engine'].currentData()
            speech = [(model_spec(key, w.fields['offline_acceleration'].currentData() if key == engine else 'cpu')['name'], key, key) for key in ('sensevoice', 'paraformer', 'fun_asr_nano', 'qwen_asr')]
            speech += [('Bailian · ' + (w.fields['asr_model'].text().strip() or 'Unspecified'), 'bailian', 'bailian'), ('Alibaba Speech · realtime', 'ali_nls', 'ali_nls')]
            self.populate('asr', speech, engine if provider == 'offline' else provider)
            if provider == 'offline':
                w.services_model_choices['asr'].setToolTip(w.services_model_choices['asr'].currentText() + '\n' + w.offline_status.text() + '\nOpen Advanced for model files and downloads.')
            local = is_local_endpoint(w.fields['llm_url'].text())
            auto = bool(w.fields['ollama_auto'].currentData()) and (local or bool(w.fields['ollama'].currentData()))
            model = w.fields['llm_model'].text().strip()
            online = w._llm_source_profiles.get(False) or (w.store.config['online_llm_url'], w.store.config['online_llm_model'])
            resolved = w.service_model_metadata.get('llm', {}).get('model')
            text_choices = [('Local · Auto', 'local_auto', resolved or 'auto-local'), ('Qwen3.5 · 2B', '2b', 'qwen'), ('Qwen3.5 · 4B', '4b', 'qwen'), ('Qwen3.5 · 9B', '9b', 'qwen'), ('Online · ' + online[1], 'online', online[1]), ('DeepSeek · Flash', 'deepseek', 'deepseek')]
            current = 'local_auto' if local and auto else model.split(':')[-1] if local and model in ('qwen3.5:2b', 'qwen3.5:4b', 'qwen3.5:9b') else 'local_custom' if local else 'online'
            if local and not auto and current not in [item[1] for item in text_choices]:
                text_choices.insert(4, ('Local · ' + (model or 'Unspecified'), current, model))
            if not local:
                text_choices[4] = ('Online · ' + ('Auto' if auto else model or 'Unspecified'), 'online', model)
                if 'deepseek.com' in w.fields['llm_url'].text().lower():
                    text_choices += [('DeepSeek · V4 Pro', 'deepseek_pro', 'deepseek')]
            self.populate('llm', text_choices, current)
            ask_model = w.fields['ask_llm_model'].text().strip()
            ask_items = [(ask_model or 'Model not specified', 'custom', ask_model), ('DeepSeek · Flash', 'deepseek', 'deepseek')]
            ask_url = w.fields['ask_llm_url'].text().lower()
            if 'dashscope.aliyuncs.com' in ask_url:
                ask_items += [('Qwen · Plus', 'qwen-plus', 'qwen'), ('Qwen · Turbo', 'qwen-turbo', 'qwen')]
            elif 'deepseek.com' in ask_url:
                ask_items += [('DeepSeek · V4 Pro', 'deepseek_pro', 'deepseek')]
            self.populate('ask', ask_items, 'custom')
            for kind, combo in w.services_model_choices.items():
                combo.setEnabled(w._session_phase == 'idle' and not w.service_test_busy[kind] and not (kind == 'asr' and w._offline_download_busy))
        finally:
            self.syncing = False

    def choose(self, kind):
        if self.syncing:
            return
        w = self.window
        value = w.services_model_choices[kind].currentData()
        if value is None:
            return
        if kind == 'asr':
            if value in ('sensevoice', 'paraformer', 'fun_asr_nano', 'qwen_asr'):
                w.fields['asr_backend'].setCurrentIndex(w.fields['asr_backend'].findData('offline'))
                w.fields['offline_engine'].setCurrentIndex(w.fields['offline_engine'].findData(value))
            else:
                w.fields['asr_backend'].setCurrentIndex(w.fields['asr_backend'].findData(value))
        elif kind == 'llm':
            if value == 'deepseek':
                w.llm_preset.setCurrentIndex(w.llm_preset.findData('deepseek'))
            elif value == 'deepseek_pro':
                w.llm_source.setCurrentIndex(w.llm_source.findData(False))
                w.fields['llm_url'].setText('https://api.deepseek.com/v1')
                w.fields['ollama_auto'].setCurrentIndex(w.fields['ollama_auto'].findData(False))
                w.fields['llm_model'].setText('deepseek-v4-pro')
            else:
                w.llm_source.setCurrentIndex(w.llm_source.findData(value != 'online'))
                if value in ('local_auto', '2b', '4b', '9b'):
                    w.fields['ollama_auto'].setCurrentIndex(w.fields['ollama_auto'].findData(value == 'local_auto'))
                    if value != 'local_auto':
                        w.fields['llm_model'].setText('qwen3.5:' + value)
        elif kind == 'ask':
            if value in ('deepseek', 'deepseek_pro'):
                w.fields['ask_llm_url'].setText('https://api.deepseek.com/v1')
                w.fields['ask_llm_model'].setText('deepseek-flash' if value == 'deepseek' else 'deepseek-v4-pro')
            elif value != 'custom':
                w.fields['ask_llm_model'].setText(value)
        self.refresh()

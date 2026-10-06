"""Flat, category-based Settings UI; controller and persistence stay in MainWindow."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QScrollArea, QSizePolicy, QTabWidget, QVBoxLayout, QWidget,
)
from .ui import AdvancedSection, CompactComboBox, button, label, line_icon
from .service_settings import ServiceSettings, ServiceStatusLabel, AUTO_POLICY_DESCRIPTION, AUTO_POLICY_HELP


def preview_bubble(window):
    if getattr(window,'_session_phase','idle')!='idle':return
    from .appearance_preview import AppearancePreview
    previous=getattr(window,'_appearance_preview',None)
    if previous:previous.replace()
    cfg=dict(window.store.config)
    for key,widget in window.fields.items():
        if not key.startswith('bubble_'):continue
        cfg[key]=(widget.isChecked() if isinstance(widget,QCheckBox) else widget.currentData()
                  if hasattr(widget,'currentData') else widget.value())
    window._appearance_preview=AppearancePreview(window,cfg)


class SettingsRows(QVBoxLayout):
    """Form-compatible rows with descriptions and responsive trailing controls.

    MainWindow's existing LLM visibility rules use setRowVisible(field, bool).
    The fields themselves keep their existing types and data identifiers.
    """
    def __init__(self, parent):
        super().__init__(parent)
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(0)
        self.rows = {}
        self.pending_title = ''
        self.pending_description = ''

    def addRow(self, *items):
        if len(items) == 1 and not self.pending_title:
            widget = items[0]
            # Connection feedback and disclosures span the content width.
            self.addWidget(widget)
            self.addSpacing(10)
            return
        title = items[0] if len(items) == 2 else self.pending_title
        control = items[-1]
        title = title.text() if isinstance(title, QLabel) else str(title)
        row = QWidget()
        row.setObjectName('settingsRow')
        body = QHBoxLayout(row)
        body.setContentsMargins(0, 8, 0, 8)
        body.setSpacing(12)
        text = QWidget()
        text_layout = QVBoxLayout(text)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)
        heading = label(title)
        heading.setBuddy(control)
        control.setAccessibleName(title)
        if self.pending_description:
            control.setAccessibleDescription(self.pending_description)
        text_layout.addWidget(heading)
        if self.pending_description:
            description = label(self.pending_description, 'muted')
            description.setStyleSheet('font-size:12px;')
            text_layout.addWidget(description)
        text.setMinimumWidth(0)
        body.addWidget(text, 1, Qt.AlignVCenter)
        if isinstance(control, QCheckBox):
            control.setText('')
            control.setFixedWidth(38)
            body.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)
        else:
            control.setMinimumWidth(0)
            control.setMaximumWidth(260)
            control.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            body.addWidget(control, 1)
        self.addWidget(row)
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet('background:#303035;border:0;')
        self.addWidget(divider)
        self.rows[control] = (row, divider)
        self.pending_title = self.pending_description = ''

    def setRowVisible(self, field, visible):
        for widget in self.rows[field]:
            widget.setVisible(visible)

    def isRowVisible(self, field):
        return not self.rows[field][0].isHidden()


def build_settings(window):
    """Return the Settings stack page, exposing the legacy window UI attributes.

    Caller adds this widget to its stack. Category changes need no controller
    work; close returns to the previously selected page. Nothing is saved here.
    """
    page = QWidget()
    page.setObjectName('page')
    page.setAccessibleName('Settings')
    outer = QHBoxLayout(page)
    outer.setContentsMargins(8, 12, 24, 12)
    outer.setSpacing(12)
    categories = QFrame()
    categories.setObjectName('settingsCategories')
    categories.setStyleSheet('QFrame#settingsCategories {background:#242427;border-radius:14px;}')
    categories.setFixedWidth(160)
    navigation = QVBoxLayout(categories)
    navigation.setContentsMargins(10, 8, 10, 16)
    navigation.setSpacing(5)
    content_column = QWidget()
    content_column.setMinimumWidth(0)
    layout = QVBoxLayout(content_column)
    layout.setContentsMargins(0, 8, 0, 0)
    layout.setSpacing(12)
    header = QHBoxLayout()
    window.settings_title = label('Settings', 'title')
    header.addWidget(window.settings_title)
    header.addStretch()
    close = button('', lambda: window.navigate(getattr(window, '_settings_return_page', 0)), navigation=True)
    close.setObjectName('settingsClose')
    close.setIcon(line_icon('arrow_left'))
    close.setFixedSize(30, 30)
    close.setToolTip('Back to app')
    close.setAccessibleName('Close Settings and return to app')
    close.setStyleSheet('QPushButton {background:transparent;border:1px solid transparent;padding:0;} QPushButton:hover {background:#303035;} QPushButton[keyboardFocus="true"]:focus {border-color:#8c7eb7;}')
    header.addWidget(close)
    from .window_chrome import window_controls
    header.addWidget(window_controls(window))
    layout.addLayout(header)
    window.settings_tabs = QTabWidget()
    window.settings_tabs.tabBar().hide()
    window.settings_tabs.setMinimumWidth(0)
    window.settings_category_buttons = []
    window.settings_nav_buttons = window.settings_category_buttons
    window.settings_close_button = close
    sections = {}
    for index, (title, icon) in enumerate((('General', 'settings'), ('Services', 'waveform'), ('Shortcuts', 'record'), ('Appearance', 'home'), ('Writing', 'edit'))):
        nav = button(title, lambda checked=False, i=index: window.settings_tabs.setCurrentIndex(i), navigation=True)
        nav.setObjectName('nav')
        nav.setIcon(line_icon(icon))
        nav.setCheckable(True)
        nav.setAutoExclusive(True)
        navigation.addWidget(nav)
        window.settings_category_buttons.append(nav)
        if title == 'Services':
            window._service_settings = ServiceSettings(window)
            window.settings_tabs.addTab(window.services_stack, title)
            continue
        content = QWidget()
        content.setObjectName('page')
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 4, 10, 16)
        content_layout.setSpacing(12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        window.settings_tabs.addTab(scroll, title)
        sections[title] = content_layout
    navigation.addStretch()
    brand = QHBoxLayout()
    brand.setContentsMargins(11, 0, 0, 0)
    mark = QLabel()
    mark.setPixmap(line_icon('waveform', 14).pixmap(14, 14))
    brand.addWidget(mark)
    brand.addWidget(label('MurMur', 'muted'))
    brand.addStretch()
    navigation.addLayout(brand)
    layout.addWidget(window.settings_tabs, 1)
    outer.addWidget(categories)
    outer.addWidget(content_column, 1)

    def category_changed(index):
        for i, nav in enumerate(window.settings_category_buttons):
            nav.setChecked(i == index)
        if index != 1:
            window.show_services_overview()
    window.settings_tabs.currentChanged.connect(category_changed)
    category_changed(0)

    def group(category, title, icon='settings', parent_layout=None):
        panel = QWidget()
        panel.setMinimumWidth(0)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(5)
        heading = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(line_icon(icon, 15).pixmap(15, 15))
        heading.addWidget(mark)
        title_label = label(title)
        title_label.setWordWrap(False)
        title_label.setStyleSheet('font-size:12px;font-weight:600;' if parent_layout is None else 'font-size:12px;color:#b5b1c1;')
        heading.addWidget(title_label)
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet('background:#303035;border:0;')
        heading.addWidget(divider, 1)
        panel_layout.addLayout(heading)
        rows_widget = QWidget()
        rows = SettingsRows(rows_widget)
        panel_layout.addWidget(rows_widget)
        (sections[category] if parent_layout is None else parent_layout).addWidget(panel)
        return panel, rows

    def field(form, key, title, kind='text', options=None, description=''):
        form.pending_title, form.pending_description = title, description
        widget = window.field(form, key, title, kind, options)
        # SettingsForm.field applies its legacy 480px maximum after addRow.
        if kind != 'bool':
            widget.setMaximumWidth(260)
        return widget

    def note(text):
        widget = label(text, 'muted')
        widget.setStyleSheet('font-size:12px;')
        return widget

    def password(form, title, description, name):
        widget = QLineEdit()
        widget.setEchoMode(QLineEdit.Password)
        widget.setPlaceholderText('Blank keeps saved credentials')
        widget.setAccessibleName(name)
        form.pending_description = description
        form.addRow(title, widget)
        return widget

    _, f = group('General', 'Dictation', 'mic')
    field(f, 'demo', 'Demo mode', 'bool', description='Try a sample without recording or API requests.')
    field(f, 'polish', 'Refine dictated text', 'bool', description='Turn speech into clear writing in the original language.')
    field(f, 'smart_delivery', 'Show results only when needed', 'bool', description='Insert clear dictation and translations quietly. Review uncertain wording or copy when insertion cannot be confirmed.')
    devices = [('System default', '')]
    try:
        import sounddevice as sd
        devices += [(d['name'], str(i)) for i, d in enumerate(sd.query_devices()) if d['max_input_channels'] > 0]
    except Exception:
        pass
    field(f, 'microphone', 'Microphone', 'choice', devices, 'Choose an input device for recording.')
    field(f, 'language', 'Translate into', description='Only used in Translation mode.')
    _, f = group('General', 'Audio capture', 'waveform')
    field(f,'audio_warm_enabled','Keep microphone ready','bool',description='Capture continuously; keep only a short in-memory buffer. No recognition or upload while idle.')
    trim=field(f,'audio_quality_enabled','Trim silence for batch ASR','bool',description='Local and HTTP ASR only; streaming audio stays unchanged.')
    trim.setToolTip('Keep lead-in and tail padding around speech before batch recognition. Original saved recordings stay unchanged.')
    field(f,'audio_noise_gate','Reduce very quiet background noise','bool',description='Batch ASR only. May remove quiet speech; off by default.')
    window.audio_advanced=AdvancedSection()
    f.addRow(window.audio_advanced)
    preroll=window.field(window.audio_advanced.form,'audio_preroll_ms','Pre-record buffer · ms','int')
    preroll.setRange(0,2000)
    preroll.setToolTip('Include audio from before the recording shortcut. Default: 500 ms. Requires Keep microphone ready.')
    lead=window.field(window.audio_advanced.form,'audio_lead_padding_ms','Lead-in padding · ms','int')
    lead.setRange(0,2000)
    tail=window.field(window.audio_advanced.form,'audio_tail_padding_ms','Tail padding · ms','int')
    tail.setRange(0,1000)
    _, f = group('General', 'Startup')
    field(f, 'startup', 'Launch at sign-in', 'bool', description='Start MurMur in the system tray.')

    window.asr_service_section, f = group('Services', 'Speech to Text', 'mic', window.services_detail_layouts['asr'])
    backend = field(f, 'asr_backend', 'Provider', 'choice', [('Local speech model · offline', 'offline'), ('Bailian · online', 'bailian'), ('Alibaba Speech · online', 'ali_nls'), ('OpenAI · online', 'openai'), ('Groq · online', 'groq'), ('Custom compatible API · online', 'http_asr')], 'Choose where your audio is transcribed (ASR).')
    backend.currentIndexChanged.connect(window.update_asr_fields)
    asr_details = QVBoxLayout()
    asr_details.setSpacing(14)
    window.asr_service_section.layout().addLayout(asr_details)
    window.online_asr_panel, f = group('Services', 'Online · Bailian', 'waveform', asr_details)
    field(f, 'asr_model', 'Model', description='Your streaming speech recognition model.')
    window.asr_key = password(f, 'API key', 'Stored in Windows credentials.', 'Bailian API key')
    window.asr_hint = note('')
    f.addRow(window.asr_hint)
    window.add_service_test_row(f, 'asr')
    window.asr_advanced = AdvancedSection()
    f.addRow(window.asr_advanced)
    window.field(window.asr_advanced.form, 'asr_url', 'WebSocket endpoint')
    window.field(window.asr_advanced.form, 'vocabulary_id', 'Vocabulary ID')
    window.asr_advanced.form.addRow(note('Endpoint and key must use the same region. Supported FunASR models use the first 400 characters of Dictionary context; all terms remain saved locally.'))

    window.offline_asr_panel, f = group('Services', 'Offline · local speech model', 'waveform', asr_details)
    offline_engine = field(f, 'offline_engine', 'Speech model', 'choice', [
        ('SenseVoice Small · multilingual (default)', 'sensevoice'),
        ('Paraformer · Chinese / English', 'paraformer'),
        ('Fun-ASR-Nano · Chinese / English / Japanese', 'fun_asr_nano'),
        ('Qwen3-ASR 1.7B · multilingual', 'qwen_asr'),
    ], 'Choose a model for local speech recognition.')
    offline_engine.selected_summaries = {'sensevoice': 'SenseVoice Small · default', 'paraformer': 'Paraformer · Chinese / English', 'fun_asr_nano': 'Fun-ASR-Nano', 'qwen_asr': 'Qwen3-ASR 1.7B'}
    offline_engine.setToolTip('Choose a local speech model. Larger models need more disk space and memory; actual speed depends on your computer.')
    acceleration = field(f, 'offline_acceleration', 'Run on', 'choice', [('CPU · compatible', 'cpu'), ('GPU · DirectML / Vulkan', 'gpu')], 'CPU is the default. GPU needs compatible drivers and runtime support.')
    window.offline_acceleration_hint = note('')
    f.addRow(window.offline_acceleration_hint)
    acceleration.currentIndexChanged.connect(window.update_offline_acceleration)
    # Build the inline path control before adding the row; field registry is unchanged.
    temporary = QFormLayout()
    offline_path = window.field(temporary, 'offline_model_dir', 'Model folder')
    removed = temporary.takeRow(offline_path)
    removed.labelItem.widget().deleteLater()
    path_row = QWidget()
    path_layout = QHBoxLayout(path_row)
    path_layout.setContentsMargins(0, 0, 0, 0)
    path_layout.setSpacing(6)
    path_layout.addWidget(offline_path, 1)
    offline_path.setPlaceholderText(str(window.store.root / 'models' / 'sensevoice-small'))
    window.offline_browse = button('Browse…', window.browse_offline_model)
    window.offline_browse.setFixedWidth(75)
    path_layout.addWidget(window.offline_browse)
    f.pending_description = 'Speech recognition stays on this device.'
    f.addRow('Model folder', path_row)
    window.offline_download = button('Download model', window.install_offline.emit)
    window.offline_download.setMaximumWidth(150)
    f.addRow(window.offline_download)
    window.offline_status = ServiceStatusLabel()
    window.offline_status.text_changed.connect(lambda _text:window.update_services_overview())
    f.addRow(window.offline_status)
    f.addRow(note('This model produces the transcript. Polish uses a separate text model for refinement and translation.'))
    window.add_service_test_row(f, 'asr')
    window.offline_advanced = AdvancedSection()
    f.addRow(window.offline_advanced)
    window.field(window.offline_advanced.form, 'offline_language', 'Recognition language', 'choice', [('Auto detect', 'auto'), ('Chinese', 'zh'), ('English', 'en'), ('Cantonese', 'yue'), ('Japanese', 'ja'), ('Korean', 'ko')])
    window.offline_language_hint = note('')
    window.offline_advanced.form.addRow(window.offline_language_hint)
    threads = window.field(window.offline_advanced.form, 'offline_threads', 'CPU threads', 'int')
    threads.setRange(1, 8)
    window.offline_advanced.form.addRow(note('Up to 10 minutes per recording. Silero splits speech into segments of up to 20 seconds. Recognition works offline; the first model load may take a moment.'))
    offline_path.textChanged.connect(window.update_offline_readiness)
    offline_engine.currentIndexChanged.connect(window.update_offline_engine)

    window.ali_nls_panel, f = group('Services', 'Online · Alibaba Speech', 'waveform', asr_details)
    window.ali_appkey = password(f, 'AppKey', 'Your real-time transcription project.', 'Alibaba Speech AppKey')
    window.ali_token = password(f, 'Access token', 'Optional when AccessKeys are already saved.', 'Alibaba Speech temporary access token')
    window.ali_hint = note('')
    f.addRow(window.ali_hint)
    window.add_service_test_row(f, 'asr')
    window.ali_advanced = AdvancedSection()
    f.addRow(window.ali_advanced)
    window.field(window.ali_advanced.form, 'ali_nls_url', 'WebSocket endpoint')
    window.ali_advanced.form.addRow(note('Enable real-time transcription on your Alibaba account. Manual tokens expire; renew them before expiry.'))

    window.http_asr_panel, f = group('Services', 'Online · batch speech API', 'waveform', asr_details)
    model=field(f,'asr_http_model','Model',description='Audio is uploaded after recording stops. Original language is preserved.')
    window.asr_http_key=password(f,'API key','A separate key for this speech provider.','HTTP speech API key')
    window.http_asr_hint=note('')
    f.addRow(window.http_asr_hint)
    f.addRow(note('Test checks authentication and the model catalog only. It sends no audio and does not verify transcription.'))
    window.add_service_test_row(f,'asr')
    window.http_asr_advanced=AdvancedSection()
    f.addRow(window.http_asr_advanced)
    window.field(window.http_asr_advanced.form,'asr_http_url','API base URL')
    window.field(window.http_asr_advanced.form,'asr_http_language','Recognition language','choice',[('Auto detect','auto'),('Chinese','zh'),('English','en'),('Japanese','ja'),('Korean','ko'),('French','fr'),('German','de'),('Spanish','es')])
    timeout=window.field(window.http_asr_advanced.form,'asr_http_timeout','Request timeout · seconds','int')
    timeout.setRange(5,180)
    window.http_asr_advanced.form.addRow(note('Up to 10 minutes. WAV audio is sent to the selected endpoint; redirects and automatic fallback are disabled. Custom APIs require an explicit endpoint and model.'))
    window.http_asr_advanced.form.addRow(note('Supported OpenAI and Groq models use Dictionary terms as recognition hints, without a guarantee. Custom APIs receive no hints.'))

    window.llm_service_section, f = group('Services', 'Polish', 'edit', window.services_detail_layouts['llm'])
    window.llm_form = f
    window.llm_source = CompactComboBox()
    window.llm_source.addItem('Local · Qwen / local server', True)
    window.llm_source.addItem('Online · DeepSeek / API', False)
    f.pending_description = 'Use an on-device text model or an online text service.'
    f.addRow('Source', window.llm_source)
    window.llm_source.currentIndexChanged.connect(window.change_llm_source)
    window.llm_preset = CompactComboBox()
    for title, value in [('Custom', 'custom'), ('ProjectHub · Private API', 'projecthub'), ('Local · Auto', 'local_auto'), ('DeepSeek · Flash', 'deepseek'), ('Ollama · Auto', 'auto'), ('Ollama · Qwen3.5 2B', '2b'), ('Ollama · Qwen3.5 4B', '4b'), ('Ollama · Qwen3.5 9B', '9b')]:
        window.llm_preset.addItem(title, value)
    window.llm_preset.setToolTip('Fill provider, endpoint and model. Save changes to apply.')
    window.llm_preset.currentIndexChanged.connect(window.apply_llm_preset)
    f.pending_description = 'Select an installed Qwen size or an online model.'
    f.addRow('Model preset', window.llm_preset)
    window.llm_advanced = AdvancedSection()
    protocol = window.field(window.llm_advanced.form, 'ollama', 'API protocol', 'choice', [('OpenAI compatible', False), ('Ollama', True)])
    protocol.currentIndexChanged.connect(window.update_llm_fields)
    selection = field(f, 'ollama_auto', 'Model selection', 'choice', [('Auto · prefer 4–8B', True), ('Specify model', False)], AUTO_POLICY_DESCRIPTION)
    selection.setToolTip(AUTO_POLICY_HELP)
    selection.currentIndexChanged.connect(window.update_llm_selection)
    picker=field(f, 'llm_model', 'Text LLM', 'model', description='Enter an API key, refresh, then choose a model.')
    picker.refreshRequested.connect(lambda:window.request_model_refresh('llm'))
    window.llm_key = password(f, 'API key', 'Stored in Windows credentials.', 'Text processing API key')
    window.llm_hint = note('')
    f.addRow(window.llm_hint)
    window.add_service_test_row(f, 'llm')
    f.addRow(window.llm_advanced)
    window.field(window.llm_advanced.form, 'llm_url', 'API base URL')
    window.llm_advanced.form.addRow(note('Online providers receive your text. For Ollama, install the selected model before use.'))
    prices = QWidget()
    prices_layout = QHBoxLayout(prices)
    prices_layout.setContentsMargins(0, 0, 0, 0)
    prices_layout.setSpacing(9)
    for key, title in [('llm_input_price_per_million', 'Input'), ('llm_output_price_per_million', 'Output'), ('llm_cache_price_per_million', 'Cached')]:
        column = QFormLayout()
        column.setSpacing(5)
        column.setRowWrapPolicy(QFormLayout.WrapAllRows)
        window.field(column, key, title, 'price')
        prices_layout.addLayout(column, 1)
    window.llm_advanced.form.addRow(prices)
    window.llm_advanced.form.addRow(note('Optional USD per 1M tokens · blank = provider rate when known'))
    window.ask_service_section, f = group('Services', 'Ask Anything', 'mic', window.services_detail_layouts['ask'])
    field(f, 'ask_llm_url', 'API base URL', description='Independent external service for voice editing, questions and drafts.')
    picker=field(f, 'ask_llm_model', 'Model', 'model', description='Refresh to choose a model that follows the requested JSON format.')
    picker.refreshRequested.connect(lambda:window.request_model_refresh('ask'))
    window.ask_llm_key = password(f, 'API key', 'A separate key stored in Windows credentials.', 'Ask Anything API key')
    window.ask_llm_hint = note('')
    f.addRow(window.ask_llm_hint)
    f.addRow(note('Your spoken request and selected text are sent to this service. Answers appear in a card; edits and drafts write to a confirmed target.'))
    window.add_service_test_row(f, 'ask')
    f.addRow(note('ProjectHub: enter your key, click Refresh models, choose a model, then save. Refresh and Test only query availability. Queued tasks may take several minutes.'))
    window.remove_ask_key_button = button('Remove Ask key', window.clear_ask_key)
    f.addRow('Saved Ask key', window.remove_ask_key_button)
    window.remove_keys_button = button('Remove saved keys', window.clear_keys)
    window.remove_keys_button.setToolTip('Remove all MurMur API credentials, including speech and text services.')
    window.llm_advanced.form.addRow('All saved API keys', window.remove_keys_button)

    _, f = group('Shortcuts', 'Recording and editing', 'record')
    field(f, 'trigger', 'Recording mode', 'choice', [('Hold to record', 'hold'), ('Press to toggle', 'toggle')], 'How the dictation shortcut starts and stops recording.')
    key = field(f, 'dictation_key', 'Dictation', 'choice', [('Right Alt', 'right_alt'), ('F8', 'f8'), ('F9', 'f9'), ('Disabled (including F8)', 'disabled')], 'Record text for the current app.')
    key.currentIndexChanged.connect(window.update_shortcut_hint)
    field(f, 'translation_key', 'Translation', 'choice', [('Alt + Shift', 'alt+shift'), ('Ctrl + Shift + F9', 'ctrl+shift+f9'), ('Disabled', 'disabled')], 'Record and translate into your preferred language.')
    field(f, 'selection_key', 'Edit selection', 'choice', [('Alt + Space', 'alt+space'), ('Ctrl + Shift + Space', 'ctrl+shift+space'), ('Disabled', 'disabled')], 'Open writing tools for the text you selected.')
    field(f, 'ask_key', 'Ask Anything', 'choice', [('Right Alt + Space', 'right_alt+space'), ('Ctrl + Shift + A', 'ctrl+shift+a'), ('Disabled', 'disabled')], 'Press to start; Right Alt or this shortcut finishes. Always uses toggle mode.')
    f.addRow(note('Press Right Alt before Space. Left Alt + Space opens the selection editor.'))
    window.key_status = note('')
    f.addRow(window.key_status)

    _, f = group('Appearance', 'Floating bubble', 'waveform')
    window.bubble_preview_button=button('Preview animation',lambda:preview_bubble(window))
    window.bubble_preview_button.setIcon(line_icon('play',16))
    f.addRow(window.bubble_preview_button)
    field(f, 'bubble_position', 'Position', 'choice', [('Bottom center','bottom'),('Top center','top'),('Left center','left'),('Right center','right'),('Top left','top-left'),('Top right','top-right'),('Bottom left','bottom-left'),('Bottom right','bottom-right')], 'Anchor on the selected display.')
    field(f, 'bubble_screen', 'Display', 'choice', [(f'{i + 1} · {s.name()}', i) for i, s in enumerate(QApplication.screens())], 'Follow mouse uses the pointer’s current display.')
    edge=field(f, 'bubble_offset', 'Edge spacing · px', 'int', description='Distance from the available screen edge.')
    edge.setRange(0,3650)
    follow=field(f,'bubble_follow_mouse','Follow mouse','bool',description='Stay beside the pointer. Pause while hovering to click buttons.')
    gap=field(f,'bubble_cursor_offset','Pointer spacing · px','int',description='Used when following the mouse, on its current display.')
    gap.setRange(12,160)
    def follow_changed(checked):
        for key in ('bubble_position','bubble_screen','bubble_offset'):window.fields[key].setEnabled(not checked)
        gap.setEnabled(checked)
    follow.toggled.connect(follow_changed);follow_changed(follow.isChecked())
    _, f = group('Appearance', 'Size')
    width = field(f, 'bubble_width', 'Capsule width · px', 'int')
    width.setRange(200,360)
    height=field(f,'bubble_height','Capsule height · px','int');height.setRange(40,64)
    result=field(f,'bubble_result_width','Result width · px','int');result.setRange(320,640)
    _, f = group('Appearance', 'Motion')
    styles=[('Pop','pop'),('Slide','slide'),('Fade','fade'),('None','none')]
    field(f,'bubble_enter_motion','Appear','choice',styles,'Pop rises from the bottom edge with a soft liquid stretch and rebound.')
    field(f,'bubble_exit_motion','Disappear','choice',[('Burst','burst')]+styles,'Burst releases a soft splash of liquid droplets that disperse and fade.')
    field(f,'bubble_state_motion','Animate state changes','bool',description='Blend recording, processing and result states.')
    field(f,'bubble_wave_motion','Animate voice indicator','bool',description='Show live microphone levels. Off keeps a static microphone indicator.')
    field(f,'bubble_wave_style','Voice indicator style','choice',
          [('Scrolling bars · Classic','bars'),('Soft ribbon','centered'),('Neon matrix','dots'),('Smooth line','line'),('Recording timeline','timeline')],
          'Preview each style below. Height, stroke width and grid spacing stay fixed as the bubble grows.')
    speed=field(f,'bubble_motion_duration','Motion duration · ms','int',description='Shorter is faster. Preview uses current unsaved choices.')
    speed.setRange(120,500)
    _, f = group('Appearance', 'Local data', 'history')
    retention=field(f, 'retention', 'Keep history', 'int', description='Days to retain records. Set 0 to keep forever.')
    retention.setRange(0,3650)
    field(f, 'save_audio', 'Save recordings', 'bool', description='Keep audio locally alongside your history.')
    data_note = note('Data stays on this device.')
    data_note.setToolTip(str(window.store.root))
    f.addRow(data_note)
    from .storage_usage import LocalStorageUsage
    window.local_storage_usage=LocalStorageUsage(window.store.root)
    f.addRow(window.local_storage_usage)

    _, f = group('Writing', 'Writing preferences', 'edit')
    field(f, 'style', 'Writing style', description='Tone for clear writing in the original language.')
    rules = field(f, 'rules', 'Replacement rules', 'long', description='Exact, literal replacements applied to text.')
    rules.setPlaceholderText('Original => Replacement\nOne replacement per line')
    mode_names = {'听写': 'Dictation', '翻译': 'Translation', '润色': 'Refine', '总结': 'Summary', '扩写': 'Expand', '自定义': 'Custom', '语音指令': 'Voice instruction'}
    _, f = group('Writing', 'Operation prompts', 'edit')
    for mode, prompt in window.store.config['prompts'].items():
        editor = QPlainTextEdit(prompt)
        editor.setFixedHeight(90)
        editor.setAccessibleName(mode_names.get(mode, mode) + ' prompt')
        f.addRow(mode_names.get(mode, mode), editor)
        window.prompt_fields[mode] = editor

    for section in sections.values():
        section.addStretch()
    for section in window.services_detail_layouts.values():
        section.addStretch()
    divider = QFrame()
    divider.setFixedHeight(1)
    divider.setStyleSheet('background:#303035;border:0;')
    layout.addWidget(divider)
    footer = QHBoxLayout()
    window.settings_status = note(getattr(window.store, 'config_warning', '') or 'Changes take effect after saving.')
    footer.addWidget(window.settings_status, 1)
    window.save_button = button('Save changes', window.save, True)
    footer.addWidget(window.save_button)
    layout.addLayout(footer)
    window.update_offline_engine()
    window.update_asr_fields()
    window.update_llm_fields()
    window.update_offline_readiness()
    window.update_shortcut_hint()
    window.wire_service_test_changes()
    for kind,prefix,key_field in [('llm','llm',window.llm_key),('ask','ask_llm',window.ask_llm_key)]:
        picker=window.fields[prefix+'_model']
        picker.modelsChanged.connect(window.update_services_overview)
        window.fields[prefix+'_url'].textChanged.connect(picker.clearModels)
        key_field.textChanged.connect(picker.clearModels)
        key_field.editingFinished.connect(lambda service=kind:window.refresh_models_after_key(service))
    for key in ('llm_url', 'llm_model'):
        window.fields[key].textChanged.connect(window.update_llm_profile)
    window.fields['llm_url'].textChanged.connect(window.update_llm_selection)
    window.update_settings_actions()
    window.update_services_overview()
    return page

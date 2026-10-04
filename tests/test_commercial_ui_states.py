"""Genuine UI states using isolated records, no desktop, microphone or keys."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QLabel,QSizePolicy
from murmur import storage
from murmur.dashboard import MainWindow
from murmur.ui import STYLE
from murmur.service_settings import ModelLabel


@pytest.fixture
def window(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(storage,'credential',lambda *args:'')
    monkeypatch.setattr(storage,'DEFAULT_OFFLINE_MODELS_ROOT',tmp_path/'models')
    import sounddevice,httpx
    monkeypatch.setattr(sounddevice,'query_devices',lambda:[])
    monkeypatch.setattr(httpx,'Client',lambda *args,**kwargs:pytest.fail('UI state must not access network'))
    store=storage.Store(tmp_path/'data')
    widget=MainWindow(store);widget.setStyleSheet(STYLE);widget.show();QTest.qWait(180)
    yield widget
    widget.hide();widget.deleteLater();store.db.close()


@pytest.mark.parametrize('provider,model,expected',[
    ('bailian','fun-asr-realtime','Bailian uses up to 400'),
    ('bailian','unsupported-streaming-model','does not receive'),
    ('openai','gpt-transcribe','OpenAI keywords'),
    ('openai','gpt-4o-mini-transcribe','OpenAI uses a short'),
    ('groq','whisper-large-v3-turbo','Groq uses a short'),
    ('groq','unknown-model','does not receive'),
    ('http_asr','gpt-transcribe','does not receive'),
    ('offline','sensevoice','does not receive'),
    ('ali_nls','realtime','does not receive'),
])
def test_dictionary_notice_describes_saved_actual_capability(window,provider,model,expected):
    window.store.config.update(demo=False,asr_backend=provider,asr_model=model,asr_http_model=model)
    window.refresh_words()
    assert expected in window.vocabulary_notice.text()
    assert 'do not guarantee accuracy' in window.vocabulary_notice.toolTip()
    # An unsaved model/provider change must not be mistaken for the active ASR.
    window.fields['asr_backend'].setCurrentIndex(window.fields['asr_backend'].findData('http_asr'))
    window.refresh_words()
    assert expected in window.vocabulary_notice.text()


def test_demo_dictionary_notice_never_claims_online_hint_delivery(window):
    window.store.config.update(demo=True,asr_backend='openai',asr_http_model='gpt-transcribe')
    window.refresh_words()
    assert 'no ASR hints are sent' in window.vocabulary_notice.text()


def test_long_dictionary_terms_keep_compact_equal_rows_and_full_identity(window):
    term='Long scientific phrase '+'x'*55
    window.store.add_word(term)
    window.refresh_words();window.navigate(2);QTest.qWait(180)
    chips=[];texts=[]
    for i in range(window.words_grid.count()):
        widget=window.words_grid.itemAt(i).widget()
        if widget.objectName()=='card':
            chips.append(widget)
            texts.extend(widget.findChildren(ModelLabel))
    long=next(text for text in texts if text.text()==term)
    assert term in long.toolTip() and long.accessibleName()==term
    assert long.sizePolicy().horizontalPolicy()==QSizePolicy.Ignored
    assert long.fontMetrics().elidedText(term,Qt.ElideRight,long.width())!=term
    assert len({chip.height() for chip in chips})==1
    assert max(chip.height() for chip in chips)<=44
    assert window.stack.widget(2).horizontalScrollBar().maximum()==0


def test_install_progress_and_failure_relay_to_compact_overview(window):
    window.navigate(3);window.settings_tabs.setCurrentIndex(1)
    window.set_service_test_state('asr',False,'Model loaded','Previous synthetic file-load check.',True)
    window.set_offline_download_state(True)
    status=window.service_overview_status['asr'];progress=window.service_overview_progress['asr']
    assert status.text()=='Preparing model download…' and progress.text()=='Installing…'
    assert not progress.isHidden()
    assert all(not details.isEnabled() for _,_,details in window.service_test_controls['asr'])
    phase='Downloading model.onnx · 42% · 101 MB / 240 MB'
    window.offline_status.setText(phase)
    assert status.text()==phase and status.toolTip()==phase
    window.set_offline_download_state(False)
    window.offline_status.setText('Download failed. Check your connection and try again.')
    assert status.text().startswith('Download failed.') and progress.isHidden()
    assert window.services_install_button.isEnabled()
    assert all(button.isEnabled() for button,_,_ in window.service_test_controls['asr'])
    assert all(window.services_overview.rect().contains(card.geometry()) for card in window.services_cards.values())


def test_install_success_is_file_status_not_a_fabricated_model_test(window):
    window.set_offline_download_state(True);window.set_offline_download_state(False)
    text='Model files downloaded and verified. Save changes to use this folder.'
    window.offline_status.setText(text)
    assert window.service_overview_status['asr'].text()==text
    assert window.service_test_success.get('asr') is not True


def test_idle_instructions_point_to_available_record_controls(window):
    window.navigate(1)
    text=' '.join(label.text() for label in window.stack.widget(1).findChildren(QLabel))
    assert 'Use the button below or your dictation shortcut' in text
    assert 'Record with the capsule' not in text
    window.fields['dictation_key'].setCurrentIndex(window.fields['dictation_key'].findData('disabled'))
    assert 'Record from Home' in window.key_status.text()
    assert 'Record button on Home' in window.key_status.toolTip()

"""Provider drafts, user-triggered install and catalog checks; synthetic only."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from copy import deepcopy
import httpx
import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication
from murmur import cloud_asr,service_checks,storage
from murmur.dashboard import MainWindow
from murmur.ui import STYLE


@pytest.fixture
def window(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(storage,'credential',lambda *args:'')
    monkeypatch.setattr(storage,'DEFAULT_OFFLINE_MODELS_ROOT',tmp_path/'models')
    import sounddevice
    monkeypatch.setattr(sounddevice,'query_devices',lambda:[])
    monkeypatch.setattr(httpx,'Client',lambda *args,**kwargs:pytest.fail('Settings must not access network'))
    store=storage.Store(tmp_path/'data')
    widget=MainWindow(store);widget.setStyleSheet(STYLE);widget.navigate(3);widget.settings_tabs.setCurrentIndex(1)
    widget.show();QTest.qWait(180)
    yield widget
    for dialog in widget.service_test_dialogs.values():dialog.deleteLater()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
    app.processEvents();store.db.close()


def provider(window,value):
    selector=window.fields['asr_backend']
    selector.setCurrentIndex(selector.findData(value))


def test_six_providers_have_mutually_exclusive_panels_and_original_defaults(window):
    panels={'offline':window.offline_asr_panel,'bailian':window.online_asr_panel,'ali_nls':window.ali_nls_panel,
            'openai':window.http_asr_panel,'groq':window.http_asr_panel,'http_asr':window.http_asr_panel}
    for value,panel in panels.items():
        provider(window,value)
        assert not panel.isHidden()
        assert all(other.isHidden() for other in set(panels.values()) if other is not panel)
        if value in cloud_asr.HTTP_DEFAULTS:
            assert window.fields['asr_http_model'].text()==cloud_asr.HTTP_DEFAULTS[value]['model']
            assert window.fields['asr_http_url'].text()==cloud_asr.HTTP_DEFAULTS[value]['url']
            assert window.fields['asr_http_language'].currentData()=='auto'
            assert 'No audio' in window.service_test_controls['asr'][0][0].toolTip()


def test_http_profiles_and_key_drafts_are_independent_without_saving(window):
    baseline=deepcopy(window.store.config)
    provider(window,'openai')
    window.fields['asr_http_url'].setText('https://custom-openai.invalid/v1')
    window.fields['asr_http_model'].setText('custom-openai-model')
    window.fields['asr_http_timeout'].setValue(78)
    window.asr_http_key.setText('synthetic-openai-draft')
    provider(window,'groq')
    assert window.fields['asr_http_model'].text()=='whisper-large-v3-turbo' and window.asr_http_key.text()==''
    window.fields['asr_http_model'].setText('whisper-large-v3')
    window.asr_http_key.setText('synthetic-groq-draft')
    provider(window,'http_asr')
    assert window.fields['asr_http_url'].text()=='' and window.fields['asr_http_model'].text()==''
    window.fields['asr_http_url'].setText('http://192.168.1.2:8000/v1')
    window.fields['asr_http_model'].setText('custom-lan-speech')
    provider(window,'offline');provider(window,'openai')
    assert window.fields['asr_http_url'].text()=='https://custom-openai.invalid/v1'
    assert window.fields['asr_http_model'].text()=='custom-openai-model'
    assert window.fields['asr_http_timeout'].value()==78
    assert window.asr_http_key.text()=='synthetic-openai-draft'
    config,secrets=window.service_test_values()
    assert config['asr_http_profiles']['groq']['model']=='whisper-large-v3'
    assert config['asr_http_profiles']['http_asr']['model']=='custom-lan-speech'
    assert secrets['asr_openai_key']=='synthetic-openai-draft' and secrets['asr_groq_key']=='synthetic-groq-draft'
    assert window.store.config==baseline


def test_overview_selects_actual_http_model_and_preserves_drafts(window):
    choices=window.services_model_choices['asr']
    choices.setCurrentIndex(choices.findData('openai'))
    assert window.fields['asr_backend'].currentData()=='openai'
    assert window.fields['asr_http_model'].text()=='gpt-transcribe'
    window.fields['asr_http_model'].setText('custom long model '+'x'*100)
    window.update_services_overview()
    assert 'custom long model' in choices.currentText()
    assert 'batch upload' in window.service_overview_models['asr'].text()
    choices.setCurrentIndex(choices.findData('groq'));choices.setCurrentIndex(choices.findData('openai'))
    assert window.fields['asr_http_model'].text().startswith('custom long model')
    assert window.services_stack.currentIndex()==0


def test_install_is_explicit_and_locked_when_recording_or_checking(window):
    spy=QSignalSpy(window.install_offline)
    button=window.services_install_button
    assert not button.isHidden() and button.isEnabled() and spy.count()==0
    button.click();assert spy.count()==1
    window.set_session_state('录音','听写');assert not button.isEnabled()
    window.set_session_state('idle','听写')
    window.set_service_test_state('asr',True);assert not button.isEnabled()
    window.set_service_test_state('asr',False)
    provider(window,'openai');assert button.isHidden()


def test_file_presence_hides_install_but_does_not_claim_model_test_success(window,tmp_path):
    folder=tmp_path/'model';folder.mkdir()
    (folder/'model.int8.onnx').write_bytes(b'synthetic-not-model')
    (folder/'tokens.txt').write_text('synthetic',encoding='utf-8')
    (folder/'silero_vad.onnx').write_bytes(b'synthetic-not-model')
    window.fields['offline_model_dir'].setText(str(folder))
    assert window.services_install_button.isHidden()
    assert 'files found' in window.offline_status.text() and 'Test' in window.offline_status.text()
    assert window.service_test_success.get('asr') is not True


def test_audio_controls_snapshot_and_bounds(window):
    window.fields['audio_quality_enabled'].setChecked(False)
    window.fields['audio_noise_gate'].setChecked(True)
    window.fields['audio_lead_padding_ms'].setValue(500)
    window.fields['audio_tail_padding_ms'].setValue(260)
    cfg,_=window.service_test_values()
    assert cfg['audio_quality_enabled'] is False and cfg['audio_noise_gate'] is True
    assert cfg['audio_lead_padding_ms']==500 and cfg['audio_tail_padding_ms']==260
    assert window.fields['audio_lead_padding_ms'].maximum()==2000
    assert window.fields['audio_tail_padding_ms'].maximum()==1000


def test_save_emits_all_provider_drafts_and_remove_cannot_restore_them(window,monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    writes=[]
    monkeypatch.setattr(storage,'credential',lambda name,value=None:writes.append((name,value)) if value is not None else '')
    monkeypatch.setattr(QMessageBox,'information',lambda *args:None)
    monkeypatch.setattr(QMessageBox,'warning',lambda *args:None)
    provider(window,'openai');window.asr_http_key.setText('draft-openai')
    provider(window,'groq');window.asr_http_key.setText('draft-groq')
    spy=QSignalSpy(window.save_settings)
    window.save_button.click()
    assert spy.count()==1
    _,secrets=spy.at(0)
    assert secrets['asr_openai_key']=='draft-openai' and secrets['asr_groq_key']=='draft-groq'
    assert writes==[]
    window.clear_keys()
    assert set(cloud_asr.KEY_SLOTS.values()) <= {name for name,value in writes if value==''}
    provider(window,'openai');assert window.asr_http_key.text()==''
    _,secrets=window.service_test_values()
    assert all(secrets[slot]=='' for slot in cloud_asr.KEY_SLOTS.values())


@pytest.mark.parametrize('listed',[True,False])
def test_service_check_catalog_semantics_without_microphone(monkeypatch,listed):
    cfg=dict(asr_backend='openai',asr_http_url='https://synthetic.invalid/v1',asr_http_model='gpt-transcribe',asr_http_language='auto',asr_http_timeout=5)
    original=httpx.Client;requests=[]
    def handle(request):
        requests.append(request)
        return httpx.Response(200,json={'data':[{'id':'gpt-transcribe' if listed else 'another'}]})
    monkeypatch.setattr(cloud_asr.httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(handle),**kwargs))
    monkeypatch.setattr(cloud_asr,'credential',lambda slot:pytest.fail('draft test must not read saved key'))
    import sounddevice
    monkeypatch.setattr(sounddevice,'InputStream',lambda *args,**kwargs:pytest.fail('catalog test must not open microphone'))
    result=service_checks.check_service('asr',cfg,{'asr_openai_key':'synthetic'})
    assert result['success'] is listed
    assert 'No audio' in result['detail'] and 'transcription' in result['detail']
    assert len(requests)==1 and requests[0].method=='GET' and requests[0].content==b''
    assert 'synthetic' not in result['detail']

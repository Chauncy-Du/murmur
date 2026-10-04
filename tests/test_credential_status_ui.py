"""Saved-key guidance uses a mock vault, never real user credentials."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from murmur import storage
from murmur.dashboard import MainWindow


NAMES = ('asr', 'llm', 'ask_llm', 'ali_appkey', 'ali_token', 'ali_access_key_id', 'ali_access_key_secret', 'ali_token_expiry', 'asr_openai_key', 'asr_groq_key', 'asr_http_key')


@pytest.fixture
def mocked_settings(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    values, removed = {}, []

    def fake_credential(name, value=None):
        if value is not None:
            removed.append(name)
            if value:
                values[name] = value
            else:
                values.pop(name, None)
        return values.get(name, '')

    monkeypatch.setattr(storage, 'credential', fake_credential)
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: None)
    store=storage.Store(tmp_path);store.config.update(ollama=False,llm_url=storage.ONLINE_LLM_DEFAULTS[0],llm_model=storage.ONLINE_LLM_DEFAULTS[1])
    window = MainWindow(store)
    yield window, values, removed
    window.hide()


def test_saved_and_missing_status_never_populates_password_fields(mocked_settings):
    window, values, removed = mocked_settings
    assert 'Key not saved' in window.asr_hint.text()
    assert 'Key not saved' in window.llm_hint.text()
    assert 'AppKey not saved' in window.ali_hint.text()
    assert 'AccessKeys not saved' in window.ali_hint.text()
    assert 'Token not saved' in window.ali_hint.text()
    values.update({name: 'mock private value' for name in NAMES})
    window.refresh()
    assert 'Key saved' in window.asr_hint.text()
    assert 'Key saved' in window.llm_hint.text()
    for title in ('AppKey', 'AccessKeys', 'Token'):
        assert title + ' saved' in window.ali_hint.text()
    assert 'refresh tokens automatically' in window.ali_hint.text()
    for name in ('asr_key', 'llm_key', 'ask_llm_key', 'ali_appkey', 'ali_token'):
        assert getattr(window, name).text() == ''
    for hint in (window.asr_hint, window.llm_hint, window.ali_hint):
        assert 'mock private value' not in hint.text()
        assert 'has not been checked' in hint.toolTip()
    assert removed == []


def test_remove_clears_access_keys_expiry_and_refreshes_status(mocked_settings):
    window, values, removed = mocked_settings
    values.update({name: 'mock saved value' for name in NAMES})
    for name in ('asr_key', 'llm_key', 'ask_llm_key', 'ali_appkey', 'ali_token'):
        getattr(window, name).setText('unsaved value')
    window.clear_keys()
    assert set(removed) == set(NAMES)
    assert values == {}
    assert 'Key not saved' in window.llm_hint.text()
    assert 'AccessKeys not saved' in window.ali_hint.text()
    assert 'Token not saved' in window.ali_hint.text()
    assert all(getattr(window, name).text() == '' for name in ('asr_key', 'llm_key', 'ask_llm_key', 'ali_appkey', 'ali_token'))


def test_local_provider_does_not_imply_api_key_required(mocked_settings):
    window, values, removed = mocked_settings
    window.fields['ollama'].setCurrentIndex(window.fields['ollama'].findData(True))
    assert 'Local API' in window.llm_hint.text()
    assert not window.llm_key.isEnabled()


def test_vault_failure_never_exposes_exception_text(mocked_settings, monkeypatch):
    window, values, removed = mocked_settings

    def unavailable(*args):
        raise RuntimeError('private exception details')

    monkeypatch.setattr(storage, 'credential', unavailable)
    window.update_credential_status()
    assert 'status unavailable' in window.asr_hint.text()
    assert 'status unavailable' in window.ali_hint.text()
    assert all('private exception details' not in hint.text() for hint in (window.asr_hint, window.ali_hint, window.llm_hint))
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda parent, title, message: warnings.append(message))
    window.clear_keys()
    assert warnings == ['Could not remove all saved credentials. Try again.']


def test_one_removal_failure_does_not_skip_access_keys(mocked_settings, monkeypatch):
    window, values, removed = mocked_settings
    values.update({name: 'mock saved value' for name in NAMES})
    original = storage.credential

    def partial_failure(name, value=None):
        if name == 'asr' and value is not None:
            raise RuntimeError('private removal error')
        return original(name, value)

    warnings = []
    monkeypatch.setattr(storage, 'credential', partial_failure)
    monkeypatch.setattr(QMessageBox, 'warning', lambda parent, title, message: warnings.append(message))
    window.clear_keys()
    assert set(removed) == set(NAMES) - {'asr'}
    assert values == {'asr': 'mock saved value'}
    assert 'Key saved' in window.asr_hint.text()
    assert 'AccessKeys not saved' in window.ali_hint.text()
    assert warnings == ['Could not remove all saved credentials. Try again.']


def test_entire_credential_removal_holds_shared_lock(mocked_settings, monkeypatch):
    window, values, removed = mocked_settings
    active, entered = [], []

    class Lock:
        def __enter__(self):
            active.append(True)
            entered.append(True)

        def __exit__(self, *args):
            active.pop()

    original = storage.credential

    def checked(name, value=None):
        if value is not None:
            assert active == [True]
        return original(name, value)

    monkeypatch.setattr(storage, 'credential_lock', Lock())
    monkeypatch.setattr(storage, 'credential', checked)
    window.clear_keys()
    assert entered == [True] and active == []
    assert set(removed) == set(NAMES)


def test_remove_ask_key_isolated_under_lock_and_only_invalidates_ask(mocked_settings,monkeypatch):
    window,values,removed=mocked_settings
    values.update({name:'saved-'+name for name in NAMES})
    before=dict(values)
    for name in ('asr_key','llm_key','ask_llm_key','ali_appkey','ali_token'):
        getattr(window,name).setText('draft-'+name)
    for kind in ('asr','llm','ask'):
        window.set_service_test_state(kind,False,'Connected',kind+' details',True)
    active=[];entries=[];original=storage.credential
    class Lock:
        def __enter__(self):active.append(True);entries.append(True)
        def __exit__(self,*args):active.pop()
    def checked(name,value=None):
        if value is not None:assert name=='ask_llm' and active==[True]
        return original(name,value)
    monkeypatch.setattr(storage,'credential_lock',Lock())
    monkeypatch.setattr(storage,'credential',checked)
    assert window.remove_ask_key_button.isEnabled()
    window.remove_ask_key_button.click()
    assert removed==['ask_llm'] and entries==[True] and not active
    assert values=={name:value for name,value in before.items() if name!='ask_llm'}
    assert window.ask_llm_key.text()=='' and 'Ask key not saved' in window.ask_llm_hint.text()
    assert window.settings_status.text()=='Ask Anything key removed.'
    for name in ('asr_key','llm_key','ali_appkey','ali_token'):
        assert getattr(window,name).text()=='draft-'+name
    for kind in ('asr','llm'):
        assert window.service_test_results[kind]==('Connected',kind+' details')
    assert window.service_test_results['ask']==('Not checked','')


@pytest.mark.parametrize('busy',('recording','asr','llm','ask'))
def test_remove_ask_key_obeys_recording_and_connection_guards(mocked_settings,busy):
    window,values,removed=mocked_settings
    values['ask_llm']='saved-ask';window.ask_llm_key.setText('draft-ask')
    if busy=='recording':window.set_session_state('录音','随便问')
    else:window.set_service_test_state(busy,True)
    assert not window.remove_ask_key_button.isEnabled()
    window.clear_ask_key()
    assert removed==[] and values=={'ask_llm':'saved-ask'}
    assert window.ask_llm_key.text()=='draft-ask'
    assert window.settings_status.text()=='Finish the current session or connection test first.'
    if busy=='recording':window.set_session_state(None)
    else:window.set_service_test_state(busy,False)
    assert window.remove_ask_key_button.isEnabled()


def test_remove_ask_key_failure_keeps_saved_presence_and_sanitizes_status(mocked_settings,monkeypatch):
    window,values,removed=mocked_settings
    values.update(ask_llm='saved-ask',llm='saved-general')
    window.ask_llm_key.setText('draft-ask');original=storage.credential
    def failure(name,value=None):
        if name=='ask_llm' and value is not None:raise RuntimeError('private failure details')
        return original(name,value)
    monkeypatch.setattr(storage,'credential',failure)
    window.clear_ask_key()
    assert not removed and values=={'ask_llm':'saved-ask','llm':'saved-general'}
    assert window.ask_llm_key.text()=='' and 'Ask key saved' in window.ask_llm_hint.text()
    assert window.settings_status.text()=='Could not remove the Ask Anything key. Try again.'
    assert 'private failure details' not in window.settings_status.text()

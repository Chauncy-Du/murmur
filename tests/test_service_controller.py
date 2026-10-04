"""Service checks run off the GUI thread and cannot endorse stale settings."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import threading
import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from murmur.app import Controller
from murmur.storage import Store

@pytest.fixture(autouse=True)
def isolate_machine_dependencies(tmp_path, monkeypatch):
    from murmur import app as app_module, storage
    monkeypatch.setattr(storage, 'credential', lambda *args: '')
    monkeypatch.setattr(app_module, 'credential', lambda *args: '')
    monkeypatch.setattr(storage, 'DEFAULT_OFFLINE_MODELS_ROOT', tmp_path / 'models')
    monkeypatch.setattr(app_module.windows, 'prepare_text_context', lambda: None)
    import sounddevice
    monkeypatch.setattr(sounddevice, 'query_devices', lambda: [])

@pytest.fixture
def controller(tmp_path):
    app=QApplication.instance() or QApplication([])
    c=Controller(app,Store(tmp_path),False)
    yield c
    for _,cancel,_ in c.service_tests.values():cancel.set()
    c.quitting=True;c.monitor.stop();c.tray.hide();c.bubble.hide();c.result_bubble.hide();c.preview.hide();c.window.hide()

def wait_until(predicate):
    for _ in range(200):
        if predicate():return
        QTest.qWait(10)
    pytest.fail('Background fixture did not finish')

def install_check(c,monkeypatch):
    from murmur import service_checks
    entered=threading.Event();release=threading.Event();finished=threading.Event();seen={};states=[]
    original=c.window.set_service_test_state
    def state(*args,**kwargs):states.append((args,kwargs));original(*args,**kwargs)
    monkeypatch.setattr(c.window,'set_service_test_state',state)
    def check(kind,cfg,secrets,cancel,usage_sink=None):
        seen.update(kind=kind,model=cfg['llm_model'],key=secrets['llm'],thread=threading.current_thread(),cancel=cancel)
        entered.set()
        while not release.wait(.01):
            if cancel.is_set():break
        finished.set()
        return {'success':True,'summary':'Fixture connected','detail':'Fixture only.','elapsed':.1}
    monkeypatch.setattr(service_checks,'check_service',check)
    return entered,release,finished,seen,states

def test_check_uses_unsaved_values_in_background_without_persisting(controller,monkeypatch):
    c=controller;old_model=c.store.config['llm_model']
    c.window.fields['llm_model'].setText('fixture-unsaved-model');c.window.llm_key.setText('fixture-unsaved-key')
    entered,release,finished,seen,states=install_check(c,monkeypatch)
    cfg,secrets=c.window.service_test_values();c.test_service('llm',cfg,secrets)
    try:
        assert entered.wait(2)
        assert seen['thread'] is not threading.current_thread()
        assert seen['model']=='fixture-unsaved-model' and seen['key']=='fixture-unsaved-key'
        assert c.store.config['llm_model']==old_model
    finally:release.set()
    wait_until(lambda:not c.service_tests)
    assert states[-1][0][2]=='Fixture connected'
    assert not c.store.path.exists()  # No save action occurred.


@pytest.mark.parametrize('kind', ['asr', 'llm', 'ask'])
def test_interrupted_worker_finishes_cancelled_and_unlocks_settings(controller, monkeypatch, kind):
    from murmur import service_checks
    def interrupted(*args, **kwargs):
        raise InterruptedError('Synthetic cancelled worker')
    monkeypatch.setattr(service_checks, 'check_service', interrupted)
    c = controller
    cfg, secrets = c.window.service_test_values()
    c.test_service(kind, cfg, secrets)
    wait_until(lambda: not c.service_tests)
    assert not c.window.service_test_busy[kind]
    assert c.window.service_test_results[kind] == ('Cancelled', 'Connection check cancelled.')
    assert c.window.save_button.isEnabled()
    assert all(button.isEnabled() and status.text() == 'Cancelled'
               for button, status, details in c.window.service_test_controls[kind])


def test_saving_a_tested_draft_key_preserves_completed_result(controller, monkeypatch):
    from murmur import app as app_module, service_checks
    c = controller
    c.window.fields['llm_url'].setText('https://example.invalid/v1')
    c.window.fields['llm_model'].setText('synthetic-model')
    c.window.llm_key.setText('synthetic-draft-key')
    writes = []
    def vault(name, value=None):
        if value is not None:
            writes.append((name, value))
        return ''
    monkeypatch.setattr(app_module, 'credential', vault)
    monkeypatch.setattr(service_checks, 'check_service', lambda *args, **kwargs: {
        'success': True, 'summary': 'Connected', 'detail': 'Synthetic tested draft key.',
        'model': 'synthetic-model', 'model_selection': 'manual',
    })
    cfg, secrets = c.window.service_test_values()
    c.test_service('llm', cfg, secrets)
    wait_until(lambda: not c.service_tests)
    before = c.window.service_test_results['llm']
    metadata = dict(c.window.service_model_metadata['llm'])
    c.save_settings(cfg, secrets)
    assert writes == [('llm', 'synthetic-draft-key')]
    assert c.window.llm_key.text() == '' and c.store.path.exists()
    assert c.window.service_test_results['llm'] == before
    assert c.window.service_model_metadata['llm'] == metadata
    assert not c.window.service_test_busy['llm'] and c.window.save_button.isEnabled()

def test_changed_settings_reject_old_success(controller,monkeypatch):
    c=controller;entered,release,finished,seen,states=install_check(c,monkeypatch)
    cfg,secrets=c.window.service_test_values();c.test_service('llm',cfg,secrets)
    try:
        assert entered.wait(2)
        c.window.fields['llm_model'].setText('changed-after-test')
    finally:release.set()
    wait_until(lambda:not c.service_tests)
    assert states[-1][0][2]=='Settings changed. Test again.'
    assert states[-1][0][-1] is None

def test_quit_cancels_checks_and_ignores_late_result(controller,monkeypatch):
    c=controller;entered,release,finished,seen,states=install_check(c,monkeypatch)
    monkeypatch.setattr(c.app,'quit',lambda:None)
    cfg,secrets=c.window.service_test_values();c.test_service('llm',cfg,secrets)
    try:
        assert entered.wait(2)
        c.quit()
        assert seen['cancel'].is_set() and not c.service_tests
    finally:release.set()
    assert finished.wait(2)
    QTest.qWait(30)
    assert len(states)==1 and states[0][0]==('llm',True)


def test_save_during_check_does_not_change_credentials_or_settings(controller,monkeypatch):
    from murmur import app as app_module
    c=controller;entered,release,finished,seen,states=install_check(c,monkeypatch)
    writes=[]
    monkeypatch.setattr(app_module,'credential',lambda *args:writes.append(args))
    cfg,secrets=c.window.service_test_values()
    c.test_service('llm',cfg,secrets)
    try:
        assert entered.wait(2)
        c.save_settings(dict(cfg,llm_model='different-model'),{'ali_token':'fixture-manual-token'})
        assert not writes and not c.store.path.exists()
        assert c.store.config['llm_model']==cfg['llm_model']
        assert 'connection check' in c.window.settings_status.text()
    finally:release.set()
    wait_until(lambda:not c.service_tests)


def test_asr_check_blocks_recording_before_capture_or_microphone(controller,monkeypatch):
    from murmur import app as app_module
    c=controller;entered,release,finished,seen,states=install_check(c,monkeypatch)
    def forbidden(*args):pytest.fail('ASR checking must finish before a target or microphone is captured')
    monkeypatch.setattr(app_module.windows,'target',forbidden)
    monkeypatch.setattr(app_module,'Recorder',forbidden)
    cfg,secrets=c.window.service_test_values();c.test_service('asr',cfg,secrets)
    try:
        assert entered.wait(2)
        c.toggle()
        assert c.session is None
        assert 'speech recognition check' in c.window.home_status.text()
    finally:release.set()
    wait_until(lambda:not c.service_tests)

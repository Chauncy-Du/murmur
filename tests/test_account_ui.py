import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtWidgets import QApplication,QDialog
from PySide6.QtTest import QTest
from PySide6.QtGui import QFontDatabase
from murmur.profiles import ProfileRegistry
from murmur.account_ui import AccountDialog,public_profile
from murmur.account_manager import AccountManager
from murmur import storage,windows


@pytest.fixture
def app(monkeypatch):
    app=QApplication.instance() or QApplication([])
    for font in ('segoeui.ttf','segoeuib.ttf'):QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+font)
    monkeypatch.setattr(storage,'credential',lambda *args:'')
    monkeypatch.setattr(windows,'prepare_text_context',lambda:None)
    return app


def test_dialog_create_rename_and_sign_in_require_password(app,tmp_path):
    registry=ProfileRegistry(tmp_path);dialog=AccountDialog(registry,'default')
    dialog.new_name.setText('Work');dialog.new_username.setText('work');dialog.new_password.setText('test-password');dialog.confirm.setText('test-password')
    dialog.create_account();identifier=dialog.selected;assert dialog.result()==QDialog.Accepted
    edit=AccountDialog(registry,identifier);edit.edit_name.setText('Studio');edit.current_password.setText('wrong');edit.edit_account()
    assert edit.result()!=QDialog.Accepted and registry.get(identifier)['name']=='Work'
    edit.current_password.setText('test-password');edit.edit_account();assert registry.get(identifier)['name']=='Studio'
    login=AccountDialog(registry,identifier,startup=True);login.password.setText('wrong');login.sign_in();assert login.result()!=QDialog.Accepted
    login.password.setText('test-password');login.sign_in();assert login.result()==QDialog.Accepted
    for widget in (dialog,edit,login):widget.hide();widget.deleteLater()


def test_switch_replaces_store_and_preserves_old_history(app,tmp_path,monkeypatch):
    from murmur.app import Controller
    import murmur.account_manager as module
    registry=ProfileRegistry(tmp_path);new=registry.create('Work','work','test-password')
    original=storage.Store(tmp_path);original.profile=public_profile(registry.get('default'));original.config['demo']=True
    original.add('personal','听写','Private','Personal result',1,0,False)
    target=storage.Store(registry.folder(new['id']));target.config['demo']=True;target.save();target.db.close()
    monkeypatch.setattr(Controller,'preload_speech',lambda self:None)
    monkeypatch.setattr('murmur.dashboard.MainWindow.enable_saved_service_checks',lambda self:None)
    controller=Controller(app,original,False);manager=AccountManager(app,registry,controller,False)
    class Selection:
        selected=new['id']
        def __init__(self,*args):pass
        def exec(self):registry.activate(new['id'],'test-password');return QDialog.Accepted
    monkeypatch.setattr(module,'AccountDialog',Selection)
    try:
        manager.open_accounts()
        for _ in range(100):
            if not manager.busy:break
            QTest.qWait(10)
        active=manager.controller
        assert active is not controller and active.store.root==registry.folder(new['id'])
        assert active.store.rows()==[] and active.window.account_button.text()=='Work'
        check=storage.Store(tmp_path);assert check.rows()[0]['final']=='Personal result';check.db.close()
        active.quit(quit_app=False);active.store.db.close();active.window.hide()
    finally:storage.set_credential_scope('default')

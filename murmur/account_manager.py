"""Switch accounts without sharing stores, credentials or live microphones."""
from PySide6.QtCore import QObject,Signal,QTimer
from PySide6.QtWidgets import QDialog,QMessageBox,QProgressDialog
from .account_ui import AccountDialog,public_profile
from .storage import Store,set_credential_scope,profile_thread


class AccountManager(QObject):
    prepared=Signal(str)

    def __init__(self,app,registry,controller,listen=True):
        super().__init__(app);self.app=app;self.registry=registry;self.controller=controller;self.listen=listen;self.busy=False
        self.prepared.connect(self.finish_switch);self.bind(controller)

    def bind(self,controller):controller.window.account_requested.connect(self.open_accounts)

    def open_accounts(self):
        old=self.controller
        if self.busy:return
        if old.session or old.startup_busy or old.model_busy or old.service_tests or old.capture_busy or old.delivery:
            QMessageBox.information(old.window,'Local accounts','Finish the current task or connection check before switching accounts.');return
        identifier=old.store.profile['id'];dialog=AccountDialog(self.registry,identifier,old.window)
        if dialog.exec()!=QDialog.Accepted:return
        record=self.registry.get(dialog.selected)
        if record['id']==identifier:
            old.store.profile=public_profile(record);old.window.account_button.setText(record['name']);return
        # Open the destination first: file-access failures cannot discard the
        # current unlocked account or its live window.
        try:
            destination=Store(self.registry.folder(record['id']));destination.profile=public_profile(record)
        except Exception:
            self.registry.current=identifier;self.registry.save()
            QMessageBox.warning(old.window,'Local accounts','The account data could not be opened. Your current account is still active.');return
        self.busy=True;self.destination=destination;self.old=old;warm=old.warm_microphone
        old.quit(quit_app=False);old.window.hide()
        self.progress=QProgressDialog('Switching local account…','',0,0,None);self.progress.setCancelButton(None);self.progress.setWindowTitle('MurMur');self.progress.setMinimumDuration(0);self.progress.show()
        def prepare():
            if warm:warm.close()
            self.prepared.emit(record['id'])
        profile_thread(target=prepare,name='MurMur-account-switch',daemon=True).start()

    def finish_switch(self,identifier):
        from .app import Controller
        set_credential_scope(identifier)
        try:
            controller=Controller(self.app,self.destination,self.listen)
        except Exception:
            self.destination.db.close();set_credential_scope(self.old.store.profile['id'])
            self.registry.current=self.old.store.profile['id'];self.registry.save()
            controller=Controller(self.app,self.old.store,self.listen)
            QMessageBox.warning(controller.window,'Local accounts','Account setup failed; your previous account has been restored.')
        else:self.old.store.db.close()
        self.old.window.deleteLater();self.old.bubble.deleteLater();self.old.result_bubble.deleteLater();self.old.deleteLater()
        self.controller=controller;self.bind(controller);self.progress.close();self.progress.deleteLater();self.busy=False
        controller.show_main();controller.preload_speech();QTimer.singleShot(0,controller.window.enable_saved_service_checks)

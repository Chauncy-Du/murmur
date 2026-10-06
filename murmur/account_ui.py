"""Local account sign-in, creation and metadata editing."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QTabWidget,QWidget,QLineEdit,QComboBox,QLabel
from .ui import button,label,line_icon


def profile_label(record):return record['name']+' · '+record['username']


def public_profile(record):return {key:record[key] for key in ('id','name','username')}


class AccountDialog(QDialog):
    def __init__(self,registry,current,parent=None,startup=False):
        super().__init__(parent);self.registry=registry;self.current=current;self.selected=None
        self.setWindowTitle('MurMur · Local accounts');self.setFixedSize(460,410);self.setWindowFlag(Qt.WindowMaximizeButtonHint,False)
        body=QVBoxLayout(self);body.setContentsMargins(20,18,20,16);body.setSpacing(10)
        heading=QHBoxLayout();mark=QLabel();mark.setPixmap(line_icon('account',24,'#c7b8fa').pixmap(24,24));heading.addWidget(mark)
        title=label('Local accounts','title');title.setStyleSheet('font-size:21px;');heading.addWidget(title,1);body.addLayout(heading)
        note=label('Your configuration, API credentials and activity stay with each account.','muted');note.setWordWrap(True);body.addWidget(note)
        tabs=QTabWidget();body.addWidget(tabs,1)
        switch=QWidget();switch_body=QVBoxLayout(switch);switch_body.setContentsMargins(0,8,0,0);switch_body.setSpacing(8)
        self.accounts=QComboBox()
        for record in registry.records:self.accounts.addItem(profile_label(record),record['id'])
        self.accounts.setCurrentIndex(self.accounts.findData(current));switch_body.addWidget(self.accounts)
        self.password=QLineEdit();self.password.setEchoMode(QLineEdit.Password);self.password.setPlaceholderText('Password');self.password.setAccessibleName('Account password');switch_body.addWidget(self.password)
        self.login_hint=label('','muted');switch_body.addWidget(self.login_hint)
        switch_body.addStretch();self.unlock=button('Sign in' if startup else 'Use account',self.sign_in,True);switch_body.addWidget(self.unlock)
        self.accounts.currentIndexChanged.connect(self.selection_changed);self.password.returnPressed.connect(self.sign_in);tabs.addTab(switch,'Sign in')
        create=QWidget();form=QFormLayout(create);form.setContentsMargins(0,8,0,0);form.setSpacing(8)
        self.new_name=self.field(form,'Display name');self.new_username=self.field(form,'Account name')
        self.new_password=self.field(form,'Password',True);self.confirm=self.field(form,'Confirm password',True)
        form.addRow(button('Create account',self.create_account,True));tabs.addTab(create,'Create')
        if not startup:
            account=QWidget();edit=QFormLayout(account);edit.setContentsMargins(0,8,0,0);edit.setSpacing(8)
            record=registry.get(current)
            self.edit_name=self.field(edit,'Display name');self.edit_name.setText(record['name'])
            self.edit_username=self.field(edit,'Account name');self.edit_username.setText(record['username'])
            self.current_password=self.field(edit,'Current password',True);self.current_password.setEnabled(record['password'] is not None)
            self.change_password=self.field(edit,'New password',True);self.change_password.setPlaceholderText('Leave empty to keep password')
            self.change_confirm=self.field(edit,'Confirm password',True)
            edit.addRow(button('Save account',self.edit_account,True));tabs.addTab(account,'Account')
        self.notice=label('','muted');self.notice.setWordWrap(True);self.notice.setStyleSheet('font-size:11px;color:#ddb575;');body.addWidget(self.notice)
        privacy=label('On this PC only. Passwords lock app access; local files are not encrypted.','muted');privacy.setWordWrap(True);privacy.setStyleSheet('font-size:10px;');body.addWidget(privacy)
        self.selection_changed()

    @staticmethod
    def field(form,title,password=False):
        field=QLineEdit();field.setAccessibleName(title)
        if password:field.setEchoMode(QLineEdit.Password)
        form.addRow(title,field);return field

    def selection_changed(self):
        record=self.registry.get(self.accounts.currentData());locked=record['password'] is not None
        self.password.clear();self.password.setEnabled(locked)
        self.login_hint.setText('Password required' if locked else 'Existing personal data · No password set')
        self.notice.clear()

    def sign_in(self):
        try:
            identifier=self.accounts.currentData();self.registry.activate(identifier,self.password.text())
            self.selected=identifier;self.password.clear();self.accept()
        except (ValueError,OSError):self.notice.setText('Could not sign in. Check the password and local file access.')

    def create_account(self):
        try:
            if self.new_password.text()!=self.confirm.text():raise ValueError('Passwords do not match.')
            record=self.registry.create(self.new_name.text(),self.new_username.text(),self.new_password.text())
            self.registry.activate(record['id'],self.new_password.text());self.selected=record['id']
            self.new_password.clear();self.confirm.clear();self.accept()
        except ValueError as exc:self.notice.setText(str(exc))
        except OSError:self.notice.setText('Account could not be saved. Check local file access.')

    def edit_account(self):
        try:
            if self.change_password.text()!=self.change_confirm.text():raise ValueError('Passwords do not match.')
            self.registry.edit(self.current,self.edit_name.text(),self.edit_username.text(),self.current_password.text(),self.change_password.text())
            self.selected=self.current;self.current_password.clear();self.change_password.clear();self.change_confirm.clear();self.accept()
        except ValueError as exc:self.notice.setText(str(exc))
        except OSError:self.notice.setText('Account could not be saved. Check local file access.')

import json
import threading
import pytest
from murmur.profiles import ProfileRegistry
from murmur import storage


def test_legacy_profile_is_preserved_and_new_accounts_are_empty(tmp_path):
    registry=ProfileRegistry(tmp_path);original=storage.Store(tmp_path)
    original.add('old','听写','raw','final',1,0,False);original.config['llm_model']='private-model';original.save()
    new=registry.create('Work','work','test-password');registry.activate(new['id'],'test-password')
    account=storage.Store(registry.folder(new['id']))
    assert account.rows()==[] and account.config['llm_model']!='private-model'
    assert registry.folder('default')==tmp_path.resolve() and original.rows()[0]['final']=='final'
    assert 'test-password' not in registry.path.read_text('utf-8')
    loaded=ProfileRegistry(tmp_path);assert loaded.current==new['id']
    assert loaded.authenticate(new['id'],'test-password') and not loaded.authenticate(new['id'],'wrong')
    account.db.close();original.db.close()


def test_password_changes_require_old_password_and_invalid_edits_do_not_mutate(tmp_path):
    registry=ProfileRegistry(tmp_path);profile=registry.create('Work','work','test-password')
    with pytest.raises(ValueError):registry.edit(profile['id'],'Renamed','renamed','wrong','new-password')
    with pytest.raises(ValueError):registry.edit(profile['id'],'Renamed','renamed','test-password','short')
    assert profile['name']=='Work'
    registry.edit(profile['id'],'Renamed','renamed','test-password','new-password')
    assert not registry.authenticate(profile['id'],'test-password') and registry.authenticate(profile['id'],'new-password')
    with pytest.raises(ValueError):registry.create('Duplicate','RENAMED','test-password')


def test_invalid_registry_paths_fail_closed(tmp_path):
    payload={'current':'default','accounts':[{'id':'default','name':'Personal','username':'personal','password':None},
        {'id':'../outside','name':'Bad','username':'bad','password':None}]}
    source=json.dumps(payload);(tmp_path/'accounts.json').write_text(source,'utf-8')
    with pytest.raises(ValueError):ProfileRegistry(tmp_path)
    assert (tmp_path/'accounts.json').read_text('utf-8')==source


def test_worker_credentials_keep_original_namespace_after_switch(monkeypatch):
    from keyring.backends.Windows import WinVaultKeyring
    vault={}
    monkeypatch.setattr(WinVaultKeyring,'set_password',lambda self,service,name,value:vault.__setitem__((service,name),value))
    monkeypatch.setattr(WinVaultKeyring,'get_password',lambda self,service,name:vault.get((service,name)))
    entered=threading.Event();release=threading.Event();results=[]
    try:
        storage.set_credential_scope('default');storage.credential('llm','legacy-token')
        storage.set_credential_scope('a'*32);storage.credential('llm','account-a-token')
        def work():
            entered.set();release.wait(3);results.append(storage.credential('llm'))
            nested=storage.profile_thread(target=lambda:results.append(storage.credential('llm')));nested.start();nested.join()
        worker=storage.profile_thread(target=work);worker.start();assert entered.wait(3)
        storage.set_credential_scope('b'*32);storage.credential('llm','account-b-token');release.set();worker.join(3)
        assert results==['account-a-token','account-a-token'] and storage.credential('llm')=='account-b-token'
        storage.set_credential_scope('default');assert storage.credential('llm')=='legacy-token'
    finally:release.set();storage.set_credential_scope('default')

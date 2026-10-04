import json
from pathlib import Path

import pytest

from murmur import storage
from murmur.storage import DEFAULTS,Store,default_offline_model_dir,validated_config


@pytest.fixture(autouse=True)
def shared_model_root(tmp_path, monkeypatch):
    root = tmp_path / 'shared-models'
    monkeypatch.setattr(storage, 'DEFAULT_OFFLINE_MODELS_ROOT', root)
    return root


def test_new_profile_defaults_to_real_local_sensevoice(tmp_path):
    store=Store(tmp_path)
    try:
        assert store.config['asr_backend']=='offline'
        assert store.config['offline_engine']=='sensevoice'
        assert store.config['demo'] is False
        assert Path(store.config['offline_model_dir'])==tmp_path/'shared-models'/'sensevoice-small'
        assert store.config['dictation_key']==DEFAULTS['dictation_key']=='right_alt'
        assert store.config['translation_key']==DEFAULTS['translation_key']=='alt+shift'
        assert store.config['selection_key']==DEFAULTS['selection_key']=='alt+space'
        store.save()
        assert json.loads(store.path.read_text('utf-8'))['asr_backend']=='offline'
    finally:
        store.db.close()


@pytest.mark.parametrize('backend',['bailian','ali_nls','offline'])
@pytest.mark.parametrize('demo',[False,True])
def test_saved_backend_and_demo_choices_remain_explicit(backend,demo):
    config=validated_config(dict(asr_backend=backend,demo=demo,offline_engine='paraformer'))
    assert config['asr_backend']==backend
    assert config['demo'] is demo
    assert config['offline_engine']=='paraformer'


@pytest.mark.parametrize('engine,name',[('sensevoice','sensevoice-small'),('paraformer','paraformer-zh')])
@pytest.mark.parametrize('missing_path',[None,'','  '])
def test_missing_model_directory_follows_selected_engine(tmp_path,engine,name,missing_path):
    saved=dict(offline_engine=engine)
    if missing_path is not None:saved['offline_model_dir']=missing_path
    (tmp_path/'settings.json').write_text(json.dumps(saved),'utf-8')
    store=Store(tmp_path)
    try:
        assert Path(store.config['offline_model_dir'])==tmp_path/'shared-models'/name
        assert default_offline_model_dir(engine=engine)==tmp_path/'shared-models'/name
    finally:
        store.db.close()


@pytest.mark.parametrize('engine',['sensevoice','paraformer'])
def test_custom_model_directory_is_preserved(tmp_path,engine):
    custom=str(tmp_path/'custom-model')
    (tmp_path/'settings.json').write_text(json.dumps(dict(offline_engine=engine,offline_model_dir=custom)),'utf-8')
    store=Store(tmp_path)
    try:
        assert store.config['offline_model_dir']==custom
    finally:
        store.db.close()


@pytest.mark.parametrize('invalid',[None,True,1,[],{},'unknown','SenseVoice'])
def test_invalid_engine_defaults_to_sensevoice(invalid):
    assert validated_config(dict(offline_engine=invalid))['offline_engine']=='sensevoice'


def test_old_cloud_profile_keeps_other_preferences():
    saved=dict(asr_backend='bailian',demo=True,llm_url='https://custom.invalid/v1',llm_model='my-model',
        ollama=False,dictation_key='f8',translation_key='ctrl+shift+f9',selection_key='ctrl+shift+space',
        hotwords='User phrase',prompts={'听写':'Custom dictation prompt'})
    config=validated_config(saved)
    for key,value in saved.items():
        if key=='prompts':assert config[key]['听写']==value['听写']
        else:assert config[key]==value
    assert config['offline_engine']=='sensevoice'

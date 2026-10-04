import json
import pytest
from murmur.storage import Store

def test_invalid_json_recovers_backup_without_losing_history(tmp_path):
    s=Store(tmp_path);s.config['style']='My style';s.save();s.config['style']='Another style';s.save()
    s.add('kept','听写','raw','final',1,0,False);s.db.close()
    (tmp_path/'settings.json').write_text('{broken','utf-8')
    recovered=Store(tmp_path)
    assert recovered.config['style']=='My style'
    assert recovered.rows()[0]['session']=='kept'
    assert recovered.config_warning
    assert list(tmp_path.glob('settings-damaged-*.json'))

def test_invalid_fields_fall_back_to_safe_defaults(tmp_path):
    (tmp_path/'settings.json').write_text(json.dumps({'retention':-1,'demo':'false','bubble_width':900,'hotwords':None,'prompts':[]}),'utf-8')
    s=Store(tmp_path)
    assert s.config['retention']==90
    assert s.config['demo'] is False
    assert s.config['bubble_width']==168
    assert isinstance(s.config['hotwords'],str)
    assert isinstance(s.config['prompts'],dict)

def test_config_defaults_do_not_share_prompt_mutations(tmp_path):
    a=Store(tmp_path/'a');a.config['prompts']['听写']='custom'
    b=Store(tmp_path/'b');assert b.config['prompts']['听写']!='custom'


@pytest.mark.parametrize('url',('http://localhost:1234/v1','http://127.0.0.1:8000/v1','http://[::1]:8080/v1'))
def test_legacy_generic_local_model_stays_explicit(url):
    from murmur.storage import validated_config
    old=dict(ollama=False,llm_url=url,llm_model='custom:7b')
    migrated=validated_config(old)
    assert migrated['llm_model']=='custom:7b' and migrated['ollama_auto'] is False
    assert validated_config(dict(old,ollama_auto=True))['ollama_auto'] is True

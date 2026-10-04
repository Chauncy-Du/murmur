import csv
import json
import sqlite3

from murmur.storage import Store, validated_config


def test_ask_profile_defaults_and_online_migration():
    config=validated_config({})
    assert config['ask_key']=='right_alt+space'
    config=validated_config({'online_llm_url':'https://assistant.fixture.invalid/v1','online_llm_model':'saved-model'})
    assert config['ask_llm_url']=='https://assistant.fixture.invalid/v1' and config['ask_llm_model']=='saved-model'
    config=validated_config({'ollama':False,'llm_url':'https://legacy.fixture.invalid/v1','llm_model':'legacy-model'})
    assert config['ask_llm_url']=='https://legacy.fixture.invalid/v1' and config['ask_llm_model']=='legacy-model'
    config=validated_config({'online_llm_model':'online-model','ask_llm_model':'assistant-model','ask_key':'ctrl+shift+a'})
    assert config['ask_llm_model']=='assistant-model' and config['ask_key']=='ctrl+shift+a'
    assert validated_config({'ask_key':'invalid'})['ask_key']=='right_alt+space'
    assert validated_config({'ask_key':'disabled'})['ask_key']=='disabled'


def test_history_schema_migrates_once_and_preserves_old_data(tmp_path):
    db=sqlite3.connect(tmp_path/'history.db')
    db.execute('CREATE TABLE history(id INTEGER PRIMARY KEY, session TEXT UNIQUE, time TEXT, mode TEXT, raw TEXT, final TEXT, duration REAL, latency REAL, language TEXT, demo INTEGER, error TEXT, audio TEXT)')
    db.execute("INSERT INTO history VALUES(1,'old','2099-01-01T12:00:00','听写','old raw','old final',1,2,'英文',0,'','')")
    db.commit();db.close()
    store=Store(tmp_path);old=store.rows()[0]
    assert old['context']=='' and old['raw']=='old raw' and old['final']=='old final'
    store.db.close();store=Store(tmp_path)
    assert len(store.rows())==1 and store.rows()[0]['context']==''
    store.db.close()


def test_history_context_search_exports_and_general_add_compatibility(tmp_path):
    store=Store(tmp_path)
    store.add('ask','语音编辑','改写','result',2,1,False,context='selected source text')
    store.add('dictation','听写','normal','normal result',1,0,False)
    assert store.rows('selected source')[0]['session']=='ask'
    assert store.rows('normal')[0]['context']==''
    store.export(tmp_path/'history.csv')
    with (tmp_path/'history.csv').open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.DictReader(stream))
    assert next(row for row in rows if row['session']=='ask')['context']=='selected source text'
    store.export(tmp_path/'history.json')
    rows=json.loads((tmp_path/'history.json').read_text('utf-8'))
    assert next(row for row in rows if row['session']=='ask')['context']=='selected source text'
    store.config.update(ask_llm_model='assistant-saved',ask_key='ctrl+shift+a');store.save();store.db.close()
    restored=Store(tmp_path)
    assert restored.config['ask_llm_model']=='assistant-saved' and restored.config['ask_key']=='ctrl+shift+a'
    restored.db.close()

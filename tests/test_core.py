import copy
import threading
from datetime import datetime,timedelta
from murmur.storage import Store,DEFAULTS,language_of
from murmur.hotkeys import HotkeyMachine
from murmur.providers import transform,Recorder,DEMO_TEXT

def machine():return HotkeyMachine(copy.deepcopy(DEFAULTS))

def test_repeat_and_release():
    m=machine();assert m.feed('right_alt',True)=='pending';assert m.feed('right_alt',True) is None;assert m.feed('right_alt',False)=='release'

def test_altgr_both_orders():
    m=machine();m.feed('ctrl',True);assert m.feed('right_alt',True)=='altgr';assert m.feed('right_alt',False) is None
    m=machine();m.feed('right_alt',True);assert m.feed('ctrl',True)=='cancel'

def test_priority_and_left_alt():
    m=machine();assert m.feed('left_alt',True) is None;assert m.feed('shift',True)=='translation';assert m.feed('shift',False)=='release'
    m=machine();m.feed('right_alt',True);assert m.feed('space',True)=='ask';assert m.feed('right_alt',False)=='ask_release'

def test_chord_order():
    m=machine();m.feed('shift',True);assert m.feed('left_alt',True)=='translation'
    m=machine();m.feed('space',True);assert m.feed('left_alt',True)=='selection'

def test_other_chord_cancels():
    m=machine();m.feed('right_alt',True);assert m.feed('x',True)=='cancel'

def test_raw_and_rules():
    cfg=copy.deepcopy(DEFAULTS);cfg['polish']=False;cfg['rules']='百炼 => Bailian'
    assert transform('百炼是什么？','听写',cfg)=='Bailian是什么？'

def test_demo_cancellation():
    import pytest
    e=threading.Event();e.set()
    with pytest.raises(InterruptedError):transform('原文','润色',DEFAULTS,cancel=e)

def test_demo_recorder():
    cfg=copy.deepcopy(DEFAULTS);cfg['demo']=True
    r=Recorder(cfg,lambda text:None,lambda level:None,threading.Event());r.start();assert r.stop()==DEMO_TEXT

def test_history_search_export_delete(tmp_path):
    s=Store(tmp_path);s.add('s1','听写','原文','结果',2,1,True);s.add('s1','听写','重复','重复',1,1,True)
    assert len(s.rows())==1;assert s.rows('原文')[0]['final']=='结果'
    s.export(tmp_path/'history.json');s.export(tmp_path/'history.csv');assert '结果' in (tmp_path/'history.json').read_text('utf-8')
    s.delete([s.rows()[0]['id']]);assert not s.rows()

def test_retention_and_audio(tmp_path):
    s=Store(tmp_path);audio=tmp_path/'audio'/'one.wav';audio.parent.mkdir();audio.write_bytes(b'pcm')
    s.add('old','听写','原文','结果',1,1,False,audio=str(audio));s.db.execute('UPDATE history SET time=?',((datetime.now()-timedelta(days=100)).isoformat(),));s.db.commit();s.prune();assert not s.rows();assert not audio.exists()

def test_language():
    assert language_of('你好 Python')=='混合';assert language_of('你好')=='中文';assert language_of('123')=='未知'

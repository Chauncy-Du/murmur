from datetime import date
from murmur.insights import insights,analyze_vocabulary
from murmur.storage import Store

def row(day,text='测试 MurMur',duration=60,mode='听写'):
    return dict(time=day+'T10:00:00',raw=text,final=text,duration=duration,mode=mode,language='混合')

def test_activity_streak_and_scope():
    rows=[row('2026-10-01'),row('2026-10-02'),row('2026-10-03'),row('2026-10-04',mode='润色')]
    data=insights(rows,date(2026,10,4));assert data['active']==3;assert data['streak']==3;assert data['longest']==3;assert data['uses']==3;assert data['duration']==180

def test_vocabulary_evidence_and_existing():
    rows=[row('2026-10-01','COMSOL 模拟电极结构。'),row('2026-10-02','COMSOL 分析电极结构。')]
    words=analyze_vocabulary(rows,['COMSOL']);assert not any(w['word']=='COMSOL' for w in words);assert any(w['word']=='电极结构' for w in words);assert all(w['count']>=2 and w['example'] for w in words)

def test_dictionary_persistence(tmp_path):
    s=Store(tmp_path);s.add_word('COMSOL','分析');s.add_word('comsol','手动');assert len([w for w in s.words() if w['word'].casefold()=='comsol'])==1
    assert 'COMSOL' in s.config['hotwords'];s.delete_word('COMSOL');s.db.close();s=Store(tmp_path);assert not any(w['word']=='COMSOL' for w in s.words())

def test_dictionary_validation(tmp_path):
    import pytest
    s=Store(tmp_path)
    with pytest.raises(ValueError):s.add_word('bad\nterm')

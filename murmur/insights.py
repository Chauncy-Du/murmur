"""Local, deterministic insights. No history is sent to a cloud service."""
import re
from collections import Counter
from datetime import date,datetime,timedelta

STOPWORDS={'今天','我们','你们','他们','这个','那个','一个','可以','没有','就是','然后','因为','所以','已经','需要','进行','希望','什么','怎么','一下','时候','自己','但是','还是','现在','如果','觉得','知道','这样','这里','结果','文字','请把','the','and','for','with','this','that','from','have','will','your','you','are','was'}

def analyze_vocabulary(rows, existing=()):
    """Extract recurring Latin terms and Chinese collocations, with visible evidence."""
    existing={w.casefold() for w in existing};counts=Counter();sessions=Counter();examples={}
    for row in rows:
        text=row['raw'];tokens=re.findall(r'[A-Za-z][A-Za-z0-9_+.#-]{1,30}',text)
        for phrase in re.findall(r'[\u4e00-\u9fff]{2,}',text):
            for length in (2,3,4):
                tokens.extend(phrase[i:i+length] for i in range(len(phrase)-length+1))
        filtered=[t for t in tokens if t.casefold() not in STOPWORDS and t.casefold() not in existing]
        counts.update(filtered);sessions.update(set(filtered))
        for word in set(filtered):examples.setdefault(word,text[:180])
    suppressed=set()
    for longer,count in counts.items():
        if re.fullmatch(r'[\u4e00-\u9fff]{3,4}',longer):
            for size in range(2,len(longer)):
                for i in range(len(longer)-size+1):
                    shorter=longer[i:i+size]
                    if counts[shorter]<=count:suppressed.add(shorter)
    candidates=[]
    for word,count in counts.most_common():
        if count<2:continue
        # Avoid short Chinese fragments when an equally frequent longer phrase contains them.
        if word in suppressed:continue
        candidates.append(dict(word=word,count=count,sessions=sessions[word],example=examples[word]))
        if len(candidates)==30:break
    return candidates

def insights(rows,today=None):
    today=today or date.today();daily=Counter();languages=Counter()
    for row in rows:
        if row['mode'] not in ('听写','翻译'):continue
        daily[datetime.fromisoformat(row['time']).date()]+=1;languages[row['language']]+=1
    active=sorted(daily);longest=current=0;previous=None
    for day in active:
        current=current+1 if previous and day==previous+timedelta(days=1) else 1
        longest=max(longest,current);previous=day
    streak=0;cursor=today if today in daily else today-timedelta(days=1)
    while cursor in daily:streak+=1;cursor-=timedelta(days=1)
    spoken=[r for r in rows if r['mode'] in ('听写','翻译')]
    duration=sum(r['duration'] for r in spoken)
    characters=sum(sum(not c.isspace() for c in r['final']) for r in spoken)
    return dict(daily=daily,active=len(daily),longest=longest,streak=streak,characters=characters,duration=duration,speed=characters/(duration/60) if duration else 0,languages=languages,uses=len(spoken))

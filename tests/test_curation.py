import pytest
from datetime import timedelta
from briefing.core import now,iso,Settings
from briefing.config import load_settings,load_interests,CurationConfig
from briefing.collect import canonical
from briefing.curation import content_hash,simhash,similarity,deduplicate,cluster,score,novelty,passes,facts_signature,trends
from briefing.models import Article

def article(id='a',title='Ukraine government approved major election policy',text=None,**kw):
    text=text or 'The government approved a new policy after an election. '+('Legislators debated substantial reforms. '*30)
    obj=dict(id=id,url='https://example.com/'+id,canonical_url='https://example.com/'+id,title=title,source='test',source_id='s',published_at=iso(),fetched_at=iso(),text=text,word_count=len(text.split()),content_hash=content_hash(text),simhash=simhash(text),group=id,region='欧洲',category='政治',priority=5)
    obj.update(kw); return Article(**obj)

def test_url():
    assert canonical('HTTPS://Example.COM:443/a?utm_source=x&ref=abc&fbclid=x&gclid=y&z=2&a=1#frag')=='https://example.com/a?a=1&z=2'
    assert canonical('https://example.com/a?id=7')!='https://example.com/a?id=8'

def test_hash_similarity():
    assert content_hash(' A  B\nC')==content_hash('a b c')
    assert similarity('Ukraine election policy approved','Policy approved Ukraine election')==1
    assert similarity('Ukraine election','quantum physics')==0

def test_dedup_quality():
    cfg=load_interests(); a=article(priority=2); b=article('b',priority=5)
    assert deduplicate([a,b],cfg)==[b]
    b=article('b',text='Totally different body '*40,canonical_url=a.canonical_url)
    assert len(deduplicate([a,b],cfg))==1

def test_clusters_and_score():
    cfg=load_interests(); a=article(); b=article('b',title='Ukraine government approved election policy',text='Different detailed coverage '*100)
    groups=cluster([a,b],cfg)
    assert len(groups)==1 and len(groups[0].articles)==2
    g=score(groups[0],[],cfg)
    assert 0<=g.score<=100 and g.score==round(sum(g.dimensions.values()),2)
    assert g.dimensions['CrossSource']>0 and g.dimensions['Novelty']==20

def test_history_exact_and_update():
    cfg=load_interests(); a=article(); g=cluster([a],cfg)[0]
    history=[dict(fingerprint=g.id,titles=[a.title],urls=[a.canonical_url],hashes=[a.content_hash],facts=facts_signature(a.title,cfg))]
    assert novelty(g,history,cfg)[0]==0
    b=article(title=a.title+' 25 billion',text='New findings '*100)
    new=cluster([b],cfg)[0]
    n,update,_=novelty(new,history,cfg)
    assert n==.8 and not update  # signal requires editorial confirmation
    c=article(text='Rephrased with no new facts '*100)
    assert novelty(cluster([c],cfg)[0],history,cfg)[0]==.15

def test_rules():
    cfg=load_interests(); end=now()+timedelta(seconds=1); start=end-timedelta(days=1)
    assert passes(article(),cfg,start,end)
    assert not passes(article(title=''),cfg,start,end)
    assert not passes(article(text='short',priority=3),cfg,start,end)
    assert passes(article(text='Official short announcement of a substantial policy.',priority=5),cfg,start,end)
    assert not passes(article(published_at=iso(start-timedelta(seconds=1))),cfg,start,end)

def test_config(monkeypatch):
    monkeypatch.setenv('MAX_CANDIDATES','123'); monkeypatch.setenv('SMTP_PORT','587')
    assert load_settings().max_candidates==123 and load_settings().smtp_port==587
    monkeypatch.setenv('MAX_CANDIDATES','9999')
    with pytest.raises(ValueError): load_settings()
    obj=load_interests().model_dump(); obj['weights']['Depth']=10
    with pytest.raises(ValueError): CurationConfig.model_validate(obj)

def test_trends_need_events_days_updates():
    cfg=load_interests(); end=now(); topic=next(iter(cfg.topics))
    history=[dict(fingerprint=str(i),topic=topic,title=str(i),urls=['https://example.com/'+str(i)],sent_at=iso(end-timedelta(days=i)),kind='daily',update=i==1) for i in range(3)]
    assert len(trends(history,cfg,end))==1
    for h in history: h['update']=False
    assert trends(history,cfg,end)==[]

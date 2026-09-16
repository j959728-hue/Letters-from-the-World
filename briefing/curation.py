"""Deterministic, inspectable selection before any model call."""
import math
import re
from collections import Counter
from datetime import timedelta
from .collect import canonical
from .core import digest, parse_time
from .models import Article, StoryCluster

STOP=set('the a an and or of in on to for with as is are from by at has have says said new'.split())

def tokens(text):
    words=re.findall(r'[\u4e00-\u9fff]|[^\W_]+',text.lower())
    return set(w for w in words if w not in STOP)

def similarity(a,b):
    x,y=tokens(a),tokens(b)
    return len(x&y)/len(x|y) if x and y else 0

def content_hash(text):
    return digest(re.sub(r'\s+',' ',text).strip().lower())

def simhash(text):
    weights=[0]*64
    for token in tokens(text):
        n=int(digest(token)[:16],16)
        for i in range(64): weights[i]+=1 if n&(1<<i) else -1
    return f'{sum(1<<i for i,v in enumerate(weights) if v>0):016x}'

def from_snapshot(a,snap):
    text='\n'.join(b['text'] for b in snap['blocks'])
    return Article(id=a['id'],url=snap['final_url'],canonical_url=snap['canonical_url'],original_url=a['url'],
        title=snap['title'] or a['title'],source=a['source_name'],source_id=a['source_id'],author=snap['author'],
        published_at=snap['published'] or a['published'],fetched_at=snap['captured_at'],text=text,
        word_count=len(re.findall(r'[\u4e00-\u9fff]|[^\W_]+',text)),content_hash=content_hash(text),simhash=simhash(text),
        group=a.get('group') or a['source_id'],region=a['region'],category=a['category'],priority=a['priority'],blocks=snap['blocks'],snapshot=snap)

def topic_for(text,cfg):
    ranked=[(sum(k.lower() in text.lower() for k in keys),name) for name,keys in cfg.topics.items()]
    count,name=max(ranked,default=(0,'其他'))
    return name if count else '其他'

def prefilter(a,cfg,start,end):
    r=cfg.rules; title=a.get('title','').strip(); sid=a['source_id']
    if not title: return False
    if sid in r['deny_sources'] or (r['allow_sources'] and sid not in r['allow_sources']): return False
    if any(re.search(p,a['url'],re.I) for p in r['excluded_path_patterns']): return False
    if any(k.lower() in title.lower() for k in r['exclude_keywords']): return False
    if r['include_keywords'] and not any(k.lower() in title.lower() for k in r['include_keywords']): return False
    try: return start<=parse_time(a['published'])<end
    except (ValueError,KeyError): return False

def passes(a,cfg,start,end):
    if not prefilter(a.legacy(),cfg,start,end): return False
    r=cfg.rules
    minimum=r['important_min_chars'] if a.priority>=r['important_source_priority'] else r['min_text_chars']
    if len(a.text)<minimum: return False
    return not r['require_interest_match'] or topic_for(a.title+' '+a.text[:2000],cfg)!='其他'

def deduplicate(articles,cfg):
    kept=[]
    for a in sorted(articles,key=lambda a:(a.priority,a.word_count),reverse=True):
        duplicate=any(canonical(a.canonical_url)==canonical(b.canonical_url) or a.content_hash==b.content_hash or
            (similarity(a.title,b.title)>=cfg.rules['title_duplicate_similarity'] and
             similarity(a.text,b.text)>=cfg.rules['content_similarity']) or
            ((int(a.simhash,16)^int(b.simhash,16)).bit_count()<=3 and similarity(a.text,b.text)>=cfg.rules['content_similarity']) for b in kept)
        if not duplicate: kept.append(a)
    return kept

def cluster(articles,cfg):
    groups=[]
    for a in articles:
        group=next((g for g in groups if abs((parse_time(a.published_at)-parse_time(g.articles[0].published_at)).total_seconds())<=cfg.rules['max_cluster_hours']*3600
            and similarity(a.title,g.articles[0].title)>=cfg.rules['cluster_similarity']),None)
        if group: group.articles.append(a)
        else: groups.append(StoryCluster(id=digest(a.title.lower())[:20],topic=topic_for(a.title+' '+a.text[:1000],cfg),articles=[a],representative_article=a.id))
    return groups

def facts_signature(title,cfg):
    """Small signals only; LLM must confirm a meaningful update against the saved summary."""
    numbers=sorted(set(re.findall(r'\b\d+(?:[.,]\d+)*\b',title)))
    actions=sorted(k for k in cfg.rules['new_fact_terms'] if k.lower() in title.lower())
    return {'numbers':numbers[:20],'actions':actions[:12]}

def novelty(g,history,cfg):
    related=[h for h in history if h.get('kind','daily')=='daily' and (h['fingerprint']==g.id or
        any(similarity(a.title,t)>=cfg.rules['history_similarity'] for a in g.articles for t in h.get('titles',[])) or
        any(canonical(a.canonical_url) in h.get('urls',[]) for a in g.articles))]
    if not related: return 1.,False,'最近历史中未发现相同事件'
    old_hashes={x for h in related for x in h.get('hashes',[])}
    if all(a.content_hash in old_hashes for a in g.articles): return 0.,False,'正文与已发送记录相同'
    old_actions={x for h in related for x in h.get('facts',{}).get('actions',[])}
    old_numbers={x for h in related for x in h.get('facts',{}).get('numbers',[])}
    current=facts_signature(' '.join(a.title for a in g.articles),cfg)
    changed=bool(set(current['actions'])-old_actions or set(current['numbers'])-old_numbers)
    # Keep ambiguous changes at low rank for editorial review; never label a heuristic as a confirmed update.
    return (.8 if changed else .15),False,('疑似新进展，须模型对照历史确认' if changed else '相似事件，尚未发现明确新事实信号')

def score(g,history,cfg,weekly=False):
    s=cfg.scoring; text=' '.join(a.title for a in g.articles).lower()
    imp=min(1,s['base_importance']+sum(k.lower() in text for k in cfg.importance_signals['major'])*s['major_signal_bonus']+
            sum(k.lower() in text for k in cfg.importance_signals['substantial'])*s['substantial_signal_bonus'])
    nov,_,reason=novelty(g,history,cfg) if not weekly else (1,False,'周报重新汇总过去一周')
    reliable={a.group for a in g.articles if a.priority>=4}
    values={'Importance':imp,'Relevance':1 if g.topic!='其他' else s['no_interest_relevance'],'Novelty':nov,
        'SourceQuality':max(a.priority for a in g.articles)/5,'CrossSource':min(1,max(0,len(reliable)-1)/(s['cross_source_cap']-1)),
        'Depth':min(1,max(a.word_count for a in g.articles)/s['depth_words'])}
    g.dimensions={k:round(values[k]*w,2) for k,w in cfg.weights.items()}; g.score=round(sum(g.dimensions.values()),2)
    g.novelty_reason=reason
    return g

def trends(history,cfg,end):
    recent=[h for h in history if parse_time(h['sent_at'])>=end-timedelta(days=7)]
    result=[]
    for topic in cfg.topics:
        items=[h for h in recent if h['topic']==topic and h.get('kind')=='daily']
        events={h['fingerprint'] for h in items}; days={h['sent_at'][:10] for h in items}
        updates=sum(bool(h.get('update')) for h in items)
        if len(events)>=cfg.trend_min_events and len(days)>=cfg.trend_min_days and updates>=cfg.trend_min_updates:
            result.append({'topic':topic,'text':f'过去7天，{len(days)}天的简报收录了{len(events)}个独立事件，其中{updates}次有经编辑确认的新进展。此为持续观察线索，不推断因果。',
                'references':[{'title':h['title'],'url':h['urls'][0]} for h in items if h.get('urls')][:5]})
    return result[:cfg.max_trends]

def deep_reads(articles,cfg):
    results=[]
    for a in sorted(articles,key=lambda a:(a.priority,a.word_count),reverse=True):
        signals=[k for k in cfg.deep_read_signals if k.lower() in (a.title+' '+a.text[:500]).lower()]
        if a.word_count<cfg.deep_read_min_words or not signals: continue
        results.append({'title':a.title,'source':a.source,'url':a.canonical_url,'minutes':max(1,math.ceil(a.word_count/220)),
            'reason':'正文篇幅充足，包含深读线索：'+', '.join(signals[:3])+'。建议核对作者论证与原始材料。'})
        if len(results)>=cfg.deep_reads: break
    return results if cfg.deep_reads else []

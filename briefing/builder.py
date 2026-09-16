"""Shared one-shot pipeline for Actions and the existing local queue."""
import json
import logging
import math
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo
from .core import DATA, atomic_json, db, iso, now, sources, window, parse_time
from .collect import Browser, collect_source, canonical
from .curation import from_snapshot, prefilter, passes, deduplicate, cluster, score, trends, deep_reads, facts_signature, similarity
from .llm_client import BudgetExceeded
from .editor import Editor, validate_claims
from .publish import render
from .mailer import deliver
from .state import State

def build(s,cfg,kind='daily',end=None,dry_run=True,force=False,limit=None,persist_git=False,jid=None,collect_only=False):
    started=time.monotonic(); end=end or now(); jid=jid or uuid.uuid4().hex
    stats={'sources_checked':0,'candidates':0,'fetch_succeeded':0,'fetch_failed':0,'after_rules':0,'after_dedup':0,'story_clusters':0,'llm_candidates':0,'final_stories':0,'deep_reads':0,'email_sent':False}
    state=State(days=cfg.history_days,max_events=cfg.max_history_events,persist_git=persist_git)
    day=str(end.astimezone(ZoneInfo(s.timezone)).date()); key=kind+':'+day
    comparison_history=[h for h in state.history if not (force and h.get('kind')==kind and
        str(parse_time(h['sent_at']).astimezone(ZoneInfo(s.timezone)).date())==day)]
    if not dry_run and state.blocked(key) and not force:
        logging.info('[EMAIL] delivery already recorded: %s; no regeneration',key)
        return {'status':'already_recorded','delivery_id':key}
    try:
        editor=None if collect_only else Editor(s)
        active=sources(True)
        if not active: raise ValueError('No enabled sources')
        stats['sources_checked']=len(active); start,end=window(kind,end,s)
        logging.info('[FETCH] sources=%d',len(active))
        with ThreadPoolExecutor(max_workers=6) as executor:
            list(executor.map(lambda source:collect_source(source,s.max_per_source),[a for a in active if a['adapter']=='rss']))
        with Browser(s) as browser:
            for source in active:
                if source['adapter']=='page': collect_source(source,s.max_per_source,browser)
            ids={a['id'] for a in active}; source_by_id={a['id']:a for a in active}
            with db() as c:
                candidates=[json.loads(r['body']) for r in c.execute('SELECT body,source_id FROM articles WHERE published>=? AND published<? ORDER BY published DESC',(iso(start),iso(end))) if r['source_id'] in ids]
            if kind=='weekly':
                for record in state.history:
                    candidates.extend(a for a in record.get('articles',[]) if a['source_id'] in ids)
            buckets={}
            for a in candidates: buckets.setdefault(a['source_id'],[]).append(a)
            pool=[]; seen=set(); cap=min(limit or s.max_candidates,s.max_candidates)
            while buckets and len(pool)<cap:
                for sid in list(buckets):
                    if len(pool)>=cap: break
                    a=buckets[sid].pop(0); url=canonical(a['url'])
                    if url not in seen and prefilter(a,cfg,start,end): pool.append(a); seen.add(url)
                    if not buckets[sid]: del buckets[sid]
            stats['candidates']=len(pool); extracted=[]
            for index,a in enumerate(pool):
                page=None
                try:
                    page=browser.open(a['url'])
                    snap=browser.extract(page,a['id'],a['url'],source_by_id[a['source_id']].get('content_selector',''))
                    article=from_snapshot(a,snap); stats['fetch_succeeded']+=1
                    if passes(article,cfg,start,end): extracted.append(article)
                except Exception as exc:
                    stats['fetch_failed']+=1
                    logging.warning('[EXTRACT] article=%s error=%s',a['id'],type(exc).__name__)
                finally:
                    if page: page.close()
                if index%10==0: logging.info('[EXTRACT] completed=%d/%d',index+1,len(pool))
            stats['after_rules']=len(extracted); logging.info('[FILTER] remaining=%d',len(extracted))
            articles=deduplicate(extracted,cfg); stats['after_dedup']=len(articles)
            logging.info('[DEDUP] remaining=%d',len(articles))
            groups=[score(g,comparison_history,cfg,kind=='weekly') for g in cluster(articles,cfg)]
            stats['story_clusters']=len(groups); logging.info('[CLUSTER] count=%d',len(groups))
            groups=sorted((g for g in groups if g.score>=cfg.rules['minimum_score'] and g.dimensions['Novelty']>0),key=lambda g:g.score,reverse=True)
            shortlisted=groups[:cfg.llm_candidate_clusters]; stats['llm_candidates']=len(shortlisted)
            atomic_json(DATA/'jobs'/f'{jid}.scores.json',[{'id':g.id,'topic':g.topic,'score':g.score,'dimensions':g.dimensions,'novelty':g.novelty_reason,'titles':[a.title for a in g.articles]} for g in groups])
            logging.info('[SCORE] LLM candidates=%d',len(shortlisted))
            if collect_only:
                if not articles: raise ValueError('No readable articles; browser collection diagnostic failed')
                return {'status':'collected','stats':stats}
            if not shortlisted: raise ValueError('No eligible fresh events; refusing empty digest')
            maximum=s.weekly_limit if kind=='weekly' else s.daily_limit
            relevant=[h for h in comparison_history if any(h['fingerprint']==g.id or any(similarity(a.title,t)>=cfg.rules['history_similarity'] for a in g.articles for t in h.get('titles',[])) for g in shortlisted)]
            recent=[dict({k:h.get(k) for k in ('fingerprint','title','titles','sent_at','kind')},summary=h.get('summary','')[:500]) for h in relevant[-40:]]
            events=editor.select_clusters(shortlisted,kind,maximum+4,recent)
            bykey={g.id:g for g in shortlisted}; used=set(); accepted=[]; records=[]; read_candidates=[]; regions=Counter(); rejected=[]
            for event in events[:maximum+4]:
                if len(accepted)>=maximum: break
                g=bykey.get(event.event_key)
                if not g or g.id in used: continue
                used.add(g.id)
                available={a.id:a for a in g.articles[:4]}
                if any(aid not in available for aid in event.article_ids): continue
                rep=g.articles[0]
                if regions[rep.region]>=math.ceil(maximum*s.max_region_share): continue
                opened={}; snaps={}; refs=[]
                try:
                    for aid in dict.fromkeys(event.article_ids):
                        a=available[aid]
                        try:
                            page=browser.open(a.url); opened[aid]=page
                            snap=browser.extract(page,aid,a.original_url,source_by_id[a.source_id].get('content_selector',''))
                            fresh=from_snapshot(a.legacy(),snap)
                            if not passes(fresh,cfg,start,end): raise ValueError('Article no longer qualifies')
                            snaps[aid]=snap; refs.append(fresh.legacy())
                        except Exception as exc:
                            logging.warning('[EXTRACT] selected article=%s error=%s',aid,type(exc).__name__)
                            if aid in opened: opened.pop(aid).close()
                    if not refs: raise ValueError('No source evidence')
                    docs=[{'article_id':a['id'],'source':a['source_name'],'group':a['group'],'published':a['published'],'url':a['url'],'blocks':snaps[a['id']]['blocks']} for a in refs]
                    story=editor.write(event,docs,kind); validate_claims(story,snaps,refs)
                    evidence=[browser.capture(opened[c.article_id],snaps[c.article_id],c.block_id,c.quote) for c in story.core]
                    audit=editor.audit(story,docs,evidence,{'update':event.update,'reason':event.update_reason,'history':recent})
                    if not all((audit.approved,audit.all_core_supported,audit.screenshots_readable,audit.no_extra_facts)): raise ValueError('Evidence audit rejected')
                    # Only attach metadata to the edition; raw documents never enter committed state.
                    reference_keys=('id','source_id','source_name','title','url','published','author','canonical_url','group')
                    st=dict(story.model_dump(),event_key=g.id,region=rep.region,category=rep.category,importance=event.importance,
                        score=g.score,dimensions=g.dimensions,weights=cfg.weights,update=event.update and bool(event.update_reason),evidence=evidence,audit=audit.model_dump(),
                        references=[{k:a.get(k,'') for k in reference_keys} for a in refs])
                    if st['update']: st['title']='【更新】'+st['title']
                    accepted.append(st); regions[rep.region]+=1
                    atomic_json(DATA/'jobs'/f'{jid}.checkpoint.json',{'stories':accepted,'rejected':rejected})
                    read_candidates.extend(available[aid] for aid in available if aid in snaps)
                    records.append({'fingerprint':g.id,'delivery_id':key,'topic':g.topic,'title':st['title'],'titles':[a['title'][:300] for a in refs],
                        'urls':[canonical(a['canonical_url']) for a in refs],'hashes':[a['content_hash'] for a in refs],
                        'facts':facts_signature(' '.join(a['title'] for a in refs),cfg),'summary':' '.join(c['text'] for c in st['core'])[:900],
                        'sent_at':iso(end),'kind':kind,'update':st['update'],
                        'articles':[{k:a[k] for k in ('id','url','title','published','source_id','source_name','group','region','category','priority')} for a in refs]})
                    logging.info('[LLM] approved=%d calls=%d',len(accepted),editor.calls)
                except BudgetExceeded:
                    stats['budget_exhausted']=True
                    logging.warning('[LLM] budget reached; retain only fully audited stories')
                    break
                except Exception as exc:
                    rejected.append({'event_id':g.id,'error':type(exc).__name__})
                    logging.warning('[LLM] event=%s rejected error=%s',g.id,type(exc).__name__)
                    # Provider/budget failures are fatal, unlike a single article or editorial rejection.
                    if str(exc).startswith(('模型','LLM','请先')): raise
                finally:
                    for page in opened.values(): page.close()
        if len(accepted)<s.min_stories: raise ValueError('Too few evidence-approved stories')
        overview=''
        for st in accepted:
            sentence=st['core'][0]['text']
            if len(overview)+len(sentence)>400: break
            overview+=sentence+'\n'
        edition={'id':jid,'delivery_id':key,'kind':kind,'title':f'Daily Intelligence Brief · {day}' if kind=='daily' else f'Weekly Intelligence Brief · {day}',
            'created':iso(),'start':iso(start),'end':iso(end),'stories':accepted,'overview':overview.strip(),
            'trends':trends(state.history+records,cfg,end),'deep_reads':deep_reads(read_candidates,cfg),
            'history_records':records,'model':s.model,'model_usage':editor.usage,'rejected':rejected,'sample':False,
            'coverage':{'enabled':len(active),'successful':sum(x.get('health',{}).get('status')=='ok' for x in sources(True))}}
        render(edition); logging.info('[RENDER] EPUB + HTML ready id=%s',jid)
        with db() as c: c.execute('INSERT OR REPLACE INTO editions VALUES(?,?,?,?,?)',(jid,kind,iso(),json.dumps(edition,ensure_ascii=False),'ready'))
        stats.update(final_stories=len(accepted),deep_reads=len(edition['deep_reads']),llm_calls=editor.calls,
            llm_usage=editor.usage,token_budget_reserved=editor.reserved_tokens)
        if s.input_usd_per_million is not None and s.output_usd_per_million is not None:
            stats['estimated_cost_usd']=round(sum(u.get('input_tokens',0)*s.input_usd_per_million+u.get('output_tokens',0)*s.output_usd_per_million for u in editor.usage)/1_000_000,6)
        if not dry_run: stats['email_sent']=deliver(edition,s,state,force)=='smtp_accepted'
        return edition
    finally:
        stats['runtime_seconds']=round(time.monotonic()-started,1)
        atomic_json(DATA/'jobs'/f'{jid}.stats.json',stats)
        logging.info('[SUMMARY] %s',json.dumps(stats,ensure_ascii=False))

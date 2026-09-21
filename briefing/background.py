"""Find older, readable publisher articles related to weekly lead stories."""
import logging
from datetime import datetime, timezone
from urllib.parse import urlencode, urlparse

import feedparser

from .collect import fetch, public_url, canonical
from .core import digest, parse_time
from .curation import tokens


def publisher(url, sources):
    host=(urlparse(url).hostname or '').lower()
    for source in sources:
        site=(urlparse(source['url']).hostname or '').lower()
        if site and (host==site or host.endswith('.'+site)) and source['priority']>=4:
            return source
    return None


def historical_reads(stories, editor, browser, sources, start, minimum_words=700, maximum=4):
    """Search only for links; accept only opened, dated publisher originals."""
    if not stories or maximum<=0:
        return []
    try:
        plan=editor.background_queries(stories)
    except Exception as exc:
        logging.warning('[BACKGROUND] search plan error=%s',type(exc).__name__)
        return []
    cut=parse_time(start) if isinstance(start,str) else start.astimezone(timezone.utc)
    windows=[('2015-01-01','2021-01-01'),('2021-01-01',cut.date().isoformat())]
    result=[]; seen=set()
    for item in plan[:2]:
        if item.story_index>=min(2,len(stories)) or any(x in item.query for x in (':','/','\\')):
            continue
        for after,before in windows:
            if after>=before:
                continue
            query=f'{item.query} after:{after} before:{before}'
            url='https://news.google.com/rss/search?'+urlencode({'q':query,'hl':'en-US','gl':'US','ceid':'US:en'})
            try:
                raw,_=fetch(url)
                entries=feedparser.parse(raw).entries[:8]
            except Exception as exc:
                logging.warning('[BACKGROUND] discovery error=%s',type(exc).__name__)
                continue
            kept=0
            for entry in entries:
                if kept>=3 or len(result)>=maximum:
                    break
                link=entry.get('link','')
                if not link or link in seen:
                    continue
                seen.add(link)
                feed_source=entry.get('source') or {}
                publisher_hint=feed_source.get('href','') if isinstance(feed_source,dict) else ''
                if publisher_hint and not publisher(publisher_hint,sources):
                    continue
                page=None
                try:
                    public_url(link)
                    page=browser.open(link)
                    source=publisher(page.url,sources)
                    if not source:
                        continue
                    aid=digest(canonical(page.url))[:24]
                    snap=browser.extract(page,aid,page.url,source.get('content_selector',''))
                    published=snap['published']
                    if not published or not datetime(2015,1,1,tzinfo=timezone.utc)<=parse_time(published)<cut:
                        continue
                    body=' '.join(b['text'] for b in snap['blocks'])
                    words=len(body.split())
                    if words<minimum_words:
                        continue
                    # Require a meaningful link to the event/person, not just a broad category.
                    terms={t for t in tokens(item.query) if len(t)>2}
                    title_terms=tokens(snap['title'])
                    if terms and not terms.intersection(title_terms):
                        continue
                    final=canonical(snap['canonical_url'])
                    if final in {r['url'] for r in result}:
                        continue
                    result.append({'focus':stories[item.story_index]['title'],'title':snap['title'],
                                   'source':source['name'],'published':published,'url':final,
                                   'minutes':max(1,round(words/220)),'priority':source['priority'],
                                   'reason':'历史深读：对照本周事件，了解较早阶段的背景与相关人物；请留意报道当时的时间和视角。'})
                    kept+=1
                except Exception as exc:
                    logging.warning('[BACKGROUND] article error=%s',type(exc).__name__)
                finally:
                    if page:
                        page.close()
            if len(result)>=maximum:
                break
    result.sort(key=lambda item:(item['priority'],item['minutes']),reverse=True)
    for item in result:
        item.pop('priority')
    return result

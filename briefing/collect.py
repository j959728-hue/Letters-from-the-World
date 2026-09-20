import calendar
import os
import logging
import hashlib
import ipaddress
import json
import re
import socket
import time
from datetime import datetime, timezone
from functools import lru_cache
from html.parser import HTMLParser
from urllib.parse import urlparse, urljoin, urlunparse, parse_qsl, urlencode

import feedparser
import httpx
from playwright.sync_api import sync_playwright

from .core import DATA, Settings, db, digest, iso, parse_time, now, health

USER_AGENT = 'KindleBriefing/0.1 (personal RSS reader; evidence capture)'

GATED_MARKERS = ('subscribe to continue', 'subscribe to read', 'subscription required',
                 'exclusive to subscribers', 'this article is for subscribers',
                 'already a subscriber')

def publisher_alternate(current_url, href):
    """Use only an alternate that the publisher links on its own hostname."""
    if not href: return None
    target=urljoin(current_url,href)
    if urlparse(target).hostname!=urlparse(current_url).hostname: return None
    public_url(target)
    return target if canonical(target)!=canonical(current_url) else None

class SourceAddressBlocked(ValueError): pass
class AccessRestricted(ValueError): pass

def canonical(url):
    p=urlparse(url)
    query=sorted((k,v) for k,v in parse_qsl(p.query,keep_blank_values=True) if not k.lower().startswith('utm_') and k.lower() not in ('ref','fbclid','gclid'))
    host=p.netloc.lower()
    if (p.scheme.lower()=='https' and host.endswith(':443')) or (p.scheme.lower()=='http' and host.endswith(':80')): host=host.rsplit(':',1)[0]
    return urlunparse((p.scheme.lower(),host,p.path or '/',p.params,urlencode(query),''))

@lru_cache(maxsize=1024)
def public_url(url):
    p=urlparse(url)
    if p.scheme not in ('https','http') or not p.hostname or p.username or p.password:
        raise ValueError('只允许公开 http/https 来源')
    addresses=socket.getaddrinfo(p.hostname,p.port or (443 if p.scheme=='https' else 80),type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise SourceAddressBlocked('不允许采集本地、内网或保留地址')
    return url

def fetch(url):
    with httpx.Client(timeout=30, headers={'User-Agent':USER_AGENT}, follow_redirects=False) as client:
        for _ in range(6):
            public_url(url)
            with client.stream('GET',url) as r:
                if r.is_redirect:
                    url=urljoin(url,r.headers['location']); continue
                r.raise_for_status()
                data=bytearray()
                for chunk in r.iter_bytes():
                    data.extend(chunk)
                    if len(data)>5_000_000:
                        raise ValueError('来源超过采集大小上限')
                return bytes(data),url
    raise ValueError('跳转次数超限')

class FeedLinks(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='link' and 'alternate' in a.get('rel','') and ('rss' in a.get('type','') or 'atom' in a.get('type','')):
            self.links.append(a.get('href',''))

def discover_feed(url):
    body,final=fetch(url)
    parsed=feedparser.parse(body)
    if parsed.entries:
        return final,parsed
    parser=FeedLinks(); parser.feed(body.decode('utf-8',errors='replace'))
    for link in parser.links[:4]:
        try:
            target=urljoin(final,link)
            raw,resolved=fetch(target); feed=feedparser.parse(raw)
            if feed.entries: return resolved,feed
        except Exception:
            continue
    raise ValueError('未发现可用 RSS/Atom；请填写订阅地址或选择网页适配器')

def published(entry):
    # Unknown dates stay unknown; never substitute fetch time for publication time.
    t=entry.get('published_parsed') or entry.get('updated_parsed')
    return iso(datetime.fromtimestamp(calendar.timegm(t),timezone.utc)) if t else ''

def store_article(article):
    article['id']=digest(canonical(article['url']))[:24]
    article['url']=canonical(article['url'])
    if not article.get('published'):
        return None
    pub=parse_time(article['published'])
    if pub>now()+__import__('datetime').timedelta(minutes=15):
        return None
    with db() as c:
        c.execute('INSERT INTO articles VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,published=excluded.published,body=excluded.body',
                  (article['id'],article['source_id'],article['url'],article['title'],iso(pub),iso(),json.dumps(article,ensure_ascii=False)))
    return article

class Browser:
    def __init__(self,settings=None):
        self.s=settings or Settings()

    def __enter__(self):
        self.pw=sync_playwright().start()
        try:
            self.browser=self.pw.chromium.launch(headless=True)
        except Exception:
            if os.name!='nt':
                self.pw.stop()
                raise
            # A fresh, isolated profile; never reuse the user's browser profile.
            self.browser=self.pw.chromium.launch(headless=True,channel='msedge')
        self.context=self.browser.new_context(viewport={'width':720,'height':1000},device_scale_factor=1.5,locale='en-US',service_workers='block')
        def route_handler(route):
            try:
                if route.request.resource_type in ('media','font'):
                    return route.abort()
                public_url(route.request.url)
                return route.continue_()
            except Exception:
                return route.abort()
        self.context.route('**/*',route_handler)
        return self

    def __exit__(self,*args):
        self.context.close(); self.browser.close(); self.pw.stop()

    def open(self,url):
        public_url(url)
        page=self.context.new_page()
        try:
            response=page.goto(url,wait_until='domcontentloaded',timeout=self.s.fetch_timeout_ms)
            if response and response.status>=400:
                raise ValueError(f'原文返回 HTTP {response.status}')
            page.wait_for_function("() => !!document.body && document.body.innerText.length > 35",timeout=self.s.body_wait_ms)
            body=page.locator('body').inner_text()[:1600].lower()
            main=page.locator('article,main,[role="main"]').first
            visible=main.inner_text() if main.count() else body
            if len(visible.strip())<500 and any(marker in body for marker in GATED_MARKERS):
                alternate=page.locator('link[rel="amphtml"]').first
                target=publisher_alternate(page.url,alternate.get_attribute('href') if alternate.count() else '')
                if not target: raise AccessRestricted('订阅页面未提供同站公开版本；跳过受限原文')
                response=page.goto(target,wait_until='domcontentloaded',timeout=self.s.fetch_timeout_ms)
                if response and response.status>=400: raise ValueError('出版社替代页面不可访问')
                page.wait_for_function("() => !!document.body && document.body.innerText.length > 35",timeout=self.s.body_wait_ms)
                alternate_body=page.locator('body').inner_text()[:1600].lower()
                alternate_main=page.locator('article,main,[role="main"]').first
                alternate_visible=alternate_main.inner_text() if alternate_main.count() else alternate_body
                if len(alternate_visible.strip())<500 and any(marker in alternate_body for marker in GATED_MARKERS):
                    raise AccessRestricted('出版社替代页面仍需订阅；跳过受限原文')
            for _ in range(self.s.scroll_steps):
                page.evaluate('window.scrollBy(0, window.innerHeight)')
                page.wait_for_timeout(250)
            public_url(page.url)
            return page
        except Exception:
            page.close(); raise

    def extract(self,page,aid,url,selector=''):
        page.wait_for_function('''selector => {
          const root=document.querySelector(selector || 'article,main,[role="main"]') || document.body;
          return Array.from(root.querySelectorAll('p,li')).some(e=>e.innerText.trim().length>=35);
        }''',arg=selector,timeout=self.s.body_wait_ms)
        blocked=page.locator('body').inner_text()[:600].lower()
        if any(x in blocked for x in ('verify you are human','checking your browser','access denied','just a moment...')):
            raise ValueError('页面验证或访问限制，未取得原文')
        blocks=page.locator('p, h1, h2, h3, li').evaluate_all('''(els, selector) => {
          const roots=Array.from(document.querySelectorAll(selector || 'article, main, [role="main"]'));
          const root=roots.sort((a,b)=>b.innerText.length-a.innerText.length)[0] || document.body;
          return els.map((e,i)=>({id:i,text:(e.innerText||'').replace(/\\s+/g,' ').trim(),
            keep:root.contains(e) && !e.closest('nav,footer,aside,form,[role="navigation"],[role="dialog"],.comments,.related,.advertisement,[aria-hidden="true"]') && !!(e.getClientRects().length && getComputedStyle(e).visibility!=='hidden')}))
            .filter(e=>e.keep && e.text.length>=20 && e.text.length<=2600).slice(0,320);
        }''',selector)
        kept=[]; chars=0
        for b in blocks:
            if chars+len(b['text'])>self.s.max_text_chars: break
            kept.append({'id':b['id'],'text':b['text']}); chars+=len(b['text'])
        blocks=kept
        if sum(len(b['text']) for b in blocks)<35:
            raise ValueError('可读原文不足；不能仅凭搜索片段生成新闻')
        date=page.locator('meta[property="article:published_time"],meta[name="date"],meta[name="pubdate"]').first
        pub=date.get_attribute('content') if date.count() else ''
        if not pub:
            node=page.locator('time[datetime]').first
            pub=node.get_attribute('datetime') if node.count() else ''
        try: pub=iso(parse_time(pub)) if pub else ''
        except ValueError: pub=''
        meta=page.evaluate('''() => {
          const m=s=>document.querySelector(s)?.content || '';
          const ld=Array.from(document.querySelectorAll('script[type="application/ld+json"]')).flatMap(e=>{try {const x=JSON.parse(e.textContent);return Array.isArray(x)?x:(x['@graph']||[x]);}catch{return [];}}).find(x=>/Article|Posting/.test(x['@type'])) || {};
          let author=ld.author; if(Array.isArray(author)) author=author.map(x=>x.name||'').join(', '); else if(typeof author==='object') author=author?.name;
          return {title:m('meta[property="og:title"]')||ld.headline||document.querySelector('h1')?.innerText||document.title,
            author:m('meta[name="author"]')||author||'',canonical_url:document.querySelector('link[rel="canonical"]')?.href||location.href,
            date:ld.datePublished||''}; }''')
        if not pub and meta['date']:
            try: pub=iso(parse_time(meta['date']))
            except ValueError: pass
        target=canonical(meta['canonical_url'])
        # A cross-domain canonical can be syndication or malicious; retain the actual page URL.
        if urlparse(target).hostname!=urlparse(page.url).hostname: target=canonical(page.url)
        snap={'article_id':aid,'url':url,'final_url':page.url,'captured_at':iso(),
              'title':meta['title'],'author':meta['author'],'canonical_url':target,'published':pub,'blocks':blocks}
        raw=page.content()
        snap['html_sha256']=digest(raw)
        folder=DATA/'evidence'/aid; folder.mkdir(parents=True,exist_ok=True)
        (folder/'source.html').write_text(raw,encoding='utf-8')
        with db() as c:
            c.execute('INSERT OR REPLACE INTO snapshots VALUES(?,?)',(aid,json.dumps(snap,ensure_ascii=False)))
        return snap

    def capture(self,page,snapshot,block_id,quote):
        block=next((b for b in snapshot['blocks'] if b['id']==block_id),None)
        norm=lambda s: re.sub(r'\s+',' ',s).strip()
        if not block or len(quote.strip())<12 or norm(quote) not in norm(block['text']):
            raise ValueError('证据引文不在选定原文段落中')
        node=page.locator('p, h1, h2, h3, li').nth(block_id)
        if norm(quote) not in norm(node.inner_text()):
            raise ValueError('页面已变化，截图与引文不匹配')
        node.scroll_into_view_if_needed()
        box=node.bounding_box()
        if not box or box['width']<100 or box['height']>1800:
            raise ValueError('证据段落不适合可读截图；请缩小证据范围')
        path=DATA/'evidence'/snapshot['article_id']/f'block-{block_id}-{__import__("uuid").uuid4().hex[:12]}.png'
        # Native screenshot of the original DOM element; no reconstructed text or highlight overlays.
        node.screenshot(path=str(path),timeout=15000)
        return {'article_id':snapshot['article_id'],'block_id':block_id,'quote':quote,
                'image':str(path.relative_to(DATA)).replace('\\','/'),'url':snapshot['url'],
                'final_url':snapshot['final_url'],'captured_at':iso(),'html_sha256':snapshot['html_sha256'],
                'image_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def collect_source(source,limit=12,browser=None):
    sid=source['id']; articles=[]; undated=0
    try:
        if source['adapter']=='manual':
            health(sid,status='manual',message='等待手动加入文章'); return []
        if source['adapter']=='rss':
            feed_url,feed=discover_feed(source['feed_url'] or source['url'])
            for entry in feed.entries[:limit*3]:
                pub=published(entry)
                if not pub: undated+=1; continue
                if not entry.get('link'): continue
                a=store_article({'source_id':sid,'url':entry.link,'title':entry.get('title','未命名'),
                      'published':pub,'summary':re.sub('<[^>]+>',' ',entry.get('summary',''))[:1800],
                      'source_name':source['name'],'region':source['region'],'category':source['category'],
                      'group':source.get('group') or urlparse(source['url']).hostname,'priority':source['priority']})
                if a: articles.append(a)
                if len(articles)>=limit: break
            health(sid,status='ok',count=len(articles),undated=undated,feed_url=feed_url)
        else:
            if browser is None: raise ValueError('网页适配器需要浏览器')
            page=browser.open(source['url'])
            try:
                links=page.locator(source['link_selector']).evaluate_all('els=>els.map(e=>({url:e.href,title:e.innerText}))')
            finally: page.close()
            seen=set()
            for item in links:
                if item['url'] in seen or not item['title'].strip(): continue
                seen.add(item['url'])
                if len(seen)>min(limit,6): break
                try:
                    p=browser.open(item['url']); aid=digest(canonical(item['url']))[:24]
                    try: snap=browser.extract(p,aid,item['url'])
                    finally: p.close()
                    if not snap['published']: undated+=1; continue
                    a=store_article({'source_id':sid,'url':item['url'],'title':item['title'][:300],'published':snap['published'],
                        'summary':' '.join(b['text'] for b in snap['blocks'][:3])[:1800],
                        'source_name':source['name'],'region':source['region'],'category':source['category'],
                        'group':source.get('group') or urlparse(source['url']).hostname,'priority':source['priority']})
                    if a: articles.append(a)
                except Exception as e:
                    logging.warning('[EXTRACT] source=%s error=%s',sid,type(e).__name__)
                    continue
            if not articles: raise ValueError('未取得带明确发布时间的文章；检查链接选择器或使用 RSS')
            health(sid,status='ok',count=len(articles),undated=undated)
        return articles
    except Exception as e:
        logging.error('[FETCH] source=%s error=%s',sid,type(e).__name__)
        health(sid,status='error',message=type(e).__name__); return []

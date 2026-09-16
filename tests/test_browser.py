"""Real browser integration; uses an isolated local server, no remote news or model."""
import os
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse
import pytest
from briefing.core import Settings,iso,DATA,now
from briefing.collect import Browser
from briefing.curation import from_snapshot

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='Opt-in real Chromium integration')

def test_dynamic_body_metadata_and_native_screenshot(monkeypatch):
    text='The research team released its detailed findings after three years of experiments. '+('Researchers described the methods and limits of their analysis. '*5)
    publication=iso(now()-timedelta(minutes=1))
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body=f'''<html><head><title>Fixture</title><meta name="author" content="Fixture Author"><meta property="article:published_time" content="{publication}"><link rel="canonical" href="/canonical?utm_source=test"></head><body><nav><p>Navigation advertisement should not enter the article text at all.</p></nav><main><h1>Research findings released</h1><div id="dynamic"></div></main><footer><p>Footer advertising should not enter the article text at all.</p></footer><script>setTimeout(()=>{{document.querySelector('#dynamic').innerHTML='<p>{text}</p>'}},200)</script></body></html>'''.encode()
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.end_headers(); self.wfile.write(body)
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    url=f'http://127.0.0.1:{server.server_port}/article'
    # Allow only this test server. Production public_url rejects loopback.
    original=__import__('briefing.collect',fromlist=['public_url']).public_url
    def local_only(u):
        p=urlparse(u)
        if p.hostname=='127.0.0.1' and p.port==server.server_port: return u
        return original(u)
    monkeypatch.setattr('briefing.collect.public_url',local_only)
    try:
        with Browser(Settings(scroll_steps=1)) as browser:
            page=browser.open(url)
            try:
                snap=browser.extract(page,'browser-fixture',url)
                assert snap['author']=='Fixture Author' and snap['published']
                assert snap['canonical_url'].endswith('/canonical')
                body=' '.join(b['text'] for b in snap['blocks'])
                assert 'Navigation' not in body and 'Footer' not in body
                assert text.strip() in body
                block=next(b for b in snap['blocks'] if 'research team' in b['text'])
                e=browser.capture(page,snap,block['id'],'The research team released its detailed findings')
                assert (DATA/e['image']).stat().st_size>100
            finally: page.close()
        # Exercise the entire shared builder with real browser/rendering and a deterministic test editor.
        # This verifies integration, not live model quality or SMTP delivery.
        from briefing import builder
        from briefing.config import load_interests
        from briefing.editor import Event,Story,Claim,Audit
        from briefing.collect import store_article
        source=dict(id='fixture-source',name='fixture',adapter='rss',enabled=True,health={'status':'ok'})
        monkeypatch.setattr(builder,'sources',lambda enabled=False:[source])
        def collect(source,limit):
            return [store_article(dict(source_id=source['id'],url=url,title='Research findings released',published=publication,source_name='fixture',region='全球',category='科学',group='fixture',priority=5))]
        monkeypatch.setattr(builder,'collect_source',collect)
        class FixtureEditor:
            def __init__(self,s): self.calls=0; self.usage=[]; self.reserved_tokens=0
            def select_clusters(self,groups,kind,limit,recent):
                g=groups[0]; return [Event(event_key=g.id,title=g.articles[0].title,region='全球',category='科学',importance=5,article_ids=[g.articles[0].id])]
            def write(self,event,docs,kind):
                block=next(b for b in docs[0]['blocks'] if 'research team' in b['text'])
                return Story(title='自动化集成测试样例',basis='单一来源报道',core=[Claim(text='测试材料称研究团队在三年实验后发布详细结果。',article_id=docs[0]['article_id'],block_id=block['id'],quote='The research team released its detailed findings')],why_it_matters='测试说明',watch_next='测试问题',uncertainty='',timeline=[])
            def audit(self,*args): return Audit(approved=True,all_core_supported=True,screenshots_readable=True,no_extra_facts=True,issues=[])
        monkeypatch.setattr(builder,'Editor',FixtureEditor)
        result=builder.build(Settings(min_stories=1,scroll_steps=1),load_interests(),dry_run=True,limit=1)
        assert len(result['stories'])==1 and (DATA/'editions'/result['id']/'briefing.epub').exists()
        assert not (DATA/'state.json').exists(), 'dry-run must not mark history as sent'
        from briefing.state import State
        history=State(); history.body['history']=result['history_records']; history.save()
        with pytest.raises(ValueError,match='No eligible fresh events'):
            builder.build(Settings(min_stories=1,scroll_steps=1),load_interests(),dry_run=True,limit=1)
        forced=builder.build(Settings(min_stories=1,scroll_steps=1),load_interests(),dry_run=True,force=True,limit=1)
        assert len(forced['stories'])==1, '--force must allow today\'s already sent content to be regenerated'
    finally: server.shutdown(); server.server_close()

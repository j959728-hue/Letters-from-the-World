from types import SimpleNamespace

from briefing import background
from briefing.publish import extras_html


def test_weekly_background_requires_old_original_article(monkeypatch):
    feed=b'''<rss version="2.0"><channel><item><title>Iran conflict explained</title><link>https://news.google.com/rss/articles/fixture</link></item></channel></rss>'''
    monkeypatch.setattr(background,'fetch',lambda url:(feed,url))
    monkeypatch.setattr(background,'public_url',lambda url:url)
    editor=SimpleNamespace(background_queries=lambda stories:[SimpleNamespace(story_index=0,query='Iran conflict')])

    class Page:
        url='https://www.reuters.com/world/iran-conflict-explained/'
        def close(self): pass

    class Browser:
        def open(self,url): return Page()
        def extract(self,page,aid,url,selector):
            return {'title':'Iran conflict explained','published':'2020-01-10T00:00:00+00:00',
                    'canonical_url':page.url,'blocks':[{'text':'Iran conflict history and context ' * 5}]}

    sources=[{'url':'https://www.reuters.com/','name':'Reuters','priority':5}]
    reads=background.historical_reads([{'title':'Iran conflict this week'}],editor,Browser(),sources,
                                      '2026-09-14T00:00:00+00:00',minimum_words=5)
    assert len(reads)==1
    assert reads[0]['source']=='Reuters'
    assert reads[0]['published'][:10]=='2020-01-10'
    assert reads[0]['url'].startswith('https://www.reuters.com/')


def test_weekly_background_rejects_aggregator(monkeypatch):
    feed=b'''<rss version="2.0"><channel><item><title>Iran conflict explained</title><link>https://news.google.com/rss/articles/fixture</link></item></channel></rss>'''
    monkeypatch.setattr(background,'fetch',lambda url:(feed,url))
    monkeypatch.setattr(background,'public_url',lambda url:url)
    editor=SimpleNamespace(background_queries=lambda stories:[SimpleNamespace(story_index=0,query='Iran conflict')])

    class Page:
        url='https://news.google.com/rss/articles/fixture'
        def close(self): pass

    browser=SimpleNamespace(open=lambda url:Page())
    reads=background.historical_reads([{'title':'Iran conflict this week'}],editor,browser,
                                      [{'url':'https://www.reuters.com/','name':'Reuters','priority':5}],
                                      '2026-09-14T00:00:00+00:00',minimum_words=5)
    assert reads==[]


def test_weekly_reading_guide_is_chronological():
    older={'focus':'伊朗局势','title':'较早报道','source':'Reuters','published':'2018-01-01',
           'url':'https://www.reuters.com/old','minutes':8}
    newer={**older,'title':'较晚报道','published':'2022-01-01','url':'https://www.reuters.com/new'}
    html=extras_html({'kind':'weekly','background_reads':[newer,older]})
    assert html.index('较早报道') < html.index('较晚报道')
    assert '2018-01-01' in html and 'https://www.reuters.com/old' in html

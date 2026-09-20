import hashlib
import json
import re
import smtplib
import ssl
import zipfile
from email.message import EmailMessage
from email.policy import SMTP
from html import escape
from pathlib import Path
from xml.etree import ElementTree as ET

from .core import DATA, db, iso, secret

CSS='''
body{font-family:serif;line-height:1.7;color:#111;background:white;margin:5%;}
h1{font-size:1.7em;line-height:1.3;}h2{font-size:1.3em;line-height:1.4;}
.meta,.caption{font-size:.82em;color:#444;line-height:1.5;}
.label{font-size:.8em;border-bottom:1px solid #888;padding-bottom:.4em;}
.cover{padding-top:10%;page-break-after:always;}article{page-break-before:always;}
p{orphans:2;widows:2;}figure{margin:1em 0;page-break-inside:avoid;}
img{max-width:100%;height:auto;display:block;}a{color:#222;text-decoration:underline;overflow-wrap:anywhere;}
.sources{border-top:1px solid #aaa;margin-top:1.5em;padding-top:.8em;font-size:.85em;word-wrap:break-word;}
.core{font-size:1.05em;}blockquote{margin:.6em 0;padding-left:.8em;border-left:2px solid #bbb;}
'''

def esc(s):
    return escape(re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',str(s)),quote=True)

def verify_evidence(stories):
    for story in stories:
        if len(story['core'])!=len(story['evidence']):
            raise ValueError('每条核心信息都必须有对应截图')
        for claim,e in zip(story['core'],story['evidence']):
            if claim['article_id']!=e['article_id'] or claim['block_id']!=e['block_id'] or claim['quote']!=e['quote']:
                raise ValueError('截图与核心信息映射错误')
            p=(DATA/e['image']).resolve()
            if not p.is_relative_to(DATA) or not p.is_file() or p.suffix!='.png':
                raise ValueError('证据截图不存在')
            if hashlib.sha256(p.read_bytes()).hexdigest()!=e['image_sha256']:
                raise ValueError('证据截图完整性校验失败')

def story_html(story,number,image_links):
    title=esc(story['title'])
    parts=[f'<article id="s{number}"><p class="label">{esc(story["region"])} · {esc(story["category"])} · {esc(story["basis"])}</p><h2>{number}. {title}</h2>']
    if story.get('dimensions'):
        ratings=[]
        for key,label in [('Importance','重要性'),('Relevance','兴趣'),('Novelty','新颖性')]:
            stars=round(5*story['dimensions'][key]/max(1,story['weights'][key]))
            ratings.append(label+'：'+'★'*stars+'☆'*(5-stars))
        parts.append('<p class="meta">'+esc(' · '.join(ratings))+f' · 规则评分 {story["score"]}/100</p>')
    for i,claim in enumerate(story['core']):
        e=story['evidence'][i]
        parts.append(f'<p class="core">{esc(claim["text"])}</p><figure><img src="{esc(image_links[i])}" alt="原始来源关键段落截图"/><figcaption class="caption">证据 {i+1} · 原网页段落截图 · 截图时间 {esc(e["captured_at"])}<br/>来源域名：{esc(__import__("urllib.parse",fromlist=["urlparse"]).urlparse(e["url"]).hostname)}</figcaption></figure>')
        if e.get('final_url') and e['final_url']!=e['url']:
            parts.append(f'<p class="meta">截图页面：<a href="{esc(e["final_url"])}">{esc(e["final_url"])}</a></p>')
    if story.get('timeline'):
        parts.append('<h3>本周进展</h3><ul>'+''.join(f'<li>{esc(t)}</li>' for t in story['timeline'])+'</ul>')
    parts.append(f'<h3>为什么重要 · 分析</h3><p>{esc(story["why_it_matters"])}</p><h3>接下来观察</h3><p>{esc(story["watch_next"])}</p>')
    if story.get('uncertainty'): parts.append(f'<p class="meta">核查说明：{esc(story["uncertainty"])}</p>')
    parts.append('<div class="sources"><strong>原始信息来源</strong><ol>')
    for ref in story['references']:
        parts.append(f'<li>{esc(ref["source_name"])} · {esc(ref["title"])}<br/>原文发布时间：{esc(ref["published"])}<br/><a href="{esc(ref["url"])}">{esc(ref["url"])}</a></li>')
    parts.append('</ol></div></article>')
    return ''.join(parts)

def extras_html(edition):
    parts=['<section><h2>过去7天正在形成的趋势</h2>']
    for trend in edition.get('trends',[]):
        parts.append('<h3>'+esc(trend['topic'])+'</h3><p>'+esc(trend['text'])+'</p><ul>')
        for ref in trend['references']: parts.append('<li><a href="'+esc(ref['url'])+'">'+esc(ref['title'])+'</a></li>')
        parts.append('</ul>')
    if not edition.get('trends'): parts.append('<p>目前没有满足多事件、跨日和实质更新条件的趋势，不以关键词热度凑数。</p>')
    parts.append('</section><section><h2>值得深读</h2>')
    for item in edition.get('deep_reads',[]):
        parts.append('<h3>'+esc(item['title'])+'</h3><p>'+esc(item['reason'])+'</p><p>'+esc(item['source'])+' · 约'+str(item['minutes'])+'分钟</p><p><a href="'+esc(item['url'])+'">原文链接</a></p>')
    if not edition.get('deep_reads'): parts.append('<p>本期没有满足深读条件的文章。</p>')
    return ''.join(parts)+'</section>'

def xhtml(title,content):
    return f'<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="zh-CN" xml:lang="zh-CN"><head><meta charset="utf-8"/><title>{esc(title)}</title><link rel="stylesheet" type="text/css" href="style.css"/></head><body>{content}</body></html>'

def render(edition):
    stories=edition['stories']; verify_evidence(stories)
    folder=DATA/'editions'/edition['id']; folder.mkdir(parents=True,exist_ok=True)
    title=edition['title']
    sample='排版验收样刊 · 人工编写，非自动生成的当天新闻' if edition.get('sample') else '每日精选' if edition['kind']=='daily' else '一周重要进展'
    cover=f'<section class="cover"><p>世界来信 · KINDLE BRIEFING</p><h1>{esc(title)}</h1><p>{esc(sample)}</p><p class="meta">范围：{esc(edition["start"])} 至 {esc(edition["end"])}<br/>{len(stories)} 条 · 正文可调整字号 · 核心信息附原网页截图</p><p class="meta">截图证明来源当时如何表述，仍需结合证据和归属判断真实性。原文链接列在每条新闻末尾。</p></section>'
    cover+=f'<section><h2>今日概览</h2><p>{esc(edition.get("overview",""))}</p></section>'
    appendix=extras_html(edition)
    htmlstories=[]; epubstories=[]; images=[]
    for i,s in enumerate(stories,1):
        hl=[]; el=[]
        for j,e in enumerate(s['evidence']):
            hl.append('../../'+e['image'])
            name=f'images/s{i}-{j}.png'; el.append(name); images.append((name,DATA/e['image']))
        section='<h2>今日最重要</h2>' if i==1 else '<h2>值得关注</h2>' if i==4 else ''
        htmlstories.append(section+story_html(s,i,hl)); epubstories.append(section+story_html(s,i,el))
    if epubstories: epubstories[-1]+=appendix
    nav='<nav epub:type="toc" id="toc"><h2>目录</h2><ol>'+''.join(f'<li><a href="story{i}.xhtml#s{i}">{esc(s["title"])}</a></li>' for i,s in enumerate(stories,1))+'</ol></nav>'
    webnav='<nav><h2>目录</h2><ol>'+''.join(f'<li><a href="#s{i}">{esc(s["title"])}</a></li>' for i,s in enumerate(stories,1))+'</ol></nav>'
    (folder/'index.html').write_text('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/><title>'+esc(title)+'</title><style>'+CSS+'body{max-width:680px;margin:40px auto;padding:0 20px;}article{margin-top:4em;}</style></head><body>'+cover+webnav+''.join(htmlstories)+appendix+'</body></html>',encoding='utf-8')
    path=folder/'briefing.epub'
    manifest=['<item id="css" href="style.css" media-type="text/css"/>','<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>','<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>','<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>']
    manifest += [f'<item id="s{i}" href="story{i}.xhtml" media-type="application/xhtml+xml"/>' for i in range(1,len(stories)+1)]
    manifest += [f'<item id="img{i}" href="{name}" media-type="image/png"/>' for i,(name,_) in enumerate(images)]
    spine='<itemref idref="cover"/><itemref idref="nav"/>'+''.join(f'<itemref idref="s{i}"/>' for i in range(1,len(stories)+1))
    opf=f'''<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="uid">urn:uuid:{edition['id']}</dc:identifier><dc:title>{esc(title)}</dc:title><dc:language>zh-CN</dc:language><dc:creator>世界来信</dc:creator><meta property="dcterms:modified">{edition['created'][:19]}Z</meta></metadata><manifest>{''.join(manifest)}</manifest><spine toc="ncx">{spine}</spine></package>'''
    ncx=f'<?xml version="1.0" encoding="utf-8"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head><meta name="dtb:uid" content="urn:uuid:{edition["id"]}"/></head><docTitle><text>{esc(title)}</text></docTitle><navMap>'+''.join(f'<navPoint id="p{i}" playOrder="{i}"><navLabel><text>{esc(s["title"])}</text></navLabel><content src="story{i}.xhtml"/></navPoint>' for i,s in enumerate(stories,1))+'</navMap></ncx>'
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('mimetype','application/epub+zip',compress_type=zipfile.ZIP_STORED)
        def add(name,value): z.writestr(name,value,compress_type=zipfile.ZIP_DEFLATED)
        add('META-INF/container.xml','<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        add('OEBPS/content.opf',opf); add('OEBPS/toc.ncx',ncx); add('OEBPS/style.css',CSS)
        add('OEBPS/cover.xhtml',xhtml(title,cover)); add('OEBPS/nav.xhtml',xhtml('目录',nav))
        for i,s in enumerate(epubstories,1): add(f'OEBPS/story{i}.xhtml',xhtml(stories[i-1]['title'],s))
        for name,p in images: add('OEBPS/'+name,p.read_bytes())
    validate_epub(path)
    (folder/'manifest.json').write_text(json.dumps(edition,ensure_ascii=False,indent=2),encoding='utf-8')
    return path

def validate_epub(path):
    with zipfile.ZipFile(path) as z:
        assert z.infolist()[0].filename=='mimetype' and z.infolist()[0].compress_type==0
        assert z.read('mimetype')==b'application/epub+zip'
        assert not z.testzip()
        for name in z.namelist():
            if name.endswith(('.xhtml','.opf','.ncx','.xml')):
                node=ET.fromstring(z.read(name))
                if name.endswith('.xhtml'):
                    for img in node.iter('{http://www.w3.org/1999/xhtml}img'):
                        assert 'OEBPS/'+img.attrib['src'] in z.namelist()

# Compatibility for the existing local UI; cloud and UI use the same sender.
def mail_ready(s):
    from .mailer import mail_ready as check
    return check(s)

def smtp_connect(s):
    from .mailer import smtp_connect as connect
    return connect(s)

def deliver(edition,s):
    from .mailer import deliver as send
    return send(edition,s)

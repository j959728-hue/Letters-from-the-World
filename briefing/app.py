import csv
import io
import json
import secrets as token_compare
import threading
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from . import core
from .core import DATA, ROOT, Source, Settings, init, settings, save_settings, save_secrets, secret, db, sources, upsert_source, iso
from .collect import collect_source, Browser, store_article, canonical, public_url
from .pipeline import worker, STOP, enqueue
from .publish import mail_ready, smtp_connect, deliver

@asynccontextmanager
async def lifespan(app):
    init(); STOP.clear()
    thread=threading.Thread(target=worker,name='briefing-worker',daemon=True); thread.start()
    yield
    STOP.set()

app=FastAPI(title='世界来信 · Kindle Briefing',version='0.1.0',lifespan=lifespan,docs_url='/api/docs',redoc_url=None)

@app.middleware('http')
async def local_only(request,call_next):
    host=request.headers.get('host','').split(':')[0]
    if host not in ('127.0.0.1','localhost','testserver'):
        return JSONResponse({'detail':'管理服务只允许本机访问'},status_code=403)
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        if origin and urlparse(origin).netloc!=request.headers.get('host'):
            return JSONResponse({'detail':'拒绝跨站操作'},status_code=403)
        token=(DATA/'token').read_text(encoding='utf-8')
        if not token_compare.compare_digest(request.headers.get('x-briefing-token',''),token):
            return JSONResponse({'detail':'缺少本地操作令牌，请刷新管理页'},status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Cache-Control']='no-store'
    return response

@app.exception_handler(ValueError)
async def value_error(request,exc):
    return JSONResponse({'detail':str(exc)},status_code=400)

@app.get('/',response_class=HTMLResponse)
def index():
    return (ROOT/'web'/'index.html').read_text(encoding='utf-8').replace('__TOKEN__',(DATA/'token').read_text(encoding='utf-8'))

@app.get('/api/status')
def status():
    s=settings()
    with db() as c:
        jobs=[dict(r) for r in c.execute('SELECT * FROM jobs ORDER BY created DESC LIMIT 20')]
        editions=[]
        for r in c.execute('SELECT * FROM editions ORDER BY created DESC LIMIT 30'):
            body=json.loads(r['body']); delivery=c.execute('SELECT * FROM deliveries WHERE edition_id=?',(r['id'],)).fetchone()
            editions.append({'id':r['id'],'title':body['title'],'kind':r['kind'],'created':r['created'],
                'count':len(body['stories']),'sample':body.get('sample',False),'coverage':body.get('coverage',{}),
                'delivery':dict(delivery) if delivery else None})
        count=c.execute('SELECT COUNT(*) FROM articles').fetchone()[0]
    ss=sources()
    return {'sources':len(ss),'enabled':sum(x['enabled'] for x in ss),'articles':count,'jobs':jobs,'editions':editions,
            'schedule_enabled':s.schedule_enabled,'auto_send':s.auto_send,'daily_time':s.daily_time,'weekly_time':s.weekly_time,
            'timezone':s.timezone,'missing_mail':mail_ready(s),'model_ready':bool(s.model and secret('api_key'))}

@app.get('/api/settings')
def get_settings():
    return {'settings':settings().model_dump(),'secrets':{'api_key':bool(secret('api_key')),'smtp_password':bool(secret('smtp_password'))}}

@app.put('/api/settings')
def put_settings(s:Settings):
    if s.schedule_enabled and (not s.model or not secret('api_key')):
        raise ValueError('启用定时生成前请先保存模型名称和 API 密钥')
    if s.auto_send and mail_ready(s):
        raise ValueError('启用自动投递前请完成：'+'、'.join(mail_ready(s)))
    save_settings(s); return {'ok':True}

class SecretInput(BaseModel):
    api_key: str = Field(default='',max_length=2000)
    smtp_password: str = Field(default='',max_length=2000)

@app.put('/api/secrets')
def put_secrets(data:SecretInput):
    save_secrets(data.model_dump()); return {'ok':True}

@app.post('/api/smtp-test')
def test_smtp():
    s=settings()
    if not s.smtp_host or not s.smtp_user or not secret('smtp_password'): raise ValueError('先填写并保存 Gmail 发件配置')
    try:
        c=smtp_connect(s); c.quit()
    except Exception: raise ValueError('SMTP 登录失败，请核对 Gmail 应用专用密码、账号和网络')
    return {'ok':True,'message':'SMTP 登录成功，此操作没有发送邮件'}

@app.get('/api/sources')
def get_sources(): return sources()

@app.post('/api/sources')
def post_source(s:Source):
    upsert_source(s); return s

@app.put('/api/sources/{sid}')
def put_source(sid:str,s:Source):
    if s.id!=sid: raise ValueError('信息源编号不一致')
    upsert_source(s); return s

@app.delete('/api/sources/{sid}')
def delete_source(sid:str):
    # Archives and past evidence are deliberately retained.
    with db() as c: c.execute('DELETE FROM sources WHERE id=?',(sid,))
    return {'ok':True}

@app.post('/api/sources/{sid}/probe')
def probe(sid:str):
    source=next((s for s in sources() if s['id']==sid),None)
    if not source: raise HTTPException(404)
    if source['adapter']=='page':
        with Browser() as browser: result=collect_source(source,3,browser)
    else: result=collect_source(source,3)
    return {'count':len(result),'source':next(s for s in sources() if s['id']==sid)}

@app.get('/api/export/sources.json')
def export():
    return Response(json.dumps([Source.model_validate(s).model_dump() for s in sources()],ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':'attachment; filename="sources.json"'})

@app.post('/api/import/sources')
def import_sources(items:list[Source]):
    if len(items)>1000: raise ValueError('一次最多导入1000个来源')
    if len({s.id for s in items})!=len(items): raise ValueError('导入文件含重复编号')
    for s in items: upsert_source(s)
    return {'count':len(items)}

class ManualArticle(BaseModel):
    source_id:str
    url:str
    title:str
    published:str

@app.post('/api/articles')
def manual_article(item:ManualArticle):
    public_url(item.url)
    s=next((s for s in sources() if s['id']==item.source_id),None)
    if not s: raise ValueError('来源不存在')
    core.parse_time(item.published)
    a=store_article(dict(item.model_dump(),summary='',source_name=s['name'],region=s['region'],category=s['category'],group=s['group'] or s['id'],priority=s['priority']))
    if not a: raise ValueError('文章日期不可用')
    return a

@app.post('/api/run/{kind}')
def run_kind(kind:str): return {'job_id':enqueue(kind)}

@app.get('/api/jobs/{jid}/audit')
def audit_log(jid:str):
    if not __import__('re').fullmatch('[a-f0-9]{32}',jid): raise HTTPException(404)
    p=DATA/'jobs'/f'{jid}.checkpoint.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'message':'暂无逐条核查记录'}

@app.post('/api/editions/{eid}/send')
def send_edition(eid:str):
    with db() as c: r=c.execute('SELECT body FROM editions WHERE id=?',(eid,)).fetchone()
    if not r: raise HTTPException(404)
    return {'status':deliver(json.loads(r['body']),settings())}

@app.get('/files/{path:path}')
def files(path:str):
    p=(DATA/path).resolve()
    allowed=(p.is_relative_to(DATA/'editions') and p.name in ('index.html','briefing.epub','manifest.json')) or (p.is_relative_to(DATA/'evidence') and p.suffix=='.png')
    if not allowed or not p.is_file(): raise HTTPException(404)
    return FileResponse(p,media_type='application/epub+zip' if p.suffix=='.epub' else None)

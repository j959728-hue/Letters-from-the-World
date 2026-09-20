import hashlib
import json
import os
import secrets
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('BRIEFING_DATA', ROOT / 'data')).resolve()
DB_LOCK = threading.RLock()

def now():
    return datetime.now(timezone.utc)

def iso(dt=None):
    return (dt or now()).astimezone(timezone.utc).isoformat()

def parse_time(s):
    d = datetime.fromisoformat(s.replace('Z', '+00:00'))
    if d.tzinfo is None:
        raise ValueError('时间必须包含时区')
    return d.astimezone(timezone.utc)

def digest(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()

def atomic_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)

class Source(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12], pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    name: str = Field(min_length=1, max_length=180)
    url: str
    feed_url: str = ''
    adapter: Literal['rss', 'page', 'manual'] = 'rss'
    enabled: bool = False
    region: str = '全球'
    language: str = 'en'
    category: str = '世界'
    group: str = ''
    perspective: str = ''
    priority: int = Field(default=3, ge=1, le=5)
    link_selector: str = 'article a[href]'
    content_selector: str = ''
    notes: str = ''

    @field_validator('url', 'feed_url')
    @classmethod
    def urls(cls, v):
        if v and not v.startswith(('https://', 'http://')):
            raise ValueError('只支持 http/https 地址')
        return v

class Settings(BaseModel):
    timezone: str = 'Asia/Shanghai'
    daily_time: str = '07:30'
    weekly_time: str = '09:00'
    schedule_enabled: bool = False
    auto_send: bool = False
    language: str = '简体中文'
    daily_limit: int = Field(default=16, ge=1, le=30)
    weekly_limit: int = Field(default=16, ge=1, le=30)
    min_stories: int = Field(default=3, ge=1, le=20)
    max_candidates: int = Field(default=300, ge=1, le=600)
    max_per_source: int = Field(default=12, ge=1, le=30)
    max_region_share: float = Field(default=0.5, ge=0.2, le=1)
    min_source_success_ratio: float = Field(default=0.5, ge=0.1, le=1)
    daily_lookback_hours: int = Field(default=24, ge=12, le=48)
    model: str = ''
    api_base: str = 'https://api.openai.com/v1'
    api_format: Literal['responses', 'chat_completions'] = 'responses'
    max_output_tokens: int = Field(default=4500, ge=1000, le=16000)
    fetch_timeout_ms: int = Field(default=35000, ge=1000, le=90000)
    body_wait_ms: int = Field(default=8000, ge=100, le=30000)
    scroll_steps: int = Field(default=3, ge=0, le=8)
    max_text_chars: int = Field(default=16000, ge=1000, le=50000)
    llm_token_budget: int = Field(default=180000, ge=5000, le=1000000)
    input_usd_per_million: float | None = Field(default=None,ge=0)
    output_usd_per_million: float | None = Field(default=None,ge=0)
    kindle_email: str = ''
    smtp_host: str = ''
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_security: Literal['ssl', 'starttls'] = 'ssl'
    smtp_user: str = ''
    sender_email: str = ''
    approved_sender_confirmed: bool = False
    max_attachment_mb: int = Field(default=18, ge=1, le=25)

    @field_validator('timezone')
    @classmethod
    def tz(cls, v):
        ZoneInfo(v)
        return v

    @field_validator('daily_time', 'weekly_time')
    @classmethod
    def times(cls, v):
        datetime.strptime(v, '%H:%M')
        return v

    @field_validator('kindle_email', 'sender_email', 'smtp_user', 'smtp_host')
    @classmethod
    def no_headers(cls, v):
        if any(c in v for c in '\r\n\x00'):
            raise ValueError('字段包含非法控制字符')
        return v.strip()

def settings():
    return Settings.model_validate_json((DATA / 'settings.json').read_text(encoding='utf-8'))

def save_settings(s):
    atomic_json(DATA / 'settings.json', s.model_dump())

def secret(name):
    keys = {'api_key':('LLM_API_KEY','OPENAI_API_KEY','BRIEFING_API_KEY'), 'smtp_password':('SMTP_PASSWORD','BRIEFING_SMTP_PASSWORD')}[name]
    for key in keys:
        if os.environ.get(key): return os.environ[key]
    path = DATA / 'secrets.dpapi'
    if os.name=='nt' and path.exists():
        from .vault import decode
        return json.loads(decode(path.read_bytes())).get(name,'')
    return ''

def save_secrets(values):
    if not any(values.values()): return
    if os.name!='nt': raise ValueError('云端密钥请通过环境变量／GitHub Secrets 设置')
    from .vault import encode,decode
    path = DATA / 'secrets.dpapi'
    obj = json.loads(decode(path.read_bytes())) if path.exists() else {}
    for name in ('api_key', 'smtp_password'):
        if values.get(name):
            obj[name] = values[name]
    tmp=path.with_suffix('.tmp'); tmp.write_bytes(encode(json.dumps(obj).encode())); os.replace(tmp,path)
    try:
        path.chmod(0o600)
    except OSError:
        pass

@contextmanager
def db():
    DATA.mkdir(parents=True, exist_ok=True)
    with DB_LOCK:
        con = sqlite3.connect(DATA/'briefing.sqlite', timeout=30)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA journal_mode=WAL')
        try:
            yield con
            con.commit()
        finally:
            con.close()

def init():
    for d in ('evidence', 'editions'):
        (DATA/d).mkdir(parents=True, exist_ok=True)
    if not (DATA/'settings.json').exists():
        save_settings(Settings())
    if not (DATA/'token').exists():
        (DATA/'token').write_text(secrets.token_urlsafe(32), encoding='utf-8')
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, body TEXT NOT NULL, health TEXT DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS articles(id TEXT PRIMARY KEY, source_id TEXT NOT NULL, url TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL, published TEXT NOT NULL, discovered TEXT NOT NULL, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS snapshots(article_id TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS editions(id TEXT PRIMARY KEY, kind TEXT NOT NULL, created TEXT NOT NULL,
            body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ready');
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, dedup TEXT UNIQUE, kind TEXT NOT NULL,
            status TEXT NOT NULL, stage TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL,
            error TEXT NOT NULL DEFAULT '', edition_id TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS deliveries(edition_id TEXT PRIMARY KEY, recipient TEXT NOT NULL,
            status TEXT NOT NULL, updated TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '');
        ''')
        if not c.execute('SELECT 1 FROM sources LIMIT 1').fetchone():
            source_path=ROOT/'config'/'sources.json'
            if not source_path.exists(): source_path=ROOT/'sources.seed.json'
            for s in json.loads(source_path.read_text(encoding='utf-8')):
                source = Source.model_validate(s)
                c.execute('INSERT INTO sources(id,body) VALUES(?,?)', (source.id, source.model_dump_json()))

def sources(enabled=False):
    with db() as c:
        result = [dict(json.loads(r['body']), health=json.loads(r['health'])) for r in c.execute('SELECT * FROM sources')]
    return [r for r in result if r['enabled']] if enabled else result

def upsert_source(s):
    with db() as c:
        c.execute('INSERT INTO sources(id,body) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body', (s.id,s.model_dump_json()))

def health(sid, **data):
    with db() as c:
        c.execute('UPDATE sources SET health=? WHERE id=?', (json.dumps(dict(checked_at=iso(), **data), ensure_ascii=False), sid))

def log_stage(jid, stage, status='running', error='', edition_id=''):
    with db() as c:
        c.execute('UPDATE jobs SET stage=?,status=?,updated=?,error=?,edition_id=? WHERE id=?', (stage,status,iso(),error,edition_id,jid))

def window(kind, end, s):
    # Daily and weekly both use half-open windows [start,end); weekly retains seven days.
    hours = 168 if kind == 'weekly' else s.daily_lookback_hours
    return end-timedelta(hours=hours), end

def due_slots(dt, s):
    if not s.schedule_enabled:
        return []
    local = dt.astimezone(ZoneInfo(s.timezone))
    out=[]
    for kind, clock in [('daily',s.daily_time),('weekly',s.weekly_time)]:
        if kind=='weekly' and local.weekday()!=5:
            continue
        h,m=map(int,clock.split(':'))
        scheduled=local.replace(hour=h,minute=m,second=0,microsecond=0)
        # Same-day catch-up after restart; do not send days of stale mail.
        if scheduled <= local:
            out.append((kind, f'{kind}:{local.date()}', scheduled.astimezone(timezone.utc)))
    return out

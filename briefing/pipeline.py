import json
import math
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from datetime import timedelta
from zoneinfo import ZoneInfo

from .core import DATA, db, iso, now, settings, sources, log_stage, window, due_slots, atomic_json, parse_time
from .collect import Browser, collect_source
from .editor import Editor, validate_claims
from .publish import render, deliver

def enqueue(kind, dedup=None, end=None):
    if kind not in ('daily','weekly','collect'): raise ValueError('不支持的任务')
    jid=uuid.uuid4().hex
    with db() as c:
        if dedup:
            old=c.execute('SELECT id FROM jobs WHERE dedup=?',(dedup,)).fetchone()
            if old: return old['id']
        c.execute('INSERT INTO jobs(id,dedup,kind,status,stage,created,updated) VALUES(?,?,?,?,?,?,?)',
                  (jid,dedup,kind,'queued','等待运行',iso(),iso()))
        atomic_json(DATA/'jobs'/f'{jid}.json',{'end':iso(end or now()),'scheduled':bool(dedup)})
    return jid

def run(jid):
    from .builder import build
    from .config import load_interests
    with db() as c: job=dict(c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
    args=json.loads((DATA/'jobs'/f'{jid}.json').read_text(encoding='utf-8'))
    s=settings()
    log_stage(jid,'运行共享简报流水线')
    build(s,load_interests(),kind='daily' if job['kind']=='collect' else job['kind'],end=parse_time(args['end']),
        dry_run=not(args['scheduled'] and s.auto_send),jid=jid,collect_only=job['kind']=='collect')
    log_stage(jid,'已生成；查看简报与投递记录','done',edition_id=jid if job['kind']!='collect' else '')

STOP=threading.Event()

def worker():
    with db() as c:
        c.execute("UPDATE jobs SET status='interrupted',stage='上次进程中断，请手动重试' WHERE status='running'")
        c.execute("UPDATE deliveries SET status='uncertain',detail='进程中断，发送结果未知；请核查发件箱' WHERE status='sending'")
    while not STOP.is_set():
        try:
            for kind,dedup,end in due_slots(now(),settings()): enqueue(kind,dedup,end)
            with db() as c:
                row=c.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
                if row: c.execute("UPDATE jobs SET status='running' WHERE id=?",(row['id'],))
            if row:
                try: run(row['id'])
                except Exception as e:
                    log_stage(row['id'],'任务停止，查看原因','failed',f'{type(e).__name__}: {str(e)[:500]}')
                continue
        except Exception as exc:
            __import__('logging').error('[SCHEDULER] %s',type(exc).__name__)
        STOP.wait(10)

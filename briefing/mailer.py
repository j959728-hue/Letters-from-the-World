import logging
import re
import smtplib
import ssl
import time
import os
from contextlib import contextmanager
from email.message import EmailMessage
from email.policy import SMTP
from .core import DATA, iso, secret, db
from .publish import validate_epub, verify_evidence
from .state import State
from .naming import edition_filename

def mail_ready(s):
    errors=[]
    if not re.fullmatch(r'[^@\s]+@(?:free\.)?kindle\.com',s.kindle_email,re.I): errors.append('Kindle 邮箱')
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',s.sender_email): errors.append('发件邮箱')
    if not s.smtp_host or not s.smtp_user or not secret('smtp_password'): errors.append('Gmail SMTP 登录配置')
    if not s.approved_sender_confirmed: errors.append('Amazon 已认可发件人确认')
    return errors

def smtp_connect(s):
    ctx=ssl.create_default_context()
    if s.smtp_security=='ssl':
        client=smtplib.SMTP_SSL(s.smtp_host,s.smtp_port,timeout=35,context=ctx)
    else:
        client=smtplib.SMTP(s.smtp_host,s.smtp_port,timeout=35); client.ehlo(); client.starttls(context=ctx); client.ehlo()
    try: client.login(s.smtp_user,secret('smtp_password'))
    except Exception:
        client.close(); raise
    return client

def connect_with_retry(s):
    for attempt in range(3):
        try: return smtp_connect(s)
        except smtplib.SMTPAuthenticationError:
            raise ValueError('SMTP authentication failed') from None
        except (OSError,smtplib.SMTPException):
            logging.warning('[EMAIL] connection attempt=%s failed',attempt+1)
            if attempt==2: raise ValueError('SMTP unavailable after 3 attempts') from None
            time.sleep(2**attempt)

@contextmanager
def delivery_lock():
    DATA.mkdir(parents=True,exist_ok=True)
    with (DATA/'delivery.lock').open('a+b') as handle:
        handle.seek(0); handle.write(b'0'); handle.flush(); handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError: raise ValueError('Another delivery is running') from None
        try: yield
        finally:
            handle.seek(0)
            if os.name=='nt': msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else: fcntl.flock(handle,fcntl.LOCK_UN)

def deliver(edition,s,state=None,force=False):
    with delivery_lock():
        state=state or State()
        # Refresh after acquiring the process lock; a UI click may have created this State earlier.
        if state.path.exists(): state.body=State(state.path).body
        return _deliver(edition,s,state,force)

def _deliver(edition,s,state=None,force=False):
    state=state or State()
    key=edition.get('delivery_id')
    if not key:
        from zoneinfo import ZoneInfo
        from .core import parse_time
        key=edition['kind']+':'+str(parse_time(edition['end']).astimezone(ZoneInfo(s.timezone)).date())
    if state.blocked(key) and not force: return 'already_recorded'
    missing=mail_ready(s)
    if missing: raise ValueError('Missing mail configuration: '+', '.join(missing))
    if edition.get('sample'): raise ValueError('Sample editions cannot be delivered')
    if not edition['stories'] or any(not all(st.get('audit',{}).get(k) for k in ('approved','all_core_supported','screenshots_readable','no_extra_facts')) for st in edition['stories']):
        raise ValueError('Unapproved stories')
    verify_evidence(edition['stories'])
    folder=DATA/'editions'/edition['id']; path=folder/'briefing.epub'; validate_epub(path)
    if path.stat().st_size>s.max_attachment_mb*1024*1024: raise ValueError('EPUB attachment too large')
    msg=EmailMessage(policy=SMTP)
    msg['From']=s.sender_email; msg['To']=s.kindle_email
    msg['Subject']=edition_filename(edition).removesuffix('.epub')
    msg['Message-ID']=f'<briefing-{key.replace(":","-")}-{state.body["deliveries"].get(key,{}).get("attempt",0)+1}@{s.sender_email.split("@")[-1]}>'
    msg.set_content('本期简报见 HTML 正文和 EPUB 附件；每条核心信息附原文截图和核查链接。')
    html=(folder/'index.html').read_text(encoding='utf-8')
    images={e['image']:DATA/e['image'] for st in edition['stories'] for e in st['evidence']}
    for i,name in enumerate(images): html=html.replace('../../'+name,f'cid:evidence-{i}')
    msg.add_alternative(html,subtype='html')
    for i,path_image in enumerate(images.values()):
        msg.get_payload()[-1].add_related(path_image.read_bytes(),maintype='image',subtype='png',cid=f'<evidence-{i}>')
    msg.add_attachment(path.read_bytes(),maintype='application',subtype='epub+zip',filename=edition_filename(edition))
    if len(msg.as_bytes())>24*1024*1024: raise ValueError('Encoded email exceeds 24 MB; reduce images or final items')
    client=connect_with_retry(s)
    try:
        state.reserve(key,force)  # Fail closed if remote persistence fails.
        try:
            refused=client.send_message(msg)
            if refused: raise ValueError('Recipient refused')
        except Exception:
            state.finish(key,'uncertain')
            raise ValueError('SMTP outcome uncertain; verify before --force') from None
        state.finish(key,'smtp_accepted',edition.get('history_records',[]))
        with db() as c:
            c.execute('INSERT OR REPLACE INTO deliveries VALUES(?,?,?,?,?)',(edition['id'],s.kindle_email,'smtp_accepted',iso(),'SMTP accepted; Kindle receipt not verified'))
    finally: client.close()
    logging.info('[EMAIL] SMTP accepted')
    return 'smtp_accepted'


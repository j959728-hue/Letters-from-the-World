import hashlib
from unittest.mock import Mock
import pytest
from PIL import Image
from briefing.core import DATA,Settings,iso,now
from briefing.publish import render,verify_evidence
from briefing.mailer import deliver,connect_with_retry
from briefing.state import State

@pytest.fixture
def edition():
    image=DATA/'evidence/test/block.png'; image.parent.mkdir(parents=True,exist_ok=True)
    Image.new('RGB',(200,100),'white').save(image)
    claim={'article_id':'test','block_id':0,'quote':'A test source quote, for automated tests only.','text':'这是一条用于验证排版和防重发的测试内容。'}
    evidence=dict(claim,image='evidence/test/block.png',url='https://example.com/news',captured_at=iso(),image_sha256=hashlib.sha256(image.read_bytes()).hexdigest())
    story=dict(title='测试事件',region='测试',category='测试',basis='单一来源报道',core=[claim],evidence=[evidence],references=[dict(source_name='test',title='fixture',url='https://example.com',published=iso())],why_it_matters='测试意义',watch_next='测试观察',audit=dict(approved=True,all_core_supported=True,screenshots_readable=True,no_extra_facts=True))
    obj=dict(id='fixture',kind='daily',delivery_id='daily:'+str(now().date()),title='自动化测试',created=iso(),start=iso(),end=iso(),stories=[story],history_records=[])
    render(obj); return obj

def settings(): return Settings(kindle_email='test@kindle.com',sender_email='test@example.com',smtp_user='test',smtp_host='smtp.example.com',approved_sender_confirmed=True)

def test_sends_once_with_html_and_epub(edition,tmp_path,monkeypatch):
    monkeypatch.setenv('SMTP_PASSWORD','test-only')
    client=Mock(); client.send_message.return_value={}
    monkeypatch.setattr('briefing.mailer.connect_with_retry',lambda s:client)
    state=State(tmp_path/'state.json')
    assert deliver(edition,settings(),state)=='smtp_accepted'
    assert deliver(edition,settings(),state)=='already_recorded'
    assert client.send_message.call_count==1
    msg=client.send_message.call_args.args[0]
    assert any(p.get_content_type()=='text/html' for p in msg.walk())
    assert any(p.get_content_type()=='application/epub+zip' for p in msg.walk())
    assert msg.get_payload()[-1].get_filename()=='%s_世界来信-日报_测试事件.epub' % edition['delivery_id'].split(':')[1]
    assert deliver(edition,settings(),state,force=True)=='smtp_accepted'
    assert client.send_message.call_count==2

def test_uncertain_never_resends(edition,tmp_path,monkeypatch):
    monkeypatch.setenv('SMTP_PASSWORD','test-only')
    client=Mock(); client.send_message.side_effect=OSError('disconnect during DATA')
    monkeypatch.setattr('briefing.mailer.connect_with_retry',lambda s:client)
    state=State(tmp_path/'state.json')
    with pytest.raises(ValueError,match='uncertain'): deliver(edition,settings(),state)
    assert deliver(edition,settings(),State(state.path))=='already_recorded'
    assert client.send_message.call_count==1

def test_no_send_before_remote_reservation(edition,tmp_path,monkeypatch):
    monkeypatch.setenv('SMTP_PASSWORD','test-only'); client=Mock()
    monkeypatch.setattr('briefing.mailer.connect_with_retry',lambda s:client)
    state=State(tmp_path/'state.json',persist_git=True)
    monkeypatch.setattr(state,'commit',Mock(side_effect=RuntimeError('push failed')))
    with pytest.raises(RuntimeError): deliver(edition,settings(),state)
    client.send_message.assert_not_called()

def test_evidence_tamper(edition):
    (DATA/'evidence/test/block.png').write_bytes(b'changed')
    with pytest.raises(ValueError): verify_evidence(edition['stories'])

def test_connect_retry(monkeypatch):
    connect=Mock(side_effect=[OSError(),OSError(),Mock()])
    monkeypatch.setattr('briefing.mailer.smtp_connect',connect)
    monkeypatch.setattr('briefing.mailer.time.sleep',lambda _:None)
    connect_with_retry(settings()); assert connect.call_count==3

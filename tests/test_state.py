from datetime import timedelta
import pytest
from briefing.state import State
from briefing.core import iso,now

def test_reservation_durable_and_daily_weekly_distinct(tmp_path):
    s=State(tmp_path/'state.json'); s.reserve('daily:2026-09-15')
    again=State(s.path)
    assert again.blocked('daily:2026-09-15')
    assert not again.blocked('weekly:2026-09-15')
    with pytest.raises(ValueError): again.reserve('daily:2026-09-15')
    again.finish('daily:2026-09-15','smtp_accepted')
    with pytest.raises(ValueError): again.reserve('daily:2026-09-15')
    again.reserve('daily:2026-09-15',force=True)
    assert again.body['deliveries']['daily:2026-09-15']['attempt']==2

def test_state_prune_no_reset_corruption(tmp_path):
    s=State(tmp_path/'state.json'); s.body['history']=[{'sent_at':iso(now()-timedelta(days=20))}]
    s.save(); assert s.history==[]
    s.path.write_text('{broken',encoding='utf-8')
    with pytest.raises(ValueError): State(s.path)

def test_commit_failure_blocks_reservation(tmp_path,monkeypatch):
    s=State(tmp_path/'state.json',persist_git=True)
    def fail(): raise RuntimeError('remote unavailable')
    monkeypatch.setattr(s,'commit',fail)
    with pytest.raises(RuntimeError): s.reserve('daily:test')
    assert State(s.path).blocked('daily:test')

def test_forced_delivery_replaces_same_event_history(tmp_path):
    state=State(tmp_path/'state.json'); key='daily:test'
    record=dict(delivery_id=key,fingerprint='event',sent_at=iso(),summary='first')
    state.reserve(key); state.finish(key,'smtp_accepted',[record])
    state.reserve(key,force=True)
    state.finish(key,'smtp_accepted',[dict(record,summary='updated')])
    assert len(state.history)==1 and state.history[0]['summary']=='updated'

from unittest.mock import Mock
import pytest
from briefing.core import Settings
from briefing.editor import Selection
from briefing.llm_client import LLMClient,BudgetExceeded,strict_schema

def test_structured_payload_and_usage(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-fixture-key')
    response=Mock(status_code=200)
    response.json.return_value={'status':'completed','usage':{'total_tokens':100},'output':[{'type':'message','content':[{'type':'output_text','text':'{"events":[]}'}]}]}
    post=Mock(return_value=response); monkeypatch.setattr('briefing.llm_client.httpx.post',post)
    client=LLMClient(Settings(model='fixture-model'))
    assert client.ask(Selection,'test').events==[]
    body=post.call_args.kwargs['json']
    assert body['store'] is False and body['text']['format']['strict'] is True
    assert client.reserved_tokens==100 and client.calls==1

def test_budget_before_request(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-fixture-key')
    post=Mock(); monkeypatch.setattr('briefing.llm_client.httpx.post',post)
    client=LLMClient(Settings(model='fixture-model',llm_token_budget=5000))
    with pytest.raises(BudgetExceeded): client.ask(Selection,'中'*10000)
    post.assert_not_called()

def test_provider_error_does_not_echo_response(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-fixture-key')
    response=Mock(status_code=401,text='private auth content')
    monkeypatch.setattr('briefing.llm_client.httpx.post',Mock(return_value=response))
    with pytest.raises(ValueError) as exc: LLMClient(Settings(model='fixture-model')).ask(Selection,'test')
    assert '401' in str(exc.value) and 'private' not in str(exc.value) and 'test-fixture-key' not in str(exc.value)

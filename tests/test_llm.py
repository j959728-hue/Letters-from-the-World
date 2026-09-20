from unittest.mock import Mock
import pytest
from briefing.core import Settings
from briefing.editor import Selection
from briefing.llm_client import LLMClient,BudgetExceeded,strict_schema
from briefing.config import load_settings

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


def test_safe_provider_diagnostic(monkeypatch, caplog):
    monkeypatch.setenv('OPENAI_API_KEY','test-fixture-key')
    response=Mock(status_code=429)
    response.json.return_value={'error':{'code':'insufficient_quota','message':'private auth content'}}
    monkeypatch.setattr('briefing.llm_client.httpx.post',Mock(return_value=response))
    monkeypatch.setattr('briefing.llm_client.time.sleep',lambda _:None)
    with pytest.raises(ValueError):
        LLMClient(Settings(model='fixture-model')).ask(Selection,'test')
    assert 'HTTP 429' in caplog.text and 'insufficient_quota' in caplog.text
    assert 'private auth content' not in caplog.text and 'test-fixture-key' not in caplog.text


def test_incomplete_diagnostic(monkeypatch, caplog):
    monkeypatch.setenv('OPENAI_API_KEY','test-fixture-key')
    response=Mock(status_code=200)
    response.json.return_value={'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'}}
    monkeypatch.setattr('briefing.llm_client.httpx.post',Mock(return_value=response))
    with pytest.raises(ValueError):
        LLMClient(Settings(model='fixture-model')).ask(Selection,'test')
    assert 'max_output_tokens' in caplog.text


def test_switch_to_chat_completions_with_image(monkeypatch, tmp_path):
    monkeypatch.setenv('LLM_API_KEY','other-provider-fixture')
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    picture=tmp_path/'evidence.png'; picture.write_bytes(b'fake-png')
    response=Mock(status_code=200)
    response.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':'{"events":[]}'}}],
                                'usage':{'total_tokens':120}}
    post=Mock(return_value=response); monkeypatch.setattr('briefing.llm_client.httpx.post',post)
    client=LLMClient(Settings(model='other-model',api_base='https://provider.example/v1',api_format='chat_completions'))
    assert client.ask(Selection,'select',images=[picture]).events==[]
    assert post.call_args.args[0]=='https://provider.example/v1/chat/completions'
    body=post.call_args.kwargs['json']
    assert body['response_format']=={'type':'json_object'}
    assert body['messages'][1]['content'][1]['type']=='image_url'
    assert client.reserved_tokens==120


def test_provider_settings_env_and_legacy(monkeypatch):
    monkeypatch.setenv('OPENAI_MODEL','legacy-model')
    monkeypatch.setenv('LLM_MODEL','new-model')
    monkeypatch.setenv('LLM_API_BASE_URL','https://provider.example/v1')
    monkeypatch.setenv('LLM_API_FORMAT','chat_completions')
    assert load_settings().model=='new-model'
    assert load_settings().api_base=='https://provider.example/v1'
    assert load_settings().api_format=='chat_completions'


def test_chat_completion_schema_rejected(monkeypatch):
    monkeypatch.setenv('LLM_API_KEY','fixture')
    response=Mock(status_code=200)
    response.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':'{"wrong":1}'}}]}
    monkeypatch.setattr('briefing.llm_client.httpx.post',Mock(return_value=response))
    with pytest.raises(ValueError,match='output_schema_validation_failed'):
        LLMClient(Settings(model='other-model',api_format='chat_completions')).ask(Selection,'select')

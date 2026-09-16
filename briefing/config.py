import json
import os
from pathlib import Path
from pydantic import BaseModel, Field, model_validator
from .core import ROOT, Settings

class CurationConfig(BaseModel):
    topics: dict[str,list[str]]
    weights: dict[str,float]
    rules: dict
    importance_signals: dict[str,list[str]]
    scoring: dict
    history_days: int = Field(default=14,ge=7,le=31)
    max_history_events: int = Field(default=700,ge=50,le=3000)
    llm_candidate_clusters: int = Field(default=30,ge=5,le=40)
    deep_reads: int = Field(default=3,ge=0,le=4)
    deep_read_min_words: int = 1000
    deep_read_signals: list[str] = []
    max_trends: int = Field(default=4,ge=0,le=5)
    trend_min_events: int = 3
    trend_min_days: int = 2
    trend_min_updates: int = 1

    @model_validator(mode='after')
    def valid(self):
        expected={'Importance','Relevance','Novelty','SourceQuality','CrossSource','Depth'}
        if set(self.weights)!=expected or abs(sum(self.weights.values())-100)>0.001 or min(self.weights.values())<0:
            raise ValueError('评分权重必须包含六个维度且非负、合计100')
        for key in ('content_similarity','title_duplicate_similarity','cluster_similarity','history_similarity'):
            if not 0<self.rules[key]<=1: raise ValueError('相似度阈值必须在(0,1]')
        if self.scoring['depth_words']<=0 or self.scoring['cross_source_cap']<=1:
            raise ValueError('评分参数无效')
        return self

ENV_FIELDS={'OPENAI_MODEL':'model','OPENAI_BASE_URL':'api_base','SMTP_HOST':'smtp_host','SMTP_PORT':'smtp_port',
    'SMTP_USERNAME':'smtp_user','EMAIL_FROM':'sender_email','KINDLE_EMAIL':'kindle_email','SMTP_SECURITY':'smtp_security',
    'MAX_CANDIDATES':'max_candidates','MAX_FINAL_ITEMS':'daily_limit','TIMEZONE':'timezone',
    'APPROVED_SENDER_CONFIRMED':'approved_sender_confirmed','LLM_TOKEN_BUDGET':'llm_token_budget',
    'LLM_INPUT_USD_PER_MILLION':'input_usd_per_million','LLM_OUTPUT_USD_PER_MILLION':'output_usd_per_million'}

def load_settings(path=None):
    obj=json.loads(Path(path or ROOT/'config'/'settings.json').read_text(encoding='utf-8'))
    for env,field in ENV_FIELDS.items():
        if os.environ.get(env): obj[field]=os.environ[env]
    return Settings.model_validate(obj)

def load_interests(path=None):
    return CurationConfig.model_validate_json(Path(path or ROOT/'config'/'interests.json').read_text(encoding='utf-8'))

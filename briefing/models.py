from pydantic import BaseModel, Field

class Article(BaseModel):
    id: str
    url: str
    canonical_url: str
    title: str
    source: str
    source_id: str
    author: str = ''
    published_at: str
    fetched_at: str
    text: str
    word_count: int
    content_hash: str
    simhash: str
    group: str
    region: str
    category: str
    priority: int = 3
    blocks: list[dict] = Field(default_factory=list)
    snapshot: dict = Field(default_factory=dict)
    original_url: str = ''

    def legacy(self):
        return dict(self.model_dump(),published=self.published_at,source_name=self.source,summary=self.text[:1400])

class StoryCluster(BaseModel):
    id: str
    topic: str
    articles: list[Article]
    representative_article: str
    score: float = 0
    dimensions: dict[str,float] = Field(default_factory=dict)
    update: bool = False
    novelty_reason: str = ''

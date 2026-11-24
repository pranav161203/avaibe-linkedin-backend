"""Request bodies for the company knowledge base."""

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=210_000)  # the service checks the 200,000-character limit after cleaning
    account_ids: list[int] = Field(default_factory=list, max_length=50)  # empty = applies to every account

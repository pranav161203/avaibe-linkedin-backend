"""Request bodies for analytics and suggestion decisions."""

from pydantic import BaseModel, Field


class SimilarQuery(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    text: str = Field(default="", max_length=4000)
    topic: str | None = Field(default=None, max_length=200)

class SimilarIn(BaseModel):
    account_id: int
    queries: list[SimilarQuery] = Field(max_length=60)


class DecisionIn(BaseModel):
    account_id: int
    key: str = Field(min_length=1, max_length=120, pattern=r"^(rule:[\w-]+|ai:\d+:\d+)$")
    # None clears the decision (Undo)
    status: str | None = Field(default=None, pattern=r"^(doing|later|dismissed|done)$")

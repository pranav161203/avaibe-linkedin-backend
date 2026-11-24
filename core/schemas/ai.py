"""Request bodies for the Claude features (ideas, post assistant, chat, compare)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from core.services.ai import chat as ai_chat


class TrendsIn(BaseModel):
    account_id: int


class GenerateIn(BaseModel):
    account_id: int
    focus: str | None = Field(default=None, max_length=300)

class PostAssistIn(BaseModel):
    account_id: int
    format: str = Field(max_length=20)
    caption: str = Field(max_length=3500)
    topic: str | None = Field(default=None, max_length=200)
    industry: str | None = Field(default=None, max_length=200)
    cta: str | None = Field(default=None, max_length=300)
    goal: Literal["brand", "sales", "engagement"] | None = None
    instructions: str | None = Field(default=None, max_length=500)
    # The parts of the post to review, picked after clicking Analyse
    focus: list[Literal["text", "visual", "timing", "poll"]] = Field(default_factory=lambda: ["text"], min_length=1, max_length=4)
    scheduled_at: datetime | None = None  # the chosen posting time, for the timing review
    details: dict[str, Any] = Field(default_factory=dict)  # poll question and options, titles (format details)
    media_attached: bool = False  # an image, PDF or video is attached to the post (videos aren't sent: the AI can't watch them)

class ChatMessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=6000)

class PostChatIn(BaseModel):
    account_id: int
    format: str = Field(max_length=20)
    caption: str = Field(default="", max_length=3500)
    topic: str | None = Field(default=None, max_length=200)
    industry: str | None = Field(default=None, max_length=200)
    cta: str | None = Field(default=None, max_length=300)
    goal: Literal["brand", "sales", "engagement"] | None = None
    messages: list[ChatMessageIn] = Field(default_factory=list, max_length=ai_chat.POST_CHAT_MAX_MESSAGES)
    web_search: bool = False  # the team's per-message switch: look things up on the web first (costs a little more)

class ComparePostsIn(BaseModel):
    account_id: int
    post_ids: list[int] = Field(min_length=2, max_length=4)
    checkpoint: Literal["1h", "6h", "24h", "48h", "7d"]

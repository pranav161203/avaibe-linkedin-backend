"""Request bodies for tracked posts, their snapshots and audience."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from core.common.timeutil import from_uae_local
from core.schemas.common import Dimension, Format, normalise_hashtags


class PostIn(BaseModel):
    account_id: int
    post_url: str | None = Field(default=None, max_length=500)
    linkedin_post_id: str | None = Field(default=None, max_length=100)
    author: str | None = Field(default=None, max_length=200)
    # A value without a time-zone offset is read as UAE local time.
    published_at: datetime
    # None = keep what is stored (a new post: True). False = only the date is known.
    time_known: bool | None = None
    format: Format
    topic: str | None = Field(default=None, max_length=200)
    industry: str | None = Field(default=None, max_length=200)
    keywords: list[str] = []
    cta: str | None = Field(default=None, max_length=300)
    hashtags: list[str] = []
    caption: str | None = None
    notes: str | None = None

    @field_validator("published_at")
    @classmethod
    def _uae_default(cls, v: datetime) -> datetime:
        return from_uae_local(v)

    @field_validator("hashtags")
    @classmethod
    def _hashtags(cls, v: list[str]) -> list[str]:
        return normalise_hashtags(v)

    @field_validator("keywords")
    @classmethod
    def _keywords(cls, v: list[str]) -> list[str]:
        return [k.strip() for k in v if k.strip()]

    @field_validator("post_url", "linkedin_post_id", "author", "topic", "industry", "cta")
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None

class SnapshotIn(BaseModel):
    # Defaults to "now" when omitted
    captured_at: datetime | None = None
    impressions: int | None = Field(default=None, ge=0)
    members_reached: int | None = Field(default=None, ge=0)
    clicks: int | None = Field(default=None, ge=0)
    reactions: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)
    reposts: int | None = Field(default=None, ge=0)
    video_views: int | None = Field(default=None, ge=0)
    poll_votes: int | None = Field(default=None, ge=0)
    newsletter_views: int | None = Field(default=None, ge=0)
    newsletter_subscribers: int | None = Field(default=None, ge=0)
    followers_gained: int | None = Field(default=None, ge=0)
    notes: str | None = None

    @field_validator("captured_at")
    @classmethod
    def _uae_default(cls, v: datetime | None) -> datetime | None:
        return from_uae_local(v) if v else None

class AudienceRowIn(BaseModel):
    dimension: Dimension
    value: str = Field(min_length=1, max_length=200)
    pct: float = Field(ge=0, le=100)

    @field_validator("value")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

class PostAudienceIn(BaseModel):
    captured_at: datetime | None = None  # defaults to now; naive = UAE time
    rows: list[AudienceRowIn]

    @field_validator("captured_at")
    @classmethod
    def _uae_default(cls, v: datetime | None) -> datetime | None:
        return from_uae_local(v) if v else None

METRIC_FIELDS = [
    "impressions",
    "members_reached",
    "clicks",
    "reactions",
    "comments",
    "reposts",
    "video_views",
    "poll_votes",
    "newsletter_views",
    "newsletter_subscribers",
    "followers_gained",
]

"""Request bodies for the publishing queue (planned posts)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.common.timeutil import from_uae_local

PlannedFormat = Literal["text", "image", "carousel", "video", "article", "poll"]

class CarouselSlide(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headline: str = Field(default="", max_length=120)
    body: str = Field(default="", max_length=400)

class PlannedDetails(BaseModel):
    """Format-specific fields. Only the ones that belong to the post's format are kept."""

    model_config = ConfigDict(extra="forbid")

    # carousel
    document_title: str | None = Field(default=None, max_length=100)
    # carousel built in the app: the slides and their look (the PDF itself is made in the browser and uploaded as media)
    slides: list[CarouselSlide] | None = Field(default=None, max_length=20)
    carousel_theme: Literal["brand", "dark", "light"] | None = None
    carousel_accent: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    # video
    subtitles: bool | None = None
    # article / newsletter
    title: str | None = Field(default=None, max_length=150)
    link: str | None = Field(default=None, max_length=500, pattern=r"^https?://\S+$")
    # poll (LinkedIn: question up to 140 characters, 2-4 options of up to 30 characters)
    question: str | None = Field(default=None, max_length=140)
    options: list[str] | None = None
    duration: Literal["1d", "3d", "1w", "2w"] | None = None

    @field_validator("options")
    @classmethod
    def _options(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        v = [o.strip() for o in v if o.strip()]
        if not 2 <= len(v) <= 4:
            raise ValueError("A poll needs 2 to 4 options")
        if any(len(o) > 30 for o in v):
            raise ValueError("Each poll option can be at most 30 characters")
        return v

FORMAT_DETAIL_FIELDS = {
    "text": set(),
    "image": set(),
    "carousel": {"document_title", "slides", "carousel_theme", "carousel_accent"},
    "video": {"subtitles"},
    "article": {"title", "link"},
    "poll": {"question", "options", "duration"},
}

class PlannedPostIn(BaseModel):
    account_id: int
    format: PlannedFormat = "text"
    details: PlannedDetails = Field(default_factory=PlannedDetails)
    caption: str = Field(min_length=1, max_length=3000)  # LinkedIn's post text limit
    image_alt: str | None = Field(default=None, max_length=300)
    visibility: Literal["PUBLIC", "CONNECTIONS"] = "PUBLIC"
    # Naive = UAE time. None = not scheduled (publish manually)
    scheduled_at: datetime | None = None
    # Required: what the post aims for (Brand awareness, Leads, Sales or Engagement)
    goal: Literal["brand", "sales", "engagement"]
    topic: str | None = Field(default=None, max_length=200)
    industry: str | None = Field(default=None, max_length=200)
    cta: str | None = Field(default=None, max_length=300)
    keywords: list[str] = []

    @field_validator("scheduled_at")
    @classmethod
    def _uae_default(cls, v: datetime | None) -> datetime | None:
        return from_uae_local(v) if v else None

    @field_validator("topic", "industry", "cta", "image_alt")
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None

    @model_validator(mode="after")
    def _details_for_format(self) -> "PlannedPostIn":
        if self.format == "poll" and (not self.details.question or not self.details.options):
            raise ValueError("A poll needs a question and 2 to 4 options")
        return self

    def stored_details(self) -> dict:
        """Only the fields that belong to this format, without empty values."""
        keep = FORMAT_DETAIL_FIELDS[self.format]
        return {k: v for k, v in self.details.model_dump().items() if k in keep and v not in (None, "", [])}


class MarkPostedIn(BaseModel):
    post_url: str = Field(min_length=10, max_length=500)

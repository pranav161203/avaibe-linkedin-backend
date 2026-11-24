"""Request bodies for leads."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Source = Literal["company_post", "founder_post", "company_page", "founder_profile", "website", "referral", "event", "other"]

Stage = Literal["new", "talking", "proposal", "won", "lost"]

class LeadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: int
    received_on: date
    source: Source
    post_id: int | None = None
    via_account_id: int | None = None
    company: str = Field(min_length=1, max_length=200)
    industry: str | None = Field(default=None, max_length=120)
    in_uae: bool | None = None
    role: str | None = Field(default=None, max_length=120)
    decision_maker: bool | None = None
    service: str | None = Field(default=None, max_length=120)
    stage: Stage = "new"
    value_aed: Decimal | None = Field(default=None, ge=0, le=Decimal("999999999999"))
    closed_on: date | None = None
    notes: str | None = Field(default=None, max_length=2000)
    how_heard: str | None = Field(default=None, max_length=300)
    utm_source: str | None = Field(default=None, max_length=100)
    utm_medium: str | None = Field(default=None, max_length=100)
    utm_campaign: str | None = Field(default=None, max_length=100)
    replied_at: datetime | None = None
    qualified: bool | None = None  # None = use the default rule (UAE-based decision-maker)

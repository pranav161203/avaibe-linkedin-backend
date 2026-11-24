"""Request bodies for accounts, page audience and account documents (checklist, competitors, member totals)."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.schemas.common import Dimension

AccountKind = Literal["company", "founder", "personal"]

class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: AccountKind
    linkedin_url: str | None = Field(default=None, max_length=500)
    is_test: bool = False

class AccountOut(AccountIn):
    model_config = ConfigDict(from_attributes=True)
    id: int

class PageAudienceRowIn(BaseModel):
    dimension: Dimension
    value: str = Field(min_length=1, max_length=200)
    count: int | None = Field(default=None, ge=0)
    pct: float | None = Field(default=None, ge=0, le=100)

class PageAudienceIn(BaseModel):
    as_of: date
    audience: Literal["followers", "visitors"]
    total: int | None = Field(default=None, ge=0)
    rows: list[PageAudienceRowIn]


URL = r"^https?://\S+$"

class ChecklistItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    done: bool = False
    note: str | None = Field(default=None, max_length=300)

class PageChecklist(BaseModel):
    """Ticks and notes, keyed by the item ids the page shows (the item wording lives in the app)."""

    model_config = ConfigDict(extra="forbid")
    items: dict[str, ChecklistItem] = Field(default_factory=dict, max_length=60)

class Competitor(BaseModel):
    """Public, observed facts kept apart from AVAIBE's own interpretation."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    name: str = Field(min_length=1, max_length=120)
    segment: Literal["software", "erp", "edtech", "it_services", "agency", "other"] = "other"
    website: str | None = Field(default=None, max_length=300, pattern=URL)
    linkedin_url: str | None = Field(default=None, max_length=300, pattern=URL)
    # Observed (public)
    followers: int | None = Field(default=None, ge=0, le=100_000_000)
    posts_per_week: float | None = Field(default=None, ge=0, le=100)
    topics: str | None = Field(default=None, max_length=400)
    positioning: str | None = Field(default=None, max_length=600)
    # Interpretation (ours)
    strengths: str | None = Field(default=None, max_length=600)
    opportunity: str | None = Field(default=None, max_length=600)
    checked_on: date | None = None

class Competitors(BaseModel):
    model_config = ConfigDict(extra="forbid")
    competitors: list[Competitor] = Field(default_factory=list, max_length=40)

class MemberTotals(BaseModel):
    """A founder's totals across ALL their posts (LinkedIn's q=me analytics), written by the sync."""

    model_config = ConfigDict(extra="forbid")
    as_of: date | None = None
    followers: int | None = None
    totals: dict[str, int] = Field(default_factory=dict, max_length=20)

KINDS: dict[str, type[BaseModel]] = {"page_checklist": PageChecklist, "competitors": Competitors, "member_totals": MemberTotals}

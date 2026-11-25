"""Editable Settings sections, kept per company: audience definitions ("segments"), performance rules
("performance") and the brand kit ("brand"). Stored in company_settings and cached in memory for a short time.
Defaults apply until a company changes a section.

Which company: an explicit company_id, or else the company of the request being served. That is set from the
signed-in person's company, and narrowed to the account's company whenever an endpoint checks an account
(core.auth.permissions.check_account), so analytics code can call get() without passing the company around.

The cache refreshes every CACHE_SECONDS so several server processes stay in step."""

import time
from contextvars import ContextVar
from copy import deepcopy
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from core.models import Company, CompanySetting
from core.services.auth.audit import stamp

CACHE_SECONDS = 30
DEFAULTS: dict[str, dict[str, Any]] = {
    "segments": {
        # Location values containing these words count as UAE
        "uae_country": ["united arab emirates", "uae"],
        "uae_cities": [
            "dubai", "abu dhabi", "sharjah", "ajman", "ras al khaimah", "fujairah", "umm al quwain", "al ain",
        ],
        # LinkedIn industry names containing these words count as education
        "education_industry": ["education", "e-learning", "school"],
        # LinkedIn seniority levels that count as decision-makers
        "decision_seniority": ["owner", "partner", "cxo", "vp", "director"],
        # Fallback when only job titles are available
        "decision_titles": [
            "ceo", "founder", "owner", "principal", "head of school", "director", "managing director",
            "general manager", "cto", "cio", "chairman", "president",
        ],
        # LinkedIn job functions that count as technology professionals (CTOs, IT managers, engineers, consultants)
        "tech_functions": ["engineering", "information technology"],
        # LinkedIn job functions that count as potential partners (consultants, business development, agencies)
        "partner_functions": ["business development", "consulting"],
    },
    "performance": {
        "min_history": 8,  # posts needed before labelling against a baseline
        "min_slot_posts": 3,  # posts needed in a day/time cell before it can be suggested
        # Percentile cut-offs within the account's own history
        "cut_high": 0.90,
        "cut_above": 0.65,
        "cut_average": 0.35,
        "cut_below": 0.10,
        "trend_threshold": 0.10,  # change vs previous period that counts as improving/declining
    },
    "brand": {
        # What Claude needs to know about the company (edited in Settings → Claude). Empty until the company fills it in.
        "company_summary": "",
        "website": "",
        "services": [],
        "target_segments": [],
        "differentiators": [],
        "proof_points": [],
        "voice": "Professional, practical and UAE-aware. Plain English, specific examples, no hype or buzzwords.",
        "avoid": [
            "Claims that can't be verified",
            "Naming clients or results without written permission",
            "Spammy or mass outreach, engagement bait",
        ],
        "competitors": [],
        "languages": ["English"],
    },
}


# ------------------------------------------------------------------ validation

def _clean(items: list[str]) -> list[str]:
    out: list[str] = []
    for s in items:
        s = s.strip().lower()
        if s and s not in out:
            out.append(s)
    return out


class SegmentsIn(BaseModel):
    uae_country: list[str] = Field(max_length=100)
    uae_cities: list[str] = Field(max_length=100)
    education_industry: list[str] = Field(min_length=1, max_length=100)
    decision_seniority: list[str] = Field(max_length=100)
    decision_titles: list[str] = Field(max_length=100)
    tech_functions: list[str] = Field(default_factory=lambda: ["engineering", "information technology"], max_length=100)
    partner_functions: list[str] = Field(default_factory=lambda: ["business development", "consulting"], max_length=100)

    @field_validator("*")
    @classmethod
    def _items(cls, v: list[str]) -> list[str]:
        if any(len(s) > 100 for s in v):
            raise ValueError("Each entry must be 100 characters or fewer")
        return _clean(v)

    @model_validator(mode="after")
    def _non_empty(self):
        if not self.uae_country and not self.uae_cities:
            raise ValueError("Add at least one UAE country or city keyword")
        if not self.education_industry:
            raise ValueError("Add at least one education keyword")
        if not self.decision_seniority and not self.decision_titles:
            raise ValueError("Add at least one decision-maker seniority or job-title keyword")
        return self


class PerformanceIn(BaseModel):
    min_history: int = Field(ge=3, le=200)
    min_slot_posts: int = Field(ge=1, le=50)
    cut_high: float = Field(gt=0, lt=1)
    cut_above: float = Field(gt=0, lt=1)
    cut_average: float = Field(gt=0, lt=1)
    cut_below: float = Field(gt=0, lt=1)
    trend_threshold: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _descending(self):
        if not (self.cut_high > self.cut_above > self.cut_average > self.cut_below):
            raise ValueError("Thresholds must decrease: High performer > Above average > Average > Below average")
        return self


def _clean_lines(items: list[str], max_len: int = 400) -> list[str]:
    out: list[str] = []
    for s in items:
        s = s.strip()
        if s and s not in out:
            if len(s) > max_len:
                raise ValueError(f"each entry must be {max_len} characters or fewer")
            out.append(s)
    return out


class BrandIn(BaseModel):
    company_summary: str = Field(default="", max_length=1500)
    website: str = Field(default="", max_length=300)
    services: list[str] = Field(default_factory=list, max_length=40)
    target_segments: list[str] = Field(default_factory=list, max_length=20)
    differentiators: list[str] = Field(default_factory=list, max_length=20)
    proof_points: list[str] = Field(default_factory=list, max_length=30)
    voice: str = Field(default="", max_length=1000)
    avoid: list[str] = Field(default_factory=list, max_length=30)
    competitors: list[str] = Field(default_factory=list, max_length=30)
    languages: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("services", "target_segments", "differentiators", "proof_points", "avoid", "competitors", "languages")
    @classmethod
    def _lines(cls, v: list[str]) -> list[str]:
        return _clean_lines(v)

    @field_validator("company_summary", "website", "voice")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


VALIDATORS = {"segments": SegmentsIn, "performance": PerformanceIn, "brand": BrandIn}


# ------------------------------------------------------------------ which company

_company: ContextVar[int | None] = ContextVar("settings_company", default=None)


def use_company(company_id: int | None) -> None:
    """Set the company for the rest of this request (reset at the start of each request by the middleware)."""
    _company.set(company_id)


def current_company() -> int | None:
    return _company.get()


_only_company: tuple[float, int | None] = (0.0, None)


def _resolve(company_id: int | None) -> int | None:
    """Explicit id, else the request's company, else the only company if there is exactly one (scripts, owners
    on a page with no account). None means defaults."""
    global _only_company
    if company_id is not None:
        return company_id
    if (cid := _company.get()) is not None:
        return cid
    loaded, cid = _only_company
    if time.monotonic() - loaded >= CACHE_SECONDS:
        try:
            ids = list(Company.objects.values_list("id", flat=True)[:2])
        except Exception:  # table missing (before migrate) or DB unavailable
            ids = []
        cid = ids[0] if len(ids) == 1 else None
        _only_company = (time.monotonic(), cid)
    return cid


# ------------------------------------------------------------------ reading and writing

_cache: dict[int | None, tuple[float, dict[str, dict[str, Any]]]] = {}


def _load(company_id: int | None, force: bool = False) -> dict[str, dict[str, Any]]:
    hit = _cache.get(company_id)
    if hit and not force and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    fresh = deepcopy(DEFAULTS)
    if company_id is not None:
        try:
            for row in CompanySetting.objects.filter(company_id=company_id):
                if row.section in fresh:
                    fresh[row.section].update({k: v for k, v in (row.value or {}).items() if k in fresh[row.section]})
        except Exception:  # table missing (before migrate) or DB unavailable: fall back to defaults
            pass
    _cache[company_id] = (time.monotonic(), fresh)
    return fresh


def get(section: str, company_id: int | None = None) -> dict[str, Any]:
    return _load(_resolve(company_id))[section]


def all_settings(company_id: int | None = None) -> dict[str, Any]:
    return {k: deepcopy(v) for k, v in _load(_resolve(company_id)).items()}


def save(section: str, value: dict[str, Any], company_id: int, actor_id: int | None = None) -> dict[str, Any]:
    """Validate, persist and cache one section for one company. Raises pydantic.ValidationError on bad input."""
    clean = VALIDATORS[section](**value).model_dump()
    row = CompanySetting.objects.filter(company_id=company_id, section=section).first()
    created = row is None
    if created:
        row = CompanySetting(company_id=company_id, section=section)
    row.value = clean
    stamp(row, actor_id, created=created)
    row.save()
    return _load(company_id, force=True)[section]


def reset(section: str, company_id: int) -> dict[str, Any]:
    CompanySetting.objects.filter(company_id=company_id, section=section).delete()
    return _load(company_id, force=True)[section]


def invalidate() -> None:
    """Force a reload on next access (used by tests and imports)."""
    global _only_company
    _cache.clear()
    _only_company = (0.0, None)

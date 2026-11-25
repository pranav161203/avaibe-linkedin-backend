"""Editable app settings (audience definitions, performance rules, access defaults), stored in the
database and cached in memory for a short time. Code reads them through get(); the Settings page
writes them through save(). Defaults apply until someone changes a value.

The cache refreshes every CACHE_SECONDS so several server processes stay in step."""

import time
from copy import deepcopy
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from core.models import AppSetting

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
        # What Claude needs to be creative about AVAIBE specifically (edited in Settings → Brand & knowledge)
        "company_summary": "AVAIBE is a UAE-based software company building custom software, ERP and education technology (LMS and school systems).",
        "website": "https://avaibe.com",
        "services": [],
        "target_segments": [
            "UAE decision-makers: CEOs, founders, school principals, directors, business owners",
            "Technology professionals: CTOs, IT managers, developers, consultants",
            "Potential partners: consultants, technology partners, agencies",
        ],
        "differentiators": [],
        "proof_points": [
            "Client logos shown publicly on avaibe.com: Next Generation School, CyberDisti, Alrajhi Education Management, Marathon Education UK, Costain Process Engineering & Technical LLC, American Islamic School (name clients in posts only with their permission)",
        ],
        "voice": "Professional, practical and UAE-aware. Plain English, specific examples, no hype or buzzwords.",
        "avoid": [
            "Claims that can't be verified",
            "Naming clients or results without written permission",
            "Spammy or mass outreach, engagement bait",
        ],
        "competitors": [],
        "languages": ["English"],
    },
    "access": {
        # The only account people WITHOUT "can switch accounts" can see. None = first company page.
        "default_account_id": None,
    },
}

_cache: dict[str, dict[str, Any]] = deepcopy(DEFAULTS)


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


class AccessIn(BaseModel):
    default_account_id: int | None = Field(default=None, ge=1)


VALIDATORS = {"segments": SegmentsIn, "performance": PerformanceIn, "access": AccessIn, "brand": BrandIn}


# ------------------------------------------------------------------ access

_loaded_at = 0.0


def _refresh(force: bool = False) -> None:
    global _loaded_at
    if not force and time.monotonic() - _loaded_at < CACHE_SECONDS:
        return
    fresh = deepcopy(DEFAULTS)
    try:
        for row in AppSetting.objects.all():
            if row.key in fresh:
                fresh[row.key].update({k: v for k, v in (row.value or {}).items() if k in fresh[row.key]})
    except Exception:  # table missing (before migrate) or DB unavailable: fall back to defaults
        pass
    _cache.clear()
    _cache.update(fresh)
    _loaded_at = time.monotonic()


def get(section: str) -> dict[str, Any]:
    _refresh()
    return _cache[section]


def all_settings() -> dict[str, Any]:
    _refresh()
    return {k: deepcopy(v) for k, v in _cache.items()}


def save(section: str, value: dict[str, Any]) -> dict[str, Any]:
    """Validate, persist and cache one section. Raises pydantic.ValidationError on bad input."""
    clean = VALIDATORS[section](**value).model_dump()
    AppSetting.objects.update_or_create(key=section, defaults={"value": clean})
    _refresh(force=True)
    return _cache[section]


def reset(section: str) -> dict[str, Any]:
    AppSetting.objects.filter(key=section).delete()
    _refresh(force=True)
    return _cache[section]


def invalidate() -> None:
    """Force a reload on next access (used by tests)."""
    global _loaded_at
    _loaded_at = 0.0

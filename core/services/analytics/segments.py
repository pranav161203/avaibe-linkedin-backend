"""Target-audience definitions: who counts as "relevant" for AVAIBE.

The keyword lists are editable on the Settings page (see settings_store).
Values are matched case-insensitively as substrings of what LinkedIn shows
(e.g. "Dubai, United Arab Emirates" matches "dubai").

Shares are computed from LinkedIn's audience breakdowns, which list only the
top values. A share is therefore a LOWER BOUND, not an exact figure.
Each segment uses one dimension, so dimensions are never added together
(that would double-count the same viewers).
"""

from typing import Iterable

from core.services import settings_store

DIMENSIONS = ["location", "industry", "seniority", "job_title", "job_function", "company_size", "company"]


def _cfg() -> dict:
    return settings_store.get("segments")


def describe() -> dict[str, str]:
    c = _cfg()
    return {
        "uae": "Located in the UAE (country entry, or the sum of UAE city entries)",
        "education": f"Industry contains: {', '.join(c['education_industry'])}",
        "decision_maker": "Seniority matches the decision-maker list (or job title if no seniority data)",
        "tech": f"Job function contains: {', '.join(c.get('tech_functions', []))}",
        "partner": f"Job function contains: {', '.join(c.get('partner_functions', []))}",
    }


def _match(value: str, keywords: Iterable[str]) -> bool:
    v = value.lower()
    return any(k in v for k in keywords)


def _share(rows: list[tuple[str, str, float]], dimension: str, keywords: Iterable[str]) -> float | None:
    """rows: (dimension, value, share 0..1). None if the dimension wasn't recorded."""
    dim_rows = [(v, s) for d, v, s in rows if d == dimension]
    if not dim_rows:
        return None
    return min(1.0, sum(s for v, s in dim_rows if _match(v, keywords)))


def uae_share(rows: list[tuple[str, str, float]]) -> float | None:
    c = _cfg()
    loc = [(v, s) for d, v, s in rows if d == "location"]
    if not loc:
        return None
    # A country-level entry ("United Arab Emirates" alone) already includes its cities: use it alone to avoid
    # double counting. Places LinkedIn lists as "Town, United Arab Emirates" are cities, even if not on our list.
    country_names = {k.strip().lower() for k in c["uae_country"]}
    country = [s for v, s in loc if v.strip().lower() in country_names]
    if country:
        return min(1.0, max(country))
    return min(1.0, sum(s for v, s in loc if _match(v, c["uae_country"] + c["uae_cities"])))


def education_share(rows: list[tuple[str, str, float]]) -> float | None:
    return _share(rows, "industry", _cfg()["education_industry"])


def decision_maker_share(rows: list[tuple[str, str, float]]) -> float | None:
    c = _cfg()
    s = _share(rows, "seniority", c["decision_seniority"]) if c["decision_seniority"] else None
    return s if s is not None else _share(rows, "job_title", c["decision_titles"])


def tech_share(rows: list[tuple[str, str, float]]) -> float | None:
    return _share(rows, "job_function", _cfg().get("tech_functions", []))


def partner_share(rows: list[tuple[str, str, float]]) -> float | None:
    return _share(rows, "job_function", _cfg().get("partner_functions", []))


def all_shares(rows: list[tuple[str, str, float]]) -> dict[str, float | None]:
    return {
        "uae_share": uae_share(rows),
        "education_share": education_share(rows),
        "decision_maker_share": decision_maker_share(rows),
        # The other audience groups AVAIBE tracks (by job function); groups overlap, so they don't add up to 100%
        "tech_share": tech_share(rows),
        "partner_share": partner_share(rows),
    }

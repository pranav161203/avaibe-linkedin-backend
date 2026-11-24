"""Dates the content calendar shows: holidays, special periods, events and awareness days.

Checked on 2026-11-18 against UAE government announcements (MoHRE / FAHR / MoE) as reported by
Gulf News, Khaleej Times and The National, and India holiday lists. Islamic holidays depend on the
moon sighting: dates in the future are "expected" until the UAE confirms them (usually days before).
Edit this list when a date is confirmed or the team wants another event.

kind: uae_holiday | india_holiday | period | event | awareness | business
status: confirmed | expected
"""

from datetime import date
from typing import Any

_E = list[dict[str, Any]]


def _d(s: str) -> date:
    return date.fromisoformat(s)


# (start, end inclusive, title, kind, status, note)
_ITEMS: list[tuple[str, str, str, str, str, str]] = [
    # ---- UAE public holidays ----
    ("2025-12-01", "2025-12-01", "Commemoration Day", "uae_holiday", "confirmed", "Honours the UAE's martyrs"),
    ("2025-12-02", "2025-12-03", "UAE National Day (Eid Al Etihad)", "uae_holiday", "confirmed", ""),
    ("2026-01-01", "2026-01-01", "New Year's Day", "uae_holiday", "confirmed", ""),
    ("2026-03-19", "2026-03-22", "Eid Al Fitr holiday", "uae_holiday", "confirmed", "Eid was on 20 March; Ramadan ran the full 30 days"),
    ("2026-05-26", "2026-05-26", "Arafat Day", "uae_holiday", "confirmed", ""),
    ("2026-05-27", "2026-05-29", "Eid Al Adha", "uae_holiday", "confirmed", "Private sector off 26–29 May; back on 1 June"),
    ("2026-06-15", "2026-06-15", "Hijri New Year (1448)", "uae_holiday", "confirmed", ""),
    ("2026-08-28", "2026-08-28", "Prophet Muhammad's Birthday (holiday)", "uae_holiday", "confirmed", "The birthday was Tue 25 Aug; the holiday was moved to Friday"),
    ("2026-12-01", "2026-12-01", "Commemoration Day", "uae_holiday", "expected", "Check the official announcement"),
    ("2026-12-02", "2026-12-03", "UAE National Day (Eid Al Etihad)", "uae_holiday", "expected", "Fixed dates; the government may add days"),
    ("2027-01-01", "2027-01-01", "New Year's Day", "uae_holiday", "confirmed", ""),
    ("2027-03-09", "2027-03-11", "Eid Al Fitr holiday", "uae_holiday", "expected", "Depends on the moon sighting; may run to 12 March"),
    ("2027-05-15", "2027-05-15", "Arafat Day", "uae_holiday", "expected", "Depends on the moon sighting"),
    ("2027-05-16", "2027-05-18", "Eid Al Adha", "uae_holiday", "expected", "Depends on the moon sighting"),
    ("2027-06-06", "2027-06-06", "Hijri New Year (1449)", "uae_holiday", "expected", "Depends on the moon sighting; the holiday may be moved"),
    ("2027-08-14", "2027-08-14", "Prophet Muhammad's Birthday", "uae_holiday", "expected", "The holiday may be moved to the start or end of a week"),
    ("2027-12-02", "2027-12-03", "UAE National Day (Eid Al Etihad)", "uae_holiday", "expected", ""),
    # ---- India (most of today's followers are in India) ----
    ("2025-12-25", "2025-12-25", "Christmas", "india_holiday", "confirmed", ""),
    ("2026-01-14", "2026-01-14", "Pongal / Makar Sankranti", "india_holiday", "confirmed", "Regional: Tamil Nadu and others"),
    ("2026-01-26", "2026-01-26", "Republic Day", "india_holiday", "confirmed", "National"),
    ("2026-03-04", "2026-03-04", "Holi", "india_holiday", "confirmed", "Mainly north India"),
    ("2026-08-15", "2026-08-15", "Independence Day", "india_holiday", "confirmed", "National"),
    ("2026-08-26", "2026-08-26", "Onam (Thiruvonam)", "india_holiday", "confirmed", "Regional: Kerala"),
    ("2026-10-02", "2026-10-02", "Gandhi Jayanti", "india_holiday", "confirmed", "National"),
    ("2026-10-20", "2026-10-20", "Dussehra", "india_holiday", "confirmed", ""),
    ("2026-11-08", "2026-11-08", "Diwali", "india_holiday", "confirmed", "Many people take the surrounding days off"),
    ("2026-12-25", "2026-12-25", "Christmas", "india_holiday", "confirmed", ""),
    ("2027-01-15", "2027-01-15", "Pongal / Makar Sankranti", "india_holiday", "expected", "Some lists give 14 January"),
    ("2027-01-26", "2027-01-26", "Republic Day", "india_holiday", "confirmed", "National"),
    ("2027-03-22", "2027-03-22", "Holi", "india_holiday", "expected", "Some lists give 23 March"),
    ("2027-08-15", "2027-08-15", "Independence Day", "india_holiday", "confirmed", "National"),
    ("2027-09-12", "2027-09-12", "Onam (Thiruvonam)", "india_holiday", "expected", "Regional: Kerala"),
    ("2027-10-02", "2027-10-02", "Gandhi Jayanti", "india_holiday", "confirmed", "National"),
    ("2027-10-09", "2027-10-09", "Dussehra", "india_holiday", "expected", ""),
    ("2027-10-29", "2027-10-29", "Diwali", "india_holiday", "expected", ""),
    ("2027-12-25", "2027-12-25", "Christmas", "india_holiday", "confirmed", ""),
    # ---- Special periods ----
    ("2026-02-18", "2026-03-19", "Ramadan", "period", "confirmed", "Shorter working hours; people are online later in the evening"),
    ("2027-02-08", "2027-03-09", "Ramadan", "period", "expected", "Depends on the moon sighting"),
    ("2026-07-01", "2026-08-31", "UAE summer", "period", "confirmed", "Many residents travel; activity is usually lower"),
    ("2027-07-01", "2027-08-31", "UAE summer", "period", "confirmed", "Many residents travel; activity is usually lower"),
    ("2025-12-08", "2026-01-04", "UAE school winter break", "period", "confirmed", "MoE calendar 2025–26; some private schools differ"),
    ("2026-03-16", "2026-03-29", "UAE school spring break", "period", "confirmed", "MoE calendar 2025–26; some private schools differ"),
    ("2026-07-03", "2026-08-30", "UAE school summer break", "period", "confirmed", "Classes resumed on 31 August"),
    ("2026-10-12", "2026-10-18", "UAE school mid-term break", "period", "confirmed", "MoE calendar 2026–27"),
    ("2026-12-14", "2027-01-03", "UAE school winter break", "period", "confirmed", "MoE calendar 2026–27"),
    ("2027-04-05", "2027-04-11", "UAE school spring break", "period", "confirmed", "MoE calendar 2026–27"),
    ("2027-07-03", "2027-08-31", "UAE school summer break", "period", "expected", "The 2026–27 school year ends on 2 July"),
    # ---- Industry events ----
    ("2026-11-10", "2026-11-12", "GESS Dubai (education)", "event", "confirmed", "Dubai World Trade Centre: schools, edtech, LMS"),
    ("2026-12-07", "2026-12-11", "GITEX Global", "event", "confirmed", "Moved to December and to Expo City Dubai this year"),
    # ---- Awareness days worth a post ----
    ("2026-01-24", "2026-01-24", "International Day of Education", "awareness", "confirmed", ""),
    ("2026-02-10", "2026-02-10", "Safer Internet Day", "awareness", "confirmed", "Second Tuesday of February"),
    ("2026-03-08", "2026-03-08", "International Women's Day", "awareness", "confirmed", ""),
    ("2026-08-28", "2026-08-28", "Emirati Women's Day", "awareness", "confirmed", ""),
    ("2026-10-01", "2026-10-31", "Cybersecurity Awareness Month", "awareness", "confirmed", ""),
    ("2026-10-05", "2026-10-05", "World Teachers' Day", "awareness", "confirmed", ""),
    ("2026-11-03", "2026-11-03", "UAE Flag Day", "awareness", "confirmed", ""),
    ("2027-01-24", "2027-01-24", "International Day of Education", "awareness", "confirmed", ""),
    ("2027-02-09", "2027-02-09", "Safer Internet Day", "awareness", "confirmed", "Second Tuesday of February"),
    ("2027-03-08", "2027-03-08", "International Women's Day", "awareness", "confirmed", ""),
    ("2027-08-28", "2027-08-28", "Emirati Women's Day", "awareness", "confirmed", ""),
    ("2027-10-01", "2027-10-31", "Cybersecurity Awareness Month", "awareness", "confirmed", ""),
    ("2027-10-05", "2027-10-05", "World Teachers' Day", "awareness", "confirmed", ""),
    ("2027-11-03", "2027-11-03", "UAE Flag Day", "awareness", "confirmed", ""),
]

# Business dates that make good hooks for ERP / finance content: UAE quarter ends
# (VAT returns for quarterly filers are due 28 days after the tax period ends; periods vary by business)
_QUARTER_ENDS = ["2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30", "2026-12-31", "2027-03-31", "2027-06-30", "2027-09-30", "2027-12-31"]


def all_items() -> _E:
    out: _E = []
    for start, end, title, kind, status, note in _ITEMS:
        out.append({"start": start, "end": end, "title": title, "kind": kind, "status": status, "note": note})
    for q in _QUARTER_ENDS:
        out.append({"start": q, "end": q, "title": "Quarter end", "kind": "business", "status": "confirmed",
                    "note": "Many UAE businesses close their books; quarterly VAT returns follow within 28 days"})
    return out


def items_between(start: date, end: date) -> _E:
    """Every item overlapping start..end (inclusive)."""
    return [i for i in all_items() if _d(i["start"]) <= end and _d(i["end"]) >= start]


def labels_for(day: date) -> list[str]:
    """Kinds active on one day (used to describe how a date differs from a normal working day)."""
    return [i["kind"] for i in all_items() if _d(i["start"]) <= day <= _d(i["end"])]


def covered_years() -> tuple[int, int]:
    days = [_d(i["start"]) for i in all_items()]
    return min(days).year, max(days).year


__all__ = ["all_items", "items_between", "labels_for", "covered_years"]

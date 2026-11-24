"""Content calendar: the posts (tracked and planned) and timing advice for a date range, across related accounts.

Dates (holidays, events) come from calendar_data.py.
"""

from collections import defaultdict
from datetime import date, timedelta
from statistics import median
from typing import Any

from core.common.timeutil import as_utc, to_uae
from core.models import CHECKPOINT_HOURS, Account
from core.services.analytics import performance as a
from core.services.analytics import timing

MIN_TYPICAL = 5  # posts needed at the same age before "vs typical" is shown (same rule as the Posts page)

def title(caption: str | None) -> str:
    line = next((ln.strip() for ln in (caption or "").splitlines() if ln.strip()), "")
    return line[:120] or "(no caption)"

def related(account: Account, allowed: set[int]) -> list[Account]:
    """The account itself, plus the founders linked to a company page (or the page and fellow founders of a profile)."""
    root = account.parent or account
    group = [root, *root.profiles.all()]
    seen, out = set(), []
    for acc in [account, *group]:
        if acc.id not in seen and acc.id in allowed:
            seen.add(acc.id)
            out.append(acc)
    return out

def _latest(snaps):
    return max(snaps, key=lambda s: CHECKPOINT_HOURS[s.checkpoint], default=None)

def posts_for(acc: Account, start: date, end: date) -> list[dict[str, Any]]:
    posts = a.load_posts(acc.id)
    # The typical post at each age, from ALL of this account's posts (not only the visible month)
    by_cp: dict[str, list[float]] = defaultdict(list)
    for p in posts:
        s = _latest(p.snapshots)
        if s and s.impressions is not None:
            by_cp[s.checkpoint].append(s.impressions)
    out = []
    for p in posts:
        local = to_uae(as_utc(p.published_at))
        if not start <= local.date() <= end:
            continue
        s = _latest(p.snapshots)
        peers = by_cp.get(s.checkpoint, []) if s else []
        typical = median(peers) if len(peers) >= MIN_TYPICAL else None
        imp = s.impressions if s else None
        out.append(
            {
                "id": p.id,
                "ref": p.ref,
                "account_id": acc.id,
                "account_name": acc.name,
                "account_kind": acc.kind,
                "date": local.date().isoformat(),
                "time": local.strftime("%H:%M") if p.time_known else None,
                "format": p.format,
                "title": title(p.caption),
                "impressions": imp,
                "checkpoint": s.checkpoint if s else None,
                "vs_typical": round(imp / typical, 2) if imp is not None and typical else None,
            }
        )
    return out

def timing_advice(posts, start: date, end: date) -> dict[str, Any]:
    """Per date, from the posting-time model (timing.py): best slot, how the date compares with a normal day,
    a slot worth testing, and whether the model has proven itself on newer posts (backtest)."""
    m, n = timing.model_for(posts)
    if m is None:
        return {"ready": False, "posts_used": n,
                "reason": f"The time model needs at least {timing.MIN_POSTS} past posts with a known posting time (has {n})."}
    need = a.min_slot_posts()
    bt = timing.backtest_verdict(posts)
    special = {k: timing._effect(m, k, m.special.get(k, 0.0), m.n_special.get(k, 0), label)
               for k, label in timing.SPECIAL.items()}
    days = {}
    d = start
    while d <= end:
        days[d.isoformat()] = timing.recommend(m, d, need)
        d += timedelta(days=1)
    return {"ready": True, "posts_used": n, "backtest": bt, "special": special, "days": days}

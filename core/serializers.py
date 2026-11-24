"""Turn ORM objects into API dictionaries, adding derived fields
(UAE/India time, time slot, engagement and click rates)."""

from typing import Any

from core.common.timeutil import as_utc, slot_label, to_ist, to_uae
from core.models import CHECKPOINT_HOURS, PageAudience, Post, Snapshot
from core.schemas.posts import METRIC_FIELDS
from core.services.analytics import segments


def engagements(s: Snapshot) -> int | None:
    """Reactions + comments + reposts + clicks. None if none were recorded."""
    parts = [s.reactions, s.comments, s.reposts, s.clicks]
    if all(p is None for p in parts):
        return None
    return sum(p or 0 for p in parts)


def engagement_rate(s: Snapshot) -> float | None:
    e = engagements(s)
    if e is None or not s.impressions:
        return None
    return e / s.impressions


def click_rate(s: Snapshot) -> float | None:
    if s.clicks is None or not s.impressions:
        return None
    return s.clicks / s.impressions


def snapshot_out(s: Snapshot) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": s.id,
        "post_id": s.post_id,
        "checkpoint": s.checkpoint,
        "captured_at": as_utc(s.captured_at).isoformat(),
        "notes": s.notes,
        "engagements": engagements(s),
        "engagement_rate": engagement_rate(s),
        "click_rate": click_rate(s),
    }
    for f in METRIC_FIELDS:
        out[f] = getattr(s, f)
    # From LinkedIn's member (founder) analytics only; read-only, not entered by hand
    for f in ("saves", "sends", "profile_views"):
        out[f] = getattr(s, f)
    return out


def post_summary(p: Post) -> dict[str, Any]:
    uae = to_uae(p.published_at)
    return {
        "id": p.id,
        "ref": p.ref,
        "account_id": p.account_id,
        "post_url": p.post_url,
        "linkedin_post_id": p.linkedin_post_id,
        "author": p.author,
        "published_at": as_utc(p.published_at).isoformat(),
        "published_at_uae": uae.strftime("%Y-%m-%d %H:%M"),
        "published_at_ist": to_ist(p.published_at).strftime("%Y-%m-%d %H:%M"),
        "day_uae": uae.strftime("%A"),
        "slot_uae": slot_label(uae) if p.time_known else None,
        "time_known": p.time_known,
        "targeted": p.targeted,
        "format": p.format,
        "topic": p.topic,
        "topic_suggested": p.topic_suggested,
        "goal": p.goal,
        "industry": p.industry,
        "keywords": p.keywords or [],
        "cta": p.cta,
        "hashtags": p.hashtags or [],
        "caption": p.caption,
        "notes": p.notes,
    }


def audience_tuples(p: Post) -> list[tuple[str, str, float]]:
    return [(a.dimension, a.value, a.pct / 100) for a in p.audience]


def post_shares(p: Post) -> dict[str, float | None]:
    return segments.all_shares(audience_tuples(p))


def post_out(p: Post) -> dict[str, Any]:
    out = post_summary(p)
    snaps = sorted(p.snapshots, key=lambda s: CHECKPOINT_HOURS[s.checkpoint])
    out["snapshots"] = [snapshot_out(s) for s in snaps]
    out["audience"] = [
        {"dimension": a.dimension, "value": a.value, "pct": a.pct}
        for a in sorted(p.audience, key=lambda a: (a.dimension, -a.pct))
    ]
    out["audience_captured_at"] = (
        as_utc(max(a.captured_at for a in p.audience)).isoformat() if p.audience else None
    )
    out["shares"] = post_shares(p)
    return out


def page_audience_shares(rows: list[PageAudience]) -> dict[str, float | None]:
    """Shares for one page snapshot. Uses count/total when both exist, else pct."""
    tuples = []
    for r in rows:
        if r.count is not None and r.total:
            share = r.count / r.total
        elif r.pct is not None:
            share = r.pct / 100
        else:
            continue
        tuples.append((r.dimension, r.value, share))
    return segments.all_shares(tuples)

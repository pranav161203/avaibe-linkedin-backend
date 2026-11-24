"""Analytics over stored posts and snapshots.

Principles (from AGENTS.md / the assignment brief):
- Compare posts at the SAME checkpoint (e.g. all at 24h), never mixed ages.
- Use medians, not averages.
- Classify against AVAIBE's own history, per format where there is enough data.
- Never crown a time slot on fewer than min_slot_posts() posts.
- All thresholds are editable on the Settings page (settings_store).
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cached_property
from statistics import median
from typing import Any

from django.db.models import Prefetch

from core.common.timeutil import DAYS, SLOT_LABELS, as_utc, now_utc, slot_label, to_uae
from core.models import CHECKPOINT_HOURS, FORMATS, Post, PostAudience, Snapshot
from core.serializers import (
    click_rate,
    engagement_rate,
    engagements,
    post_shares,
    post_summary,
)
from core.services import settings_store


# Thresholds are editable on the Settings page (settings_store "performance")
def min_history() -> int:
    return settings_store.get("performance")["min_history"]


def min_slot_posts() -> int:
    return settings_store.get("performance")["min_slot_posts"]


def labels() -> list[tuple[float, str]]:
    p = settings_store.get("performance")
    return [
        (p["cut_high"], "High performer"),
        (p["cut_above"], "Above average"),
        (p["cut_average"], "Average"),
        (p["cut_below"], "Below average"),
        (0.0, "Needs investigation"),
    ]


METRICS: dict[str, Callable[[Snapshot], float | None]] = {
    "impressions": lambda s: s.impressions,
    "members_reached": lambda s: s.members_reached,
    "engagements": engagements,
    "engagement_rate": engagement_rate,
    "click_rate": click_rate,
    "clicks": lambda s: s.clicks,
    "reactions": lambda s: s.reactions,
    "comments": lambda s: s.comments,
    "reposts": lambda s: s.reposts,
    "video_views": lambda s: s.video_views,
    "poll_votes": lambda s: s.poll_votes,
    "newsletter_views": lambda s: s.newsletter_views,
    "newsletter_subscribers": lambda s: s.newsletter_subscribers,
    "followers_gained": lambda s: s.followers_gained,
}

# The metric each format is judged on for best-time analysis (assignment brief)
FORMAT_TIME_METRIC = {
    "image": "impressions",
    "carousel": "engagement_rate",
    "video": "video_views",
    "poll": "poll_votes",
    "newsletter": "newsletter_views",
    "text": "comments",
    "untagged": "impressions",
}

INSUFFICIENT = "Insufficient history"


def _times(share_key: str) -> Callable[[Snapshot, dict[str, float | None]], float | None]:
    def f(s: Snapshot, shares: dict[str, float | None]) -> float | None:
        sh = shares[share_key]
        return None if sh is None or s.impressions is None else s.impressions * sh

    return f


# Relevant-reach metrics: need the post's audience breakdown. Estimates are
# impressions x audience share, and the share is a lower bound (LinkedIn lists top values only).
AUDIENCE_METRICS: dict[str, Callable[[Snapshot, dict[str, float | None]], float | None]] = {
    "uae_impressions": _times("uae_share"),
    "education_impressions": _times("education_share"),
    "decision_maker_impressions": _times("decision_maker_share"),
    "uae_share": lambda s, sh: sh["uae_share"],
    "education_share": lambda s, sh: sh["education_share"],
    "decision_maker_share": lambda s, sh: sh["decision_maker_share"],
}
ALL_METRICS = set(METRICS) | set(AUDIENCE_METRICS)


@dataclass
class Row:
    post: Post
    snap: Snapshot
    published: datetime  # aware UTC

    @property
    def uae(self) -> datetime:
        return to_uae(self.published)

    @cached_property
    def shares(self) -> dict[str, float | None]:
        return post_shares(self.post)

    @property
    def has_audience(self) -> bool:
        return bool(self.post.audience)

    def value(self, metric: str) -> float | None:
        if metric in AUDIENCE_METRICS:
            return AUDIENCE_METRICS[metric](self.snap, self.shares)
        return METRICS[metric](self.snap)


def _pick(snaps: list[Snapshot], checkpoint: str) -> Snapshot | None:
    if checkpoint == "latest":
        return max(snaps, key=lambda s: CHECKPOINT_HOURS[s.checkpoint], default=None)
    return next((s for s in snaps if s.checkpoint == checkpoint), None)


def posts_queryset():
    """Posts with their snapshots and audience rows loaded as plain lists
    (post.snapshots / post.audience), which the analysis code below relies on."""
    return Post.objects.prefetch_related(
        Prefetch("snapshot_items", queryset=Snapshot.objects.order_by("id"), to_attr="snapshots"),
        Prefetch("audience_items", queryset=PostAudience.objects.order_by("id"), to_attr="audience"),
    )


def load_posts(account_id: int) -> list[Post]:
    return list(posts_queryset().filter(account_id=account_id).order_by("-published_at"))


def main_checkpoint(posts: list[Post]) -> str:
    """The checkpoint most posts have a snapshot for, so a first view shows as much data as possible.
    Manually tracked accounts usually land on 24h; history imported from a LinkedIn export lands on
    7d (its totals are stored as 7-day figures). Ties go to the earlier checkpoint."""
    counts = {cp: 0 for cp in CHECKPOINT_HOURS}
    for p in posts:
        for s in p.snapshots:
            counts[s.checkpoint] += 1
    if not any(counts.values()):
        return "24h"
    best = max(counts.values())
    if counts["24h"] == best:
        return "24h"
    return next(cp for cp in CHECKPOINT_HOURS if counts[cp] == best)


def build_rows(
    posts: list[Post],
    checkpoint: str,
    fmt: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[Row]:
    rows = []
    for p in posts:
        if fmt and p.format != fmt:
            continue
        pub = as_utc(p.published_at)
        if since and pub < since:
            continue
        if until and pub >= until:
            continue
        snap = _pick(p.snapshots, checkpoint)
        if snap:
            rows.append(Row(p, snap, pub))
    return rows


def _med(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return median(vals) if vals else None


def _sum(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) if vals else None


# ---------------------------------------------------------------- classification


def _pct_rank(value: float, values: list[float]) -> float:
    if len(values) < 2:
        return 0.5
    less = sum(1 for v in values if v < value)
    equal = sum(1 for v in values if v == value)
    return (less + 0.5 * (equal - 1)) / (len(values) - 1)


def classify(rows: list[Row], metric: str) -> dict[int, dict[str, Any]]:
    """Label each post against the account's own history at the same checkpoint.
    Baseline = same-format posts if there are enough of them, else all posts."""
    by_format: dict[str, list[float]] = defaultdict(list)
    all_vals: list[float] = []
    for r in rows:
        v = r.value(metric)
        if v is not None:
            by_format[r.post.format].append(v)
            all_vals.append(v)

    need = min_history()
    cutoffs = labels()
    result: dict[int, dict[str, Any]] = {}
    for r in rows:
        v = r.value(metric)
        if v is None:
            result[r.post.id] = {"label": INSUFFICIENT, "baseline": "metric not recorded"}
            continue
        same = by_format[r.post.format]
        if len(same) >= need:
            base, desc = same, f"{len(same)} {r.post.format} posts"
        elif len(all_vals) >= need:
            base, desc = all_vals, f"all {len(all_vals)} posts"
        else:
            result[r.post.id] = {
                "label": INSUFFICIENT,
                "baseline": f"{len(all_vals)} posts (need {need})",
            }
            continue
        pct = _pct_rank(v, base)
        label = next(lbl for cut, lbl in cutoffs if pct >= cut)
        result[r.post.id] = {"label": label, "baseline": desc, "percentile": round(pct, 3)}
    return result


def _row_out(r: Row, metric: str, labels: dict[int, dict[str, Any]]) -> dict[str, Any]:
    s = r.snap
    return {
        "post": post_summary(r.post),
        "checkpoint": s.checkpoint,
        "value": r.value(metric),
        "impressions": s.impressions,
        "engagements": engagements(s),
        "engagement_rate": engagement_rate(s),
        "clicks": s.clicks,
        "comments": s.comments,
        "classification": labels.get(r.post.id),
    }


# ---------------------------------------------------------------- endpoints' logic


def _audience_stats(rows: list[Row]) -> dict[str, Any]:
    return {
        "posts_with_audience": sum(1 for r in rows if r.has_audience),
        "median_uae_share": _med([r.value("uae_share") for r in rows]),
        "median_education_share": _med([r.value("education_share") for r in rows]),
        "median_decision_maker_share": _med([r.value("decision_maker_share") for r in rows]),
        "median_uae_impressions": _med([r.value("uae_impressions") for r in rows]),
        "median_education_impressions": _med([r.value("education_impressions") for r in rows]),
    }


def overview(posts: list[Post], checkpoint: str) -> dict[str, Any]:
    rows = build_rows(posts, checkpoint)
    snaps = [r.snap for r in rows]
    return {
        **_audience_stats(rows),
        "checkpoint": checkpoint,
        "suggested_checkpoint": main_checkpoint(posts),
        "posts_total": len(posts),
        "posts_time_unknown": sum(1 for p in posts if not p.time_known),
        "posts_untagged": sum(1 for p in posts if p.format == "untagged"),
        "posts_topic_suggested": sum(1 for p in posts if p.topic_suggested),
        "posts_at_checkpoint": len(rows),
        "median_impressions": _med([s.impressions for s in snaps]),
        "median_engagement_rate": _med([engagement_rate(s) for s in snaps]),
        "median_click_rate": _med([click_rate(s) for s in snaps]),
        "total_clicks": _sum([s.clicks for s in snaps]),
        "total_followers_gained": _sum([s.followers_gained for s in snaps]),
    }


def rankings(posts: list[Post], checkpoint: str, metric: str, limit: int) -> dict[str, Any]:
    rows = build_rows(posts, checkpoint)
    labels = classify(rows, metric)
    valued = [r for r in rows if r.value(metric) is not None]
    valued.sort(key=lambda r: r.value(metric), reverse=True)
    top = valued[:limit]
    bottom = list(reversed(valued[-limit:])) if len(valued) > limit else []
    return {
        "metric": metric,
        "checkpoint": checkpoint,
        "top": [_row_out(r, metric, labels) for r in top],
        "bottom": [_row_out(r, metric, labels) for r in bottom],
        "note": None if bottom else f"Bottom list appears once there are more than {limit} posts.",
    }


def classifications(posts: list[Post], checkpoint: str, metric: str) -> dict[int, dict[str, Any]]:
    return classify(build_rows(posts, checkpoint), metric)


def format_comparison(posts: list[Post], checkpoint: str) -> list[dict[str, Any]]:
    rows = build_rows(posts, checkpoint)
    groups: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        groups[r.post.format].append(r)
    out = []
    for fmt in FORMATS:
        g = groups.get(fmt, [])
        key_metric = FORMAT_TIME_METRIC[fmt]
        out.append(
            {
                "format": fmt,
                "posts": len(g),
                "median_impressions": _med([r.snap.impressions for r in g]),
                "median_engagement_rate": _med([engagement_rate(r.snap) for r in g]),
                "median_clicks": _med([r.snap.clicks for r in g]),
                "median_comments": _med([r.snap.comments for r in g]),
                "key_metric": key_metric,
                "median_key_metric": _med([r.value(key_metric) for r in g]),
                "followers_gained": _sum([r.snap.followers_gained for r in g]),
                **_audience_stats(g),
            }
        )
    return out


def heatmap(posts: list[Post], checkpoint: str, metric: str, fmt: str | None) -> dict[str, Any]:
    all_rows = build_rows(posts, checkpoint, fmt=fmt)
    # Posts with only a date (LinkedIn export) have no time slot: leave them out rather than guess.
    rows = [r for r in all_rows if r.post.time_known]
    # Only posts that recorded the metric count: n always matches the median shown.
    cells: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in rows:
        v = r.value(metric)
        if v is not None:
            cells[(r.uae.strftime("%A"), slot_label(r.uae))].append(v)

    need = min_slot_posts()
    # The typical post (median over every timed post), so each slot can be shown as "1.4× your typical post"
    all_vals = [v for vals in cells.values() for v in vals]
    out_cells = []
    for day in DAYS:
        for slot in SLOT_LABELS:
            vals = cells.get((day, slot), [])
            out_cells.append(
                {
                    "day": day,
                    "slot": slot,
                    "posts": len(vals),
                    "median": median(vals) if vals else None,
                    "low_confidence": len(vals) < need,
                }
            )
    return {
        "metric": metric,
        "checkpoint": checkpoint,
        "format": fmt,
        "days": DAYS,
        "slots": SLOT_LABELS,
        "min_posts_per_slot": need,
        "overall_median": median(all_vals) if all_vals else None,
        "posts_without_time": len(all_rows) - len(rows),
        "cells": out_cells,
        "suggestion": _suggest(out_cells),
    }


def _suggest(cells: list[dict[str, Any]]) -> dict[str, Any] | None:
    eligible = [c for c in cells if not c["low_confidence"] and c["median"] is not None]
    if not eligible:
        return None
    best = max(eligible, key=lambda c: c["median"])
    return {"day": best["day"], "slot": best["slot"], "median": best["median"], "posts": best["posts"]}


def best_slots(posts: list[Post], checkpoint: str) -> list[dict[str, Any]]:
    out = []
    for fmt in FORMATS:
        metric = FORMAT_TIME_METRIC[fmt]
        hm = heatmap(posts, checkpoint, metric, fmt)
        n = sum(c["posts"] for c in hm["cells"])
        out.append({"format": fmt, "metric": metric, "posts": n, "suggestion": hm["suggestion"]})
    return out


GROUP_KEYS = {"topic", "industry", "cta", "hashtag", "hashtag_combo", "keyword", "weekday", "format"}


def groups(posts: list[Post], checkpoint: str, by: str) -> list[dict[str, Any]]:
    rows = build_rows(posts, checkpoint)
    buckets: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        p = r.post
        if by == "hashtag":
            keys = p.hashtags or ["(none)"]
        elif by == "keyword":
            keys = p.keywords or ["(none)"]
        elif by == "hashtag_combo":
            keys = [" ".join(sorted(p.hashtags)) if p.hashtags else "(none)"]
        elif by == "weekday":
            # Day of week works for date-only posts too (UAE date)
            keys = [r.uae.strftime("%A")]
        else:
            keys = [getattr(p, by) or "(not set)"]
        for k in keys:
            buckets[k].append(r)

    out = []
    for k, g in buckets.items():
        out.append(
            {
                "key": k,
                "posts": len(g),
                "median_impressions": _med([r.snap.impressions for r in g]),
                "median_engagement_rate": _med([engagement_rate(r.snap) for r in g]),
                "median_comments": _med([r.snap.comments for r in g]),
                "median_clicks": _med([r.snap.clicks for r in g]),
                "followers_gained": _sum([r.snap.followers_gained for r in g]),
                **_audience_stats(g),
            }
        )
    if by == "weekday":
        out.sort(key=lambda x: DAYS.index(x["key"]))  # Monday first, so the week reads in order
        return out
    # Relevant reach first where audience data exists, then raw impressions
    out.sort(key=lambda x: (x["median_uae_impressions"] or 0, x["median_impressions"] or 0), reverse=True)
    return out


def _window_stats(rows: list[Row]) -> dict[str, Any]:
    snaps = [r.snap for r in rows]
    return {
        "posts": len(rows),
        "total_impressions": _sum([s.impressions for s in snaps]),
        "median_impressions": _med([s.impressions for s in snaps]),
        "median_engagement_rate": _med([engagement_rate(s) for s in snaps]),
        "total_clicks": _sum([s.clicks for s in snaps]),
        "followers_gained": _sum([s.followers_gained for s in snaps]),
        **_audience_stats(rows),
    }


def _trend(cur: float | None, prev: float | None) -> str:
    if cur is None or prev is None or prev == 0:
        return "unknown"
    change = (cur - prev) / prev
    t = settings_store.get("performance")["trend_threshold"]
    if change > t:
        return "improving"
    if change < -t:
        return "declining"
    return "stable"


def consistency(posts: list[Post], checkpoint: str) -> dict[str, Any]:
    now = now_utc()
    windows = []
    for days in (7, 30, 90):
        cur_start = now - timedelta(days=days)
        prev_start = cur_start - timedelta(days=days)
        cur = _window_stats(build_rows(posts, checkpoint, since=cur_start, until=now))
        prev = _window_stats(build_rows(posts, checkpoint, since=prev_start, until=cur_start))
        windows.append(
            {
                "days": days,
                "current": cur,
                "previous": prev,
                "median_impressions_trend": _trend(cur["median_impressions"], prev["median_impressions"]),
                "engagement_rate_trend": _trend(cur["median_engagement_rate"], prev["median_engagement_rate"]),
                "followers_trend": _trend(cur["followers_gained"], prev["followers_gained"]),
                "uae_impressions_trend": _trend(cur["median_uae_impressions"], prev["median_uae_impressions"]),
            }
        )

    # Posts per week (UAE weeks starting Monday), last 12 weeks, all posts regardless of snapshots
    this_monday = to_uae(now).replace(hour=0, minute=0, second=0, microsecond=0)
    this_monday -= timedelta(days=this_monday.weekday())
    weekly = []
    for i in range(11, -1, -1):
        start = this_monday - timedelta(weeks=i)
        end = start + timedelta(weeks=1)
        n = sum(1 for p in posts if start <= to_uae(p.published_at) < end)
        weekly.append({"week_start": start.strftime("%Y-%m-%d"), "posts": n})

    # Is one format carrying the account? (share of impressions, last 90 days)
    rows90 = build_rows(posts, checkpoint, since=now - timedelta(days=90))
    by_fmt: dict[str, int] = defaultdict(int)
    for r in rows90:
        by_fmt[r.post.format] += r.snap.impressions or 0
    total = sum(by_fmt.values())
    share = [
        {"format": f, "impressions": v, "share": (v / total) if total else None}
        for f, v in sorted(by_fmt.items(), key=lambda kv: kv[1], reverse=True)
    ]
    dominant = share[0] if share and total and share[0]["share"] >= 0.6 else None

    counts = [w["posts"] for w in weekly]
    return {
        "checkpoint": checkpoint,
        "windows": windows,
        "weekly_posts": weekly,
        "weeks_without_posts": sum(1 for c in counts if c == 0),
        "format_share_90d": share,
        "dominant_format_90d": dominant,
    }


def capture_window(cp: str) -> tuple[int, int]:
    """(open, close) in hours after publishing during which a checkpoint can still be
    captured honestly. LinkedIn only shows running totals, so once the next checkpoint
    arrives the earlier one is missed, not merely late. The 7d checkpoint closes after 9 days."""
    order = list(CHECKPOINT_HOURS)
    i = order.index(cp)
    close = CHECKPOINT_HOURS[order[i + 1]] if i + 1 < len(order) else CHECKPOINT_HOURS[cp] + 48
    return CHECKPOINT_HOURS[cp], close


def due_snapshots(posts: list[Post]) -> list[dict[str, Any]]:
    """Checkpoints that are open for capture now and have no snapshot yet."""
    now = now_utc()
    out = []
    for p in posts:
        pub = as_utc(p.published_at)
        have = {s.checkpoint for s in p.snapshots}
        for cp in CHECKPOINT_HOURS:
            open_h, close_h = capture_window(cp)
            due = pub + timedelta(hours=open_h)
            closes = pub + timedelta(hours=close_h)
            if cp not in have and due <= now < closes:
                out.append(
                    {
                        "post_id": p.id,
                        "topic": p.topic,
                        "format": p.format,
                        "checkpoint": cp,
                        "due_at": due.isoformat(),
                        "due_at_uae": to_uae(due).strftime("%Y-%m-%d %H:%M"),
                        "hours_late": round((now - due).total_seconds() / 3600, 1),
                        "closes_at": closes.isoformat(),
                        "closes_at_uae": to_uae(closes).strftime("%Y-%m-%d %H:%M"),
                    }
                )
    out.sort(key=lambda d: d["due_at"])
    return out

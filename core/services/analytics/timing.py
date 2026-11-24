"""Posting-time model, version 2.

The old method ("which weekday x slot had the highest median?") mixes up timing with everything else:
if the strongest topics happened to go out on Mondays, Monday gets the credit. This model:

1. Uses the earliest comparable checkpoint (24h when there is enough, otherwise the main one), because
   timing shows up in the first hours and is blurred by day 7.
2. Works out what each post was EXPECTED to get without timing: the page's level at the time (posts in the
   surrounding +-45 normal days, so growth and season are removed), plus its format and topic effects.
3. Labels every date: weekday, UAE public holiday, Ramadan, India holiday, UAE summer, UAE school break.
4. Estimates day, time-slot and special-day effects on what is left ("lift" = actual / expected), all at
   once (so a slot isn't blamed for its weekday), each pulled towards "no effect" until it has enough posts
   (shrinkage: an effect counts as if PRIOR extra posts showed no effect). Ramadan gets its own slot
   adjustments, pulled towards the normal ones.
5. Gives a date-specific answer with a confidence, flags untested slots worth trying, and
6. Backtests itself: it learns from the older 70% of posts and predicts the newest 30%. If knowing the
   time doesn't improve the predictions, it says so instead of crowning a "best time".

Everything is in log space (log(1 + value)), so effects multiply: a slot lift of 1.2 = 20% more.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from statistics import median
from typing import Any

from core.common.timeutil import (
    DAYS,
    OUTSIDE_SLOT,
    SLOT_LABELS,
    now_utc,
    slot_label,
    to_uae,
)
from core.services import calendar_data
from core.services.analytics import performance as a

PRIOR = 6  # shrinkage strength, in "posts showing no effect"
TREND_DAYS = 45  # half-width of the window used for the page's level at the time
ITERATIONS = 12
Z = 1.64  # ~90% interval, shown as "likely between"
# Calling an effect clearly better/worse needs stronger evidence (~98%), because about 20 effects are tested at
# once and a few would pass a 90% bar by luck alone
Z_CLEAR = 2.33
CLEAR_MIN_POSTS = 12
MIN_POSTS = 20  # below this the model doesn't run
WORK_SLOTS = [s for s in SLOT_LABELS if s != OUTSIDE_SLOT]
TIMING_METRICS = {"impressions": "Impressions", "engagements": "Engagements", "clicks": "Clicks"}

SPECIAL = {
    "uae_holiday": "UAE public holidays",
    "ramadan": "Ramadan",
    "india_holiday": "India holidays",
    "summer": "UAE summer (Jul–Aug)",
}
# UAE school breaks are shown on the Calendar but not modelled: they overlap summer (the two effects can't be
# told apart) and they only matter for education posts.


# ------------------------------------------------------------------ date labels


@lru_cache(maxsize=1)
def _items() -> tuple[tuple[date, date, str], ...]:
    out = []
    for i in calendar_data.all_items():
        key = None
        if i["kind"] == "uae_holiday":
            key = "uae_holiday"
        elif i["kind"] == "india_holiday":
            key = "india_holiday"
        elif i["kind"] == "period" and i["title"] == "Ramadan":
            key = "ramadan"
        elif i["kind"] == "period" and i["title"] == "UAE summer":
            key = "summer"
        if key:
            out.append((date.fromisoformat(i["start"]), date.fromisoformat(i["end"]), key))
    return tuple(out)


def day_labels(d: date) -> set[str]:
    return {k for s, e, k in _items() if s <= d <= e}


# ------------------------------------------------------------------ data


@dataclass
class Obs:
    day: date
    weekday: str
    slot: str
    fmt: str
    topic: str
    y: float  # log(1 + value)
    labels: set[str]
    expected: float = 0.0
    resid: float = 0.0  # y - expected, i.e. what timing could explain


def pick_checkpoint(posts) -> str:
    timed = [p for p in posts if p.time_known]
    n24 = sum(1 for p in timed if any(s.checkpoint == "24h" for s in p.snapshots))
    return "24h" if n24 >= 30 else a.main_checkpoint(posts)


def observations(posts, checkpoint: str, metric: str) -> list[Obs]:
    out = []
    for r in a.build_rows(posts, checkpoint):
        if not r.post.time_known:
            continue
        v = r.value(metric)
        if v is None or v < 0:
            continue
        u = r.uae
        out.append(
            Obs(
                day=u.date(),
                weekday=u.strftime("%A"),
                slot=slot_label(u),
                fmt=r.post.format or "untagged",
                topic=(r.post.topic or "").strip().lower() or "(none)",
                y=math.log1p(v),
                labels=day_labels(u.date()),
            )
        )
    out.sort(key=lambda o: o.day)
    return out


# ------------------------------------------------------------------ the model


def _shrunk(values: list[float]) -> float:
    return sum(values) / (len(values) + PRIOR) if values else 0.0


@dataclass
class Model:
    base_obs: list[Obs]  # posts used to estimate the page's level over time
    fmt: dict[str, float]
    topic: dict[str, float]
    day: dict[str, float]
    slot: dict[str, float]
    special: dict[str, float]
    ramadan_slot: dict[str, float]
    n_day: dict[str, int]
    n_slot: dict[str, int]
    n_special: dict[str, int]
    n_ramadan_slot: dict[str, int]
    sd: float
    global_level: float
    n: int
    n_day_slot: dict[tuple[str, str], int] = field(default_factory=dict)

    def level(self, d: date, exclude: Obs | None = None) -> float:
        """The page's typical value around this date, from normal days only (no holidays/periods)."""
        lo, hi = d - timedelta(days=TREND_DAYS), d + timedelta(days=TREND_DAYS)
        vals = [o.y for o in self.base_obs if lo <= o.day <= hi and o is not exclude and not o.labels]
        if len(vals) < 5:
            vals = [o.y for o in self.base_obs if lo <= o.day <= hi and o is not exclude]
        return median(vals) if len(vals) >= 5 else self.global_level

    def expected(self, o: Obs, exclude_self: bool = True) -> float:
        """Without timing: level at the time + format + topic."""
        return self.level(o.day, o if exclude_self else None) + self.fmt.get(o.fmt, 0.0) + self.topic.get(o.topic, 0.0)

    def timing(self, weekday: str, slot: str, labels: set[str]) -> float:
        t = self.day.get(weekday, 0.0) + self.slot.get(slot, 0.0) + sum(self.special.get(k, 0.0) for k in labels)
        if "ramadan" in labels:
            t += self.ramadan_slot.get(slot, 0.0)
        return t

    def se(self, n: int) -> float:
        return self.sd / math.sqrt(n + PRIOR)


def fit(obs: list[Obs]) -> Model:
    global_level = median(o.y for o in obs)
    m = Model(obs, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, sd=1.0, global_level=global_level, n=len(obs))

    # Step 2: what each post was expected to get without timing (level, then format, then topic)
    lvl = {id(o): m.level(o.day, o) for o in obs}
    by_fmt: dict[str, list[float]] = defaultdict(list)
    for o in obs:
        by_fmt[o.fmt].append(o.y - lvl[id(o)])
    m.fmt = {k: _shrunk(v) for k, v in by_fmt.items()}
    by_topic: dict[str, list[float]] = defaultdict(list)
    for o in obs:
        by_topic[o.topic].append(o.y - lvl[id(o)] - m.fmt[o.fmt])
    m.topic = {k: (_shrunk(v) if k != "(none)" else 0.0) for k, v in by_topic.items()}
    for o in obs:
        o.expected = lvl[id(o)] + m.fmt[o.fmt] + m.topic[o.topic]
        o.resid = o.y - o.expected

    # Step 4: day, slot and special-day effects together (backfitting), each shrunk towards zero
    for _ in range(ITERATIONS):
        for name, key in (("day", lambda o: [o.weekday]), ("slot", lambda o: [o.slot]), ("special", lambda o: list(o.labels))):
            groups: dict[str, list[float]] = defaultdict(list)
            for o in obs:
                others = m.timing(o.weekday, o.slot, o.labels)
                for k in key(o):
                    own = getattr(m, name).get(k, 0.0)
                    groups[k].append(o.resid - (others - own))
            setattr(m, name, {k: _shrunk(v) for k, v in groups.items()})
        # Ramadan's own slot adjustments, on top of the normal slot effects
        groups = defaultdict(list)
        for o in obs:
            if "ramadan" in o.labels:
                others = m.timing(o.weekday, o.slot, o.labels) - m.ramadan_slot.get(o.slot, 0.0)
                groups[o.slot].append(o.resid - others)
        m.ramadan_slot = {k: _shrunk(v) for k, v in groups.items()}

    m.n_day = _count(obs, lambda o: [o.weekday])
    m.n_slot = _count(obs, lambda o: [o.slot])
    m.n_special = _count(obs, lambda o: list(o.labels))
    m.n_ramadan_slot = _count([o for o in obs if "ramadan" in o.labels], lambda o: [o.slot])
    m.n_day_slot = defaultdict(int)
    for o in obs:
        m.n_day_slot[(o.weekday, o.slot)] += 1
    left = [o.resid - m.timing(o.weekday, o.slot, o.labels) for o in obs]
    m.sd = max(0.05, (sum(x * x for x in left) / max(1, len(left) - 1)) ** 0.5)
    return m


def _count(obs, key) -> dict[str, int]:
    c: dict[str, int] = defaultdict(int)
    for o in obs:
        for k in key(o):
            c[k] += 1
    return dict(c)


# ------------------------------------------------------------------ backtest


def backtest(obs: list[Obs]) -> dict[str, Any]:
    """Three rounds, always learning from older posts and predicting the next, newer ones
    (55%->next 15%, 70%->next 15%, 85%->last 15%): with timing vs without."""
    if len(obs) < 40:
        return {"ran": False, "reason": f"Needs at least 40 timed posts (has {len(obs)})."}
    err_base, err_model = [], []
    for start, end in ((0.55, 0.70), (0.70, 0.85), (0.85, 1.0)):
        a_, b_ = int(len(obs) * start), int(len(obs) * end)
        _predict_round(obs[:a_], obs[a_:b_], err_base, err_model)
    train_n, test_n = int(len(obs) * 0.55), len(err_base)
    return _bt_result(err_base, err_model, train_n, test_n)


def _predict_round(older: list[Obs], newer: list[Obs], err_base: list[float], err_model: list[float]) -> None:
    train = [Obs(o.day, o.weekday, o.slot, o.fmt, o.topic, o.y, o.labels) for o in older]
    test = newer
    m = fit(train)
    for o in test:
        # The level for a future post can only use earlier posts: the last TREND_DAYS of the training data
        lo = o.day - timedelta(days=2 * TREND_DAYS)
        past = [t.y for t in train if lo <= t.day < o.day and not t.labels] or [t.y for t in train if t.day < o.day]
        lvl = median(past) if past else m.global_level
        base = lvl + m.fmt.get(o.fmt, 0.0) + m.topic.get(o.topic, 0.0)
        err_base.append((o.y - base) ** 2)
        err_model.append((o.y - base - m.timing(o.weekday, o.slot, o.labels)) ** 2)


def _bt_result(err_base: list[float], err_model: list[float], train_n: int, test_n: int) -> dict[str, Any]:
    # Squared errors in log space (so a miss by 2x counts the same at 50 or 5,000 impressions)
    mb, mm = sum(err_base) / len(err_base), sum(err_model) / len(err_model)
    improvement = (mb - mm) / mb * 100 if mb else 0.0
    # Paired check over the same posts: is the improvement bigger than chance?
    diffs = [b - m_ for b, m_ in zip(err_base, err_model)]
    mean_d = sum(diffs) / len(diffs)
    sd_d = (sum((x - mean_d) ** 2 for x in diffs) / max(1, len(diffs) - 1)) ** 0.5
    t = mean_d / (sd_d / math.sqrt(len(diffs))) if sd_d else 0.0
    if improvement >= 2 and t >= Z:
        verdict = "helps"
        text = f"Tested on {test_n} newer posts: knowing the day and time made predictions {improvement:.0f}% more accurate. The timing advice is worth following."
    elif improvement > -1:
        verdict = "no_difference"
        text = f"Tested on {test_n} newer posts: knowing the day and time made no real difference ({improvement:+.1f}%). So far, timing matters much less than what you post."
    else:
        verdict = "worse"
        text = f"Tested on {test_n} newer posts: using the day and time made predictions worse ({improvement:+.1f}%). Past timing patterns didn't hold up, so don't rely on a best time yet."
    return {"ran": True, "train": train_n, "test": test_n, "error_without_timing": round(mb, 3),
            "error_with_timing": round(mm, 3), "improvement_pct": round(improvement, 1), "verdict": verdict, "text": text}


# ------------------------------------------------------------------ outputs


def _effect(m: Model, key: str, eff: float, n: int, label: str | None = None) -> dict[str, Any]:
    se = m.se(n)
    lo, hi = eff - Z * se, eff + Z * se
    if n == 0:
        verdict = "untested"
    elif n < CLEAR_MIN_POSTS:
        verdict = "too_few"
    elif eff - Z_CLEAR * se > 0:
        verdict = "better"
    elif eff + Z_CLEAR * se < 0:
        verdict = "worse"
    else:
        verdict = "no_clear_difference"
    return {"key": key, "label": label or key, "posts": n, "lift": round(math.exp(eff), 2),
            "low": round(math.exp(lo), 2), "high": round(math.exp(hi), 2), "verdict": verdict}


def recommend(m: Model, d: date, need: int) -> dict[str, Any]:
    """The best slot for one date, how the date compares with a normal day, and a slot worth testing."""
    wd = d.strftime("%A")
    labels = day_labels(d)
    preds = {s: m.timing(wd, s, labels) for s in WORK_SLOTS}
    best = max(preds, key=lambda s: preds[s])
    others = sorted(v for s, v in preds.items() if s != best)
    gap = preds[best] - median(others) if others else 0.0
    n_best = m.n_slot.get(best, 0)
    # A slot only counts as "best" when it's clearly ahead and backed by posts
    clear = gap > Z_CLEAR * m.se(n_best) and n_best >= max(need, CLEAR_MIN_POSTS)
    date_eff = m.day.get(wd, 0.0) + sum(m.special.get(k, 0.0) for k in labels)
    tested = [s for s in WORK_SLOTS if m.n_day_slot.get((wd, s), 0) >= need]
    untested = [s for s in WORK_SLOTS if s not in tested]
    # Worth testing: the untried slot with the highest optimistic estimate
    test_slot = max(untested, key=lambda s: preds[s] + Z * m.se(m.n_slot.get(s, 0)), default=None)
    return {
        "date": d.isoformat(),
        "weekday": wd,
        "labels": sorted(labels),
        "weekend": d.weekday() >= 5,
        "best_slot": best,
        "best_lift": round(math.exp(preds[best]), 2),
        "clear": clear,
        "slots": [{"slot": s, "lift": round(math.exp(v), 2), "posts": m.n_slot.get(s, 0)} for s, v in preds.items()],
        "date_lift": round(math.exp(date_eff), 2),
        "date_posts": min([m.n_day.get(wd, 0)] + [m.n_special.get(k, 0) for k in labels]),
        "test_slot": test_slot,
    }


def build(posts, metric: str = "impressions") -> dict[str, Any]:
    cp = pick_checkpoint(posts)
    obs = observations(posts, cp, metric)
    no_time = sum(1 for p in posts if not p.time_known)
    head = {"metric": metric, "metric_label": TIMING_METRICS.get(metric, metric), "checkpoint": cp, "posts_used": len(obs),
            "posts_without_time": no_time, "prior": PRIOR, "min_posts": MIN_POSTS}
    if len(obs) < MIN_POSTS:
        return {**head, "ready": False,
                "reason": f"Needs at least {MIN_POSTS} posts with a known time and a {cp} snapshot (has {len(obs)})."
                + (f" {no_time} posts only have a date (e.g. from a LinkedIn export)." if no_time else "")}
    bt = backtest(obs)
    m = fit(obs)
    need = a.min_slot_posts()

    days = [_effect(m, d, m.day.get(d, 0.0), m.n_day.get(d, 0)) for d in DAYS]
    slots = [_effect(m, s, m.slot.get(s, 0.0), m.n_slot.get(s, 0)) for s in SLOT_LABELS]
    special = [_effect(m, k, m.special.get(k, 0.0), m.n_special.get(k, 0), SPECIAL[k]) for k in SPECIAL]
    ramadan_slots = [_effect(m, s, m.slot.get(s, 0.0) + m.ramadan_slot.get(s, 0.0), m.n_ramadan_slot.get(s, 0))
                     for s in WORK_SLOTS if m.n_ramadan_slot.get(s, 0)]
    fmt_sizes = _count(obs, lambda o: [o.fmt])
    formats = sorted(
        ({"key": k, "posts": fmt_sizes.get(k, 0), "lift": round(math.exp(v), 2)} for k, v in m.fmt.items()),
        key=lambda r: -r["lift"],
    )
    topic_sizes = _count(obs, lambda o: [o.topic])
    # Topics are grouped ignoring case; show them as the team wrote them
    shown = {}
    for p in posts:
        if p.topic and p.topic.strip():
            shown.setdefault(p.topic.strip().lower(), p.topic.strip())
    topics = sorted(
        ({"key": shown.get(k, k), "posts": topic_sizes.get(k, 0), "lift": round(math.exp(v), 2)} for k, v in m.topic.items() if k != "(none)"),
        key=lambda r: -r["lift"],
    )

    # How much each factor moves results: the spread between its best and worst well-supported group
    def spread(rows, n_key="posts"):
        ok = [r["lift"] for r in rows if r[n_key] >= CLEAR_MIN_POSTS]
        return round(max(ok) / min(ok), 2) if len(ok) >= 2 else None

    today = to_uae(now_utc()).date()
    upcoming = [recommend(m, today + timedelta(days=i), need) for i in range(1, 15)]
    return {
        **head,
        "ready": True,
        "days": days,
        "slots": slots,
        "special": special,
        "ramadan_slots": ramadan_slots,
        "formats": formats,
        "topics": topics[:8],
        "spread": {"day": spread(days), "slot": spread(slots), "format": spread(formats), "topic": spread(topics)},
        "backtest": bt,
        "upcoming": upcoming,
    }


def model_for(posts, metric: str = "impressions") -> tuple[Model | None, int]:
    """The fitted model (or None when there's too little data), for other pages such as the Calendar."""
    obs = observations(posts, pick_checkpoint(posts), metric)
    if len(obs) < MIN_POSTS:
        return None, len(obs)
    return fit(obs), len(obs)


def backtest_verdict(posts, metric: str = "impressions") -> dict[str, Any]:
    return backtest(observations(posts, pick_checkpoint(posts), metric))

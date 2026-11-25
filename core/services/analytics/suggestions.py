"""Data-driven next-step suggestions, each explained.

Every suggestion says WHAT to do, WHEN, for WHOM, WHY (evidence from the account's own data),
how it can BOOST outreach, how it could LOWER outreach (risks), how CONFIDENT we are and why,
and HOW TO MEASURE whether it worked.

Rules only fire when there is enough evidence; otherwise they suggest how to collect it.
Effects are stated as directions with evidence, never as promised numbers.
"""

from statistics import median
from typing import Any

from core.common.timeutil import now_utc, slot_label
from core.models import Post
from core.services.analytics import performance as a

FORMAT_NAMES = {
    "image": "image",
    "carousel": "carousel",
    "video": "video",
    "poll": "poll",
    "newsletter": "article",
    "text": "text",
    "untagged": "untagged",
}


def _pct(x: float) -> str:
    return f"{x * 100:+.0f}%"


def _n(x: float | None) -> str:
    return "—" if x is None else f"{x:,.0f}"


def _confidence(n: int, pct: int | None = None, strong: int = 6, ok: int = 3, below: bool = False) -> dict[str, Any]:
    """Level from the number of posts; `pct` = the measured share of those posts that beat (or, with below=True, fell
    short of) the typical post. Only measured suggestions carry a percentage."""
    share = ""
    if pct is not None:
        share = f" {pct}% of them {'fell short of' if below else 'beat'} your typical post."
    if n >= strong:
        out = {"level": "high", "reason": f"Based on {n} posts.{share} Still check it holds as more data arrives."}
    elif n >= ok:
        out = {"level": "medium", "reason": f"Based on only {n} posts.{share} A useful signal, not proof: treat it as a test."}
    else:
        out = {"level": "low", "reason": f"Based on {n} post{'s' if n != 1 else ''}.{share} Too few to rely on: run it as an experiment."}
    if pct is not None:
        out["pct"] = pct
    return out


def _share(rows: list, metric: str, baseline: float | None, match, below: bool = False) -> int | None:
    """Of the posts that `match`, the % above the baseline (or below it), from the account's own posts."""
    if not baseline:
        return None
    vals = [v for v in (r.value(metric) for r in rows if match(r)) if v is not None]
    if len(vals) < 3:
        return None
    hits = sum(1 for v in vals if (v < baseline if below else v > baseline))
    return round(100 * hits / len(vals))


def _count(group: dict[str, Any], has_audience: bool) -> int:
    """Posts that actually carry the measured value: audience-based metrics only count posts with audience data."""
    return group["posts_with_audience"] if has_audience else group["posts"]


def _s(**kw: Any) -> dict[str, Any]:
    kw.setdefault("action", None)
    # Data fixes carry how much is done, e.g. {"done": 12, "total": 42, "label": "posts checked"}
    kw.setdefault("progress", None)
    # Topic suggestions name their topic, so the card can show past posts on it
    kw.setdefault("topic", None)
    return kw


def build(posts: list[Post]) -> dict[str, Any]:
    # Suggestions compare posts at the same age: the checkpoint most posts have
    cp = a.main_checkpoint(posts)
    rows = a.build_rows(posts, cp)
    ov = a.overview(posts, cp)
    has_audience = ov["posts_with_audience"] >= a.min_slot_posts()
    metric = "uae_impressions" if has_audience else "impressions"
    mlabel = "estimated UAE impressions" if has_audience else "impressions"
    vals = [v for v in (r.value(metric) for r in rows) if v is not None]
    baseline = median(vals) if vals else None
    out: list[dict[str, Any]] = []

    # ---------------------------------------------------------------- data first
    due = a.due_snapshots(posts)
    if due:
        out.append(_s(
            id="due-snapshots", category="data", priority="high",
            title=f"Record {len(due)} snapshot{'s' if len(due) != 1 else ''} before the window closes",
            when="Today, before each checkpoint closes",
            who="Internal tracking (affects all analysis)",
            why=[
                f"{len(due)} checkpoint{'s are' if len(due) != 1 else ' is'} open now and will close when the next checkpoint arrives.",
                "LinkedIn reports cumulative totals only; a missed 24h figure cannot be recovered accurately.",
            ],
            boost="Complete, same-age data improves the reliability of every comparison (timing, format, topic) and of later suggestions.",
            risk="None. Requires a few minutes of data entry.",
            confidence={"level": "high", "reason": "This is about data completeness, not a prediction."},
            measure={"metric": "Snapshots due", "period": "Daily", "target": "Zero overdue checkpoints"},
            action={"label": "Open posts", "to": "/posts"},
        ))

    if len(rows) < a.min_history():
        out.append(_s(
            id="build-baseline", category="data", priority="high",
            title=f"Build a baseline of {a.min_history()} posts with a {cp} snapshot",
            when="Over the next 3–4 weeks (about 2–3 posts a week)",
            who="All target segments",
            why=[
                f"Only {len(rows)} post{'s have' if len(rows) != 1 else ' has'} a {cp} snapshot so far.",
                f"Performance labels and reliable comparisons need at least {a.min_history()}.",
            ],
            boost="Enables performance labels and timing and format evidence based on the account's own audience.",
            risk="Posting only to reach the count can reduce quality and engagement.",
            confidence={"level": "high", "reason": "A data requirement, not a prediction."},
            measure={"metric": f"Posts with a {cp} snapshot", "period": "Weekly", "target": f"{a.min_history()}+"},
            action={"label": "Add post", "to": "/posts/new"},
            progress={"done": len(rows), "total": a.min_history(), "label": f"posts with a {cp} snapshot"},
        ))

    # Imported history: formats LinkedIn didn't label, and topics guessed from captions
    if ov["posts_untagged"] or ov["posts_topic_suggested"]:
        parts = []
        if ov["posts_untagged"]:
            parts.append(f"{ov['posts_untagged']} imported post{'s have' if ov['posts_untagged'] != 1 else ' has'} no format (LinkedIn's export only labels articles and videos).")
        if ov["posts_topic_suggested"]:
            parts.append(f"{ov['posts_topic_suggested']} topic{'s were' if ov['posts_topic_suggested'] != 1 else ' was'} suggested from the caption and not yet confirmed.")
        out.append(_s(
            id="tag-imported", category="data", priority="high",
            title="Check the format and topic of imported posts",
            when="This week (about 30 seconds per post)",
            who="Internal tracking (affects format and topic analysis)",
            why=parts + ["Format and topic comparisons are only as good as these labels."],
            boost="Accurate labels show which formats and topics reach UAE decision-makers.",
            risk="None. Incorrect labels would mislead the analysis; verify rather than estimate.",
            confidence={"level": "high", "reason": "A data requirement, not a prediction."},
            measure={"metric": "Untagged posts and unconfirmed topics", "period": "This week", "target": "Zero"},
            action={"label": "Fix now", "to": "/data?tab=posts"},
            progress={
                "done": len(posts) - sum(1 for p in posts if p.format == "untagged" or p.topic_suggested),
                "total": len(posts),
                "label": "posts checked",
            },
        ))

    if ov["posts_at_checkpoint"] >= 3 and ov["posts_with_audience"] / max(1, ov["posts_at_checkpoint"]) < 0.5:
        out.append(_s(
            id="audience-coverage", category="data", priority="medium",
            title="Record “Who saw this post” for more posts",
            when="At the 7-day mark of each post",
            who="UAE decision-makers and schools",
            why=[
                f"Only {ov['posts_with_audience']} of {ov['posts_at_checkpoint']} posts have audience data.",
                "Without audience data, posts can be ranked by total impressions but not by reach among UAE schools and decision-makers.",
            ],
            boost="Allows suggestions to optimise for relevant UAE reach rather than total impressions.",
            risk="None. Requires about 2 minutes per post.",
            confidence={"level": "high", "reason": "A data requirement, not a prediction."},
            measure={"metric": "Posts with audience data", "period": "Weekly", "target": "Every post older than 7 days"},
            action={"label": "Fix now", "to": "/posts"},
            progress={"done": ov["posts_with_audience"], "total": ov["posts_at_checkpoint"], "label": "posts with audience data"},
        ))

    if not rows or baseline is None:
        return {"metric": metric, "metric_label": mlabel, "baseline": baseline, "checkpoint": cp, "suggestions": out}

    # ---------------------------------------------------------------- timing
    hm = a.heatmap(posts, cp, metric, None)
    best = hm["suggestion"]
    if best and best["median"] > baseline:
        lift = best["median"] / baseline - 1
        out.append(_s(
            id="timing", category="timing", priority="medium" if lift >= 0.1 else "low",
            title=f"Schedule upcoming posts on {best['day']}, {best['slot']} (UAE)",
            when=f"{best['day']}s, {best['slot']} UAE time",
            who="Your current audience, weighted to UAE viewers" if has_audience else "Your current audience",
            why=[
                f"{best['posts']} posts in this slot had a median of {_n(best['median'])} {mlabel}, vs {_n(baseline)} across all posts ({_pct(lift)}).",
                "Strongest slot with sufficient posts for comparison; slots with fewer posts are excluded.",
            ],
            boost="Posting when the audience is most active strengthens early engagement, which LinkedIn tends to reward with wider distribution.",
            risk=(
                "Concentrating all posts in one slot can cause posts to compete and fatigue followers; "
                "the advantage may also reflect the topics posted then. Continue testing one other slot each week."
            ),
            confidence=_confidence(best["posts"], _share(
                rows, metric, baseline, lambda r: r.post.time_known and r.uae.strftime("%A") == best["day"] and slot_label(r.uae) == best["slot"],
            )),
            measure={"metric": f"Median {mlabel} of the next 4 posts in this slot", "period": "4 weeks", "target": f"Above {_n(baseline)}"},
            action={"label": "See heatmap", "to": "/data?tab=timing"},
        ))
    else:
        cells = sorted((c for c in hm["cells"] if c["median"] is not None), key=lambda c: c["median"], reverse=True)[:2]
        if cells:
            out.append(_s(
                id="timing-test", category="timing", priority="medium",
                title="Run a posting-time test in two promising slots",
                when=" and ".join(f"{c['day']} {c['slot']}" for c in cells) + " (UAE)",
                who="Your current audience",
                why=[
                    f"No slot has {a.min_slot_posts()}+ posts yet, so no time can be called best.",
                    "Early, limited data favours these two slots: " + "; ".join(f"{c['day']} {c['slot']}: {_n(c['median'])} ({c['posts']} post{'s' if c['posts'] != 1 else ''})" for c in cells) + ".",
                ],
                boost="Within a few weeks, provides account-specific evidence of audience response by time slot.",
                risk="Some test posts will run at weaker times. Alternate slots and keep topic and format consistent.",
                confidence={"level": "low", "reason": "Early signal from very few posts."},
                measure={"metric": f"Median {mlabel} per slot", "period": "3–4 weeks", "target": f"{a.min_slot_posts()} posts in each slot"},
                action={"label": "See heatmap", "to": "/data?tab=timing"},
            ))

    # ---------------------------------------------------------------- format
    fkey = "median_uae_impressions" if has_audience else "median_impressions"
    fmts = [
        f for f in a.format_comparison(posts, cp)
        if f["format"] != "untagged" and _count(f, has_audience) >= 3 and f[fkey] is not None
    ]
    if fmts:
        top = max(fmts, key=lambda f: f[fkey])
        lift = top[fkey] / baseline - 1
        if lift >= 0.1:
            name = FORMAT_NAMES.get(top["format"], top["format"])
            n = _count(top, has_audience)
            out.append(_s(
                id="format", category="format", priority="medium",
                title=f"Use more {name} posts",
                when="1–2 of your next 4 posts",
                who="UAE decision-makers" if has_audience else "Your current audience",
                why=[
                    f"{n} {name} posts{' with audience data' if has_audience else ''} reached a median of {_n(top[fkey])} {mlabel}, vs {_n(baseline)} overall ({_pct(lift)}).",
                ],
                boost="Proven formats are the fastest way to increase reach without changing topics.",
                risk=(
                    "Over-reliance on one format can make the feed repetitive and reduce engagement. "
                    "Some formats (video, carousels) require more effort; quality may suffer if rushed."
                ),
                confidence=_confidence(n, _share(rows, metric, baseline, lambda r: r.post.format == top["format"])),
                measure={"metric": f"Median {mlabel} of the new {name} posts", "period": "4 weeks", "target": f"Above {_n(baseline)}"},
                action={"label": "Compare formats", "to": "/data?tab=formats"},
            ))

    # ---------------------------------------------------------------- topics
    gkey = "median_uae_impressions" if has_audience else "median_impressions"
    topics = [g for g in a.groups(posts, cp, "topic") if _count(g, has_audience) >= 3 and g["key"] != "(not set)" and g[gkey] is not None]
    suffix = " with audience data" if has_audience else ""
    if topics:
        best_t = max(topics, key=lambda g: g[gkey])
        worst_t = min(topics, key=lambda g: g[gkey])
        lift = best_t[gkey] / baseline - 1
        if lift >= 0.1:
            out.append(_s(
                id="topic-more", category="topic", priority="medium",
                title=f"Increase posts on “{best_t['key']}” with a new angle",
                when="1 of your next 3 posts",
                who="UAE schools and decision-makers" if has_audience else "Your current audience",
                why=[f"{_count(best_t, has_audience)} posts on this topic{suffix} reached a median of {_n(best_t[gkey])} {mlabel}, vs {_n(baseline)} overall ({_pct(lift)})."],
                boost="Topics with proven audience response tend to keep performing and strengthen brand recognition.",
                risk="Repeating the same angle causes topic fatigue and lower reach. Vary the angle (case study, checklist, opinion, question).",
                confidence=_confidence(_count(best_t, has_audience), _share(rows, metric, baseline, lambda r: r.post.topic == best_t["key"])),
                measure={"metric": f"Median {mlabel} of the next posts on this topic", "period": "4–6 weeks", "target": f"Stays above {_n(baseline)}"},
                action={"label": "Topic analysis", "to": "/data?tab=content"},
                topic=best_t["key"],
            ))
        drop = worst_t[gkey] / baseline - 1
        if worst_t["key"] != best_t["key"] and drop <= -0.2:
            out.append(_s(
                id="topic-rethink", category="topic", priority="low",
                title=f"Revise the approach to “{worst_t['key']}”",
                when="Before the next post on this topic",
                who="The segment this topic is meant for",
                why=[f"{_count(worst_t, has_audience)} posts on this topic{suffix} had a median of {_n(worst_t[gkey])} {mlabel}, vs {_n(baseline)} overall ({_pct(drop)})."],
                boost="A stronger hook, a different format or a UAE-specific example can improve an underperforming topic.",
                risk="Dropping the topic may lose a small but valuable audience. Review who engaged before deciding.",
                confidence=_confidence(
                    _count(worst_t, has_audience), _share(rows, metric, baseline, lambda r: r.post.topic == worst_t["key"], below=True), below=True
                ),
                measure={"metric": f"{mlabel.capitalize()} of the reworked post", "period": "Next post", "target": f"Closer to {_n(baseline)}"},
                action={"label": "Topic analysis", "to": "/data?tab=content"},
                topic=worst_t["key"],
            ))

    # ---------------------------------------------------------------- CTA (clicks, not just likes)
    ctas = [g for g in a.groups(posts, cp, "cta") if g["posts"] >= 3 and g["key"] != "(not set)" and g["median_clicks"] is not None]
    overall_clicks = a._med([r.snap.clicks for r in rows])
    if ctas and overall_clicks:
        best_c = max(ctas, key=lambda g: g["median_clicks"])
        lift = best_c["median_clicks"] / overall_clicks - 1
        if lift >= 0.15:
            out.append(_s(
                id="cta", category="cta", priority="low",
                title=f"Reuse the CTA style “{best_c['key']}”",
                when="Posts meant to drive enquiries or website visits",
                who="Prospects ready to act",
                why=[f"{best_c['posts']} posts with this CTA got a median of {_n(best_c['median_clicks'])} clicks, vs {_n(overall_clicks)} overall ({_pct(lift)})."],
                boost="Clicks indicate stronger intent than reactions and are closer to an enquiry.",
                risk="Direct CTAs on every post can appear promotional and reduce comments and reach. Limit them to about 1 in 3 posts.",
                confidence=_confidence(best_c["posts"], _share(rows, "clicks", overall_clicks, lambda r: r.post.cta == best_c["key"])),
                measure={"metric": "Median clicks and click rate", "period": "4 weeks", "target": f"Above {_n(overall_clicks)} clicks"},
                action={"label": "CTA analysis", "to": "/data?tab=content"},
            ))

    # ---------------------------------------------------------------- consistency and trends
    cons = a.consistency(posts, cp)
    last4 = [w["posts"] for w in cons["weekly_posts"][-4:]]
    if sum(last4) < 4:
        out.append(_s(
            id="consistency", category="consistency", priority="medium",
            title="Publish at least twice a week",
            when="Every week (e.g. Tuesday and Thursday)",
            who="All followers",
            why=[f"Only {sum(last4)} post{'s' if sum(last4) != 1 else ''} in the last 4 weeks; {cons['weeks_without_posts']} of the last 12 weeks had none."],
            boost="Consistent posting maintains feed visibility and builds steady reach.",
            risk="Higher frequency with weaker content can reduce average engagement. Prioritise quality over frequency.",
            confidence={"level": "medium", "reason": "Widely observed pattern; confirm against the account's trend over the next month."},
            measure={"metric": "Posts per week and 30-day median reach", "period": "4–6 weeks", "target": "2+ posts every week, stable or rising median"},
            action={"label": "Plan in Publishing", "to": "/publishing"},
        ))

    dom = cons["dominant_format_90d"]
    if dom and dom["format"] != "untagged":
        out.append(_s(
            id="diversify", category="format", priority="low",
            title=f"Reduce reliance on {FORMAT_NAMES.get(dom['format'], dom['format'])} posts",
            when="Over the next month",
            who="All followers",
            why=[f"{FORMAT_NAMES.get(dom['format'], dom['format']).capitalize()} posts produced {dom['share'] * 100:.0f}% of impressions in the last 90 days."],
            boost="Diversifying formats reduces dependence on a single format if platform behaviour changes.",
            risk="New formats typically start weaker; total reach may dip for a few weeks.",
            confidence={"level": "medium", "reason": "Concentration risk, not a performance prediction."},
            measure={"metric": "Share of impressions by format", "period": "90 days", "target": "No single format above 60%"},
            action={"label": "Consistency view", "to": "/data?tab=consistency"},
        ))

    w30 = next((w for w in cons["windows"] if w["days"] == 30), None)
    trend_key = "uae_impressions_trend" if has_audience else "median_impressions_trend"
    if w30 and w30.get(trend_key) == "declining":
        out.append(_s(
            id="decline", category="trend", priority="high",
            title="Investigate the drop in reach over the last 30 days",
            when="This week",
            who="All target segments",
            why=["The median per post in the last 30 days is more than the trend threshold below the 30 days before."],
            boost="Identifying the cause early (topic, timing, format, founder shares) prevents a sustained decline.",
            risk="Over-reacting to a short dip may abandon effective tactics. Review the lowest posts first and change one variable at a time.",
            confidence={"level": "medium", "reason": "Trend across two 30-day windows; small samples can vary."},
            measure={"metric": f"30-day median {mlabel}", "period": "Next 30 days", "target": "Back to the previous level"},
            action={"label": "Lowest posts", "to": "/data?tab=rankings"},
        ))

    order = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda s: order[s["priority"]])
    return {"metric": metric, "metric_label": mlabel, "baseline": baseline, "checkpoint": cp, "generated_at": now_utc().isoformat(), "suggestions": out}

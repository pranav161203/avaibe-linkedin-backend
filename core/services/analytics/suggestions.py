"""Data-driven next-step suggestions, each explained.

Every suggestion says WHAT to do, WHEN, for WHOM, WHY (evidence from the account's own data),
how it can BOOST outreach, how it could LOWER outreach (risks), how CONFIDENT we are and why,
and HOW TO MEASURE whether it worked.

Rules only fire when there is enough evidence; otherwise they suggest how to collect it.
Effects are stated as directions with evidence, never as promised numbers.
"""

from statistics import median
from typing import Any

from core.common.timeutil import now_utc
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


def _confidence(n: int, strong: int = 6, ok: int = 3) -> dict[str, str]:
    if n >= strong:
        return {"level": "high", "reason": f"Based on {n} posts. Still check it holds as more data arrives."}
    if n >= ok:
        return {"level": "medium", "reason": f"Based on only {n} posts: a useful signal, not proof. Treat it as a test."}
    return {"level": "low", "reason": f"Based on {n} post{'s' if n != 1 else ''}: too few to rely on. Run it as an experiment."}


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
            when="Today, before each one closes",
            who="Your own tracking (affects every analysis)",
            why=[
                f"{len(due)} checkpoint{'s are' if len(due) != 1 else ' is'} open now and will close when the next checkpoint arrives.",
                "LinkedIn only shows running totals, so a missed 24h figure can never be recovered accurately.",
            ],
            boost="Complete, same-age numbers make every comparison (best time, format, topic) more reliable, so later suggestions get better.",
            risk="None for reach. The only cost is a few minutes of data entry.",
            confidence={"level": "high", "reason": "This is about data completeness, not a prediction."},
            measure={"metric": "Snapshots due", "period": "Daily", "target": "Zero overdue checkpoints"},
            action={"label": "Open posts", "to": "/posts"},
        ))

    if len(rows) < a.min_history():
        out.append(_s(
            id="build-baseline", category="data", priority="high",
            title=f"Build a baseline: get to {a.min_history()} posts with a {cp} snapshot",
            when="Over the next 3–4 weeks (about 2–3 posts a week)",
            who="All target segments",
            why=[
                f"Only {len(rows)} post{'s have' if len(rows) != 1 else ' has'} a {cp} snapshot so far.",
                f"Performance labels and reliable comparisons need at least {a.min_history()}.",
            ],
            boost="Unlocks performance labels, best-time and best-format evidence, so later suggestions are grounded in your own audience.",
            risk="Posting just to fill the count can lower quality and engagement. Keep each post useful.",
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
            when="This week, once (about 30 seconds a post)",
            who="Your own tracking (affects format and topic analysis)",
            why=parts + ["Format and topic comparisons are only as good as these labels."],
            boost="Correct labels show which formats and topics actually reach UAE decision-makers, so the next posts can follow the evidence.",
            risk="None for reach. A wrong label would only mislead the analysis, so check rather than guess.",
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
            who="UAE decision-makers and schools (to measure them at all)",
            why=[
                f"Only {ov['posts_with_audience']} of {ov['posts_at_checkpoint']} posts have audience data.",
                "Without it, the app can rank posts by total views but can't tell whether UAE schools and decision-makers saw them.",
            ],
            boost="Lets every suggestion optimise for relevant UAE reach instead of raw views, which is the actual goal.",
            risk="None for reach. It takes about 2 minutes per post.",
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
            title=f"Schedule your next posts on {best['day']}, {best['slot']} (UAE)",
            when=f"{best['day']}s, {best['slot']} UAE time",
            who="Your current audience, weighted to UAE viewers" if has_audience else "Your current audience",
            why=[
                f"{best['posts']} posts in this slot had a median of {_n(best['median'])} {mlabel}, vs {_n(baseline)} across all posts ({_pct(lift)}).",
                "It is the strongest slot with enough posts to compare; slots with fewer posts are ignored.",
            ],
            boost="Posting when your audience is most active gives the post a stronger first hour, and LinkedIn tends to show early-engaging posts to more people.",
            risk=(
                "Putting every post in one slot can make posts compete with each other and tire your followers; "
                "the advantage may also just be the topics posted then. Keep testing one other slot each week."
            ),
            confidence=_confidence(best["posts"]),
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
                    "These two slots look promising on early, thin data: " + "; ".join(f"{c['day']} {c['slot']}: {_n(c['median'])} ({c['posts']} post{'s' if c['posts'] != 1 else ''})" for c in cells) + ".",
                ],
                boost="Within a few weeks you get real evidence of when your audience responds, instead of generic ‘best time to post’ advice.",
                risk="While testing, some posts will land at weaker times. Alternate the slots and keep topic and format similar, so the test is fair.",
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
                boost="Formats that already work for your audience are the quickest way to lift reach without changing topics.",
                risk=(
                    "Leaning on one format can make the feed repetitive and lower engagement over time. "
                    "Some formats (video, carousels) also take more effort, so quality may drop if rushed."
                ),
                confidence=_confidence(n),
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
                title=f"Post more about “{best_t['key']}”, from a new angle",
                when="1 of your next 3 posts",
                who="UAE schools and decision-makers" if has_audience else "Your current audience",
                why=[f"{_count(best_t, has_audience)} posts on this topic{suffix} reached a median of {_n(best_t[gkey])} {mlabel}, vs {_n(baseline)} overall ({_pct(lift)})."],
                boost="Topics your audience already responds to tend to keep performing, and they build recognition for what AVAIBE is known for.",
                risk="Repeating the same angle leads to topic fatigue: reach often drops when followers feel they've seen it before. Change the angle (case study, checklist, opinion, question).",
                confidence=_confidence(_count(best_t, has_audience)),
                measure={"metric": f"Median {mlabel} of the next posts on this topic", "period": "4–6 weeks", "target": f"Stays above {_n(baseline)}"},
                action={"label": "Topic analysis", "to": "/data?tab=content"},
                topic=best_t["key"],
            ))
        drop = worst_t[gkey] / baseline - 1
        if worst_t["key"] != best_t["key"] and drop <= -0.2:
            out.append(_s(
                id="topic-rethink", category="topic", priority="low",
                title=f"Rethink how you present “{worst_t['key']}”",
                when="Before the next post on this topic",
                who="The segment this topic is meant for",
                why=[f"{_count(worst_t, has_audience)} posts on this topic{suffix} had a median of {_n(worst_t[gkey])} {mlabel}, vs {_n(baseline)} overall ({_pct(drop)})."],
                boost="A sharper hook, a different format or a more UAE-specific example can turn a weak topic into a useful one.",
                risk="Dropping the topic entirely could lose a small but valuable audience (e.g. a few decision-makers who care about it). Check who engaged before deciding.",
                confidence=_confidence(_count(worst_t, has_audience)),
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
                boost="Clicks move people from scrolling to visiting, which is closer to an enquiry than a like.",
                risk="Strong ‘click here’ CTAs on every post can feel salesy and lower comments and reach. Use them on about 1 in 3 posts.",
                confidence=_confidence(best_c["posts"]),
                measure={"metric": "Median clicks and click rate", "period": "4 weeks", "target": f"Above {_n(overall_clicks)} clicks"},
                action={"label": "CTA analysis", "to": "/data?tab=content"},
            ))

    # ---------------------------------------------------------------- consistency and trends
    cons = a.consistency(posts, cp)
    last4 = [w["posts"] for w in cons["weekly_posts"][-4:]]
    if sum(last4) < 4:
        out.append(_s(
            id="consistency", category="consistency", priority="medium",
            title="Post at least twice a week, steadily",
            when="Every week (e.g. Tuesday and Thursday)",
            who="All followers",
            why=[f"Only {sum(last4)} post{'s' if sum(last4) != 1 else ''} in the last 4 weeks; {cons['weeks_without_posts']} of the last 12 weeks had none."],
            boost="Regular posting keeps the page in followers' feeds and builds steady reach instead of occasional spikes.",
            risk="Posting more often with weaker content can lower average engagement and train the audience to skip. Quality first, then frequency.",
            confidence={"level": "medium", "reason": "A widely observed pattern; confirm it with your own trend over the next month."},
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
            boost="Spreading reach across formats protects the account if that one format stops working (e.g. a LinkedIn change).",
            risk="New formats usually start weaker, so total reach may dip for a few weeks while you learn what works.",
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
            boost="Finding the cause early (topic, timing, format, fewer founder shares) stops a dip from becoming a long decline.",
            risk="Over-reacting to a short dip can make you abandon things that work. Look at the lowest posts first and change one thing at a time.",
            confidence={"level": "medium", "reason": "Trend over two 30-day windows; small samples can swing."},
            measure={"metric": f"30-day median {mlabel}", "period": "Next 30 days", "target": "Back to the previous level"},
            action={"label": "Lowest posts", "to": "/data?tab=rankings"},
        ))

    order = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda s: order[s["priority"]])
    return {"metric": metric, "metric_label": mlabel, "baseline": baseline, "checkpoint": cp, "generated_at": now_utc().isoformat(), "suggestions": out}

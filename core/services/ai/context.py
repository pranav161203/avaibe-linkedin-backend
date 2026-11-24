"""Prompt building blocks shared by the AI features: brand, competitors, account history, the draft, timing.

Post captions and team text are wrapped in <untrusted_*> tags so text inside them can't act as instructions.
"""

import json
from datetime import timedelta

from core.common.timeutil import now_utc, to_uae
from core.models import Account
from core.services import settings_store
from core.services.analytics import performance as a


def _round(v, nd=3):
    return round(v, nd) if isinstance(v, float) else v

def post_context(account: Account) -> str:
    """Brand, competitors (as the team recorded them) and this account's own results: shared by Analyse and the chat."""
    from core.models import (
        AccountDoc,  # the Competitors page: names and the team's own notes
    )

    brand = dict(settings_store.get("brand"))
    doc = AccountDoc.objects.filter(account_id=account.id, kind="competitors").first()
    competitors = [
        # What the team recorded on the Competitors page (observed public facts + their own reading), nothing else
        {k: v for k, v in c.items() if k in ("name", "segment", "followers", "posts_per_week", "topics", "positioning", "strengths", "opportunity", "checked_on") and v not in (None, "")}
        for c in (doc.data.get("competitors", []) if doc else [])
        if c.get("name")
    ]
    posts = a.load_posts(account.id)
    cp = a.main_checkpoint(posts)
    history = {
        "posts_tracked": len(posts),
        "checkpoint": cp,
        "topics_by_median_impressions": [
            {"topic": g["key"], "posts": g["posts"], "median_impressions": _round(g["median_impressions"])}
            for g in a.groups(posts, cp, "topic")[:6]
        ],
        "formats": [
            {"format": f["format"], "posts": f["posts"], "median_impressions": _round(f["median_impressions"])}
            for f in a.format_comparison(posts, cp)
            if f["posts"]
        ],
    }
    brand_keys = ("company_summary", "services", "target_segments", "differentiators", "proof_points", "voice", "avoid")
    parts = [
        "<brand>\n" + json.dumps({k: brand.get(k) for k in brand_keys}, ensure_ascii=False, indent=1) + "\n</brand>",
        f"<account>{account.name} ({account.kind})</account>",
        "<competitors>\n" + json.dumps(competitors, ensure_ascii=False) + "\n</competitors>",
        "<this_account_history>\n" + json.dumps(history, ensure_ascii=False, default=str) + "\n</this_account_history>",
    ]
    return "\n\n".join(parts)

GOAL_TEXT = {
    "brand": "Brand awareness: get AVAIBE known to relevant UAE audiences",
    "sales": "Sales: bring in enquiries (comments, DMs, demo requests) and move people towards a deal",
    "engagement": "Engagement: start conversations and grow the community",
}

def draft_block(draft: dict) -> str:
    goal = GOAL_TEXT.get(draft.get("goal") or "")
    return (
        "<draft>\n"
        f"format: {draft.get('format')}\n"
        + (f"goal of the post: {goal} (shape the hook and call to action for this goal)\n" if goal else "")
        + ""
        f"topic: <untrusted_topic>{draft.get('topic') or ''}</untrusted_topic>\n"
        f"industry: <untrusted_industry>{draft.get('industry') or ''}</untrusted_industry>\n"
        f"cta: <untrusted_cta>{draft.get('cta') or ''}</untrusted_cta>\n"
        f"<untrusted_post_text>{draft.get('caption') or ''}</untrusted_post_text>\n"
        "</draft>"
    )

# The parts of the post the team picked under Analyse
POST_PARTS = ("text", "visual", "timing", "poll")

VISUAL_NAME = {"image": "image", "video": "video", "carousel": "carousel slides"}

def timing_block(account: Account, scheduled_at) -> str:
    """This account's posting-time evidence for the chosen date (or the next 7 days when no time is chosen)."""

    from core.common.timeutil import as_utc, slot_label
    from core.services.analytics import timing

    posts = a.load_posts(account.id)
    m, n = timing.model_for(posts)
    if m is None:
        data = {"ready": False, "reason": f"Only {n} past posts with a known time; at least {timing.MIN_POSTS} are needed."}
    else:
        need = a.min_slot_posts()
        bt = timing.backtest_verdict(posts)
        if scheduled_at:
            local = to_uae(as_utc(scheduled_at))
            days = [timing.recommend(m, local.date(), need)]
            chosen = {"date": local.date().isoformat(), "weekday": local.strftime("%A"), "time": local.strftime("%H:%M"), "slot": slot_label(local)}
        else:
            today = to_uae(now_utc()).date()
            days = [timing.recommend(m, today + timedelta(days=i), need) for i in range(1, 8)]
            chosen = None
        data = {"ready": True, "posts_used": n, "proven_on_newer_posts": bt, "chosen_time_uae": chosen, "days": days,
                "note": "lift = expected impressions vs a normal post (1.2 = 20% more); 'clear' = best slot is clearly ahead and backed by posts"}
    return "<timing>\n" + json.dumps(data, ensure_ascii=False, default=str) + "\n</timing>"

def details_block(draft: dict) -> str:
    d = {k: v for k, v in (draft.get("details") or {}).items() if v not in (None, "", [])}
    return f"<format_details><untrusted_details>{json.dumps(d, ensure_ascii=False)}</untrusted_details></format_details>" if d else ""

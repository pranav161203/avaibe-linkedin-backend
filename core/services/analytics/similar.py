"""Past posts like a new idea, and how they performed.

Shown on suggestion and idea cards: "Similar past posts: 7 · median 348 impressions (above your typical 148)".

How "similar" is decided (no AI, so it is explainable):
1. The idea gets a topic: given by the suggestion itself, or from the same caption-based classifier that labelled
   the posts (topics.suggest), so ideas and posts are sorted into topics the same way.
2. Similar posts = the account's posts with that topic.
3. They are listed most-alike first: keyword overlap with the idea text, rare words weighted more (TF-IDF cosine).
Whole-text matching alone was too noisy for short strategy ideas, so the topic decides membership.
"""

import math
import re
from statistics import median

from core.models import Post
from core.services import topics as topic_rules
from core.services.analytics import performance as a

STOP = set(
    """
    the and for with that this from your you our are was were will have has had not but can more most into about over
    than then them they their there what when where which who why how all any each other some such only own same very
    just also new post posts posting week weeks month months day days next first one two three use using used make
    get its it's per via let lets out off ask asks every here would could should may might must team teams page
    avaibe linkedin learn com www http https idea ideas series run runs start like time times way ways
    """.split()
)


def _tokens(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z][a-z0-9+]{2,}", (text or "").lower()):
        if w in STOP:
            continue
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]  # schools -> school, debates -> debate
        out.add(w)
    return out


def _post_text(p: Post) -> str:
    return " ".join([p.topic or "", p.caption or "", " ".join(h.lstrip("#") for h in (p.hashtags or []))])


def topic_for(text: str) -> str | None:
    return topic_rules.suggest(text).get("topic")


def find_similar(account_id: int, queries: list[dict]) -> dict:
    """queries: [{key, text, topic?}] -> {checkpoint, baseline, results: {key: {...}}}"""
    posts = a.load_posts(account_id)
    cp = a.main_checkpoint(posts)
    impressions = {r.post.id: r.value("impressions") for r in a.build_rows(posts, cp)}
    vals = [v for v in impressions.values() if v is not None]
    baseline = median(vals) if vals else None

    docs = [(p, _tokens(_post_text(p))) for p in posts]
    n = len(docs) or 1
    df: dict[str, int] = {}
    for _, toks in docs:
        for t in toks:
            df[t] = df.get(t, 0) + 1

    def idf(t: str) -> float:
        return math.log((n + 1) / (df.get(t, 0) + 1)) + 0.1

    def norm(ts: set[str]) -> float:
        return math.sqrt(sum(idf(t) ** 2 for t in ts if t in df)) or 1.0

    results = {}
    for q in queries:
        topic = (q.get("topic") or topic_for(q.get("text", "")) or "").strip()
        qt = _tokens(q.get("text", ""))
        qn = norm(qt)
        matches = []
        for p, pt in docs:
            if not topic or (p.topic or "").strip().lower() != topic.lower():
                continue
            shared = qt & pt
            matches.append((sum(idf(t) ** 2 for t in shared) / (qn * norm(pt)), p))
        matches.sort(key=lambda m: m[0], reverse=True)
        with_numbers = [impressions[p.id] for _, p in matches if impressions.get(p.id) is not None]
        med = median(with_numbers) if with_numbers else None
        verdict = None
        if med is not None and baseline:
            ratio = med / baseline
            verdict = "above" if ratio >= 1.15 else "below" if ratio <= 0.85 else "similar"
        results[q["key"]] = {
            "topic": topic or None,
            "count": len(matches),
            "with_numbers": len(with_numbers),
            "median_impressions": med,
            "verdict": verdict,  # vs the account's typical post
            "posts": [
                {
                    "id": p.id,
                    "hook": (p.caption or "").strip().split("\n")[0][:120] or p.topic or f"Post #{p.id}",
                    "published": p.published_at.date().isoformat(),
                    "impressions": impressions.get(p.id),
                }
                for _, p in matches[:5]
            ],
        }
    return {"checkpoint": cp, "baseline": baseline, "results": results}

"""Compare the dummy company (synced from the mock API) with a real account imported from LinkedIn's export.

    python manage.py compare_demo --real 3 --demo "Demo company"

Same 90-day window length for both (each account's own latest 90 days of data), same checkpoint rules.
"""

import statistics as st
from collections import Counter
from datetime import timedelta

from django.core.management.base import BaseCommand

from core.common.timeutil import to_uae
from core.models import Account, PageAudience, PageDaily
from core.serializers import page_audience_shares
from core.services.analytics import performance as a


def q(vals):
    v = sorted(x for x in vals if x is not None)
    if not v:
        return "—"
    n = len(v)
    return f"{v[int(n * .25)]} / **{st.median(v):g}** / {v[int(n * .75)]} / {v[int(n * .9)]} / {v[-1]}"


def profile(acc: Account) -> dict:
    posts = a.load_posts(acc.id)
    days = list(PageDaily.objects.filter(account=acc).order_by("date"))
    end = days[-1].date
    start = end - timedelta(days=89)
    recent = [p for p in posts if start <= p.published_at.date() <= end]
    rows = [r for r in a.build_rows(recent, "latest")]
    win = [d for d in days if d.date >= start]
    out = {"window": f"{start} → {end}", "posts": len(recent), "per_week": len(recent) / (90 / 7)}
    out["impressions"] = q(r.snap.impressions for r in rows)
    for f in ("reactions", "comments", "clicks", "reposts"):
        out[f] = q(getattr(r.snap, f) for r in rows)
    out["engagement"] = st.median([r.value("engagement_rate") for r in rows if r.value("engagement_rate") is not None])
    out["formats"] = Counter(p.format for p in recent)
    out["weekday"] = Counter(to_uae(p.published_at).strftime("%a") for p in recent)
    out["time_known"] = sum(1 for p in recent if p.time_known)
    for f in ("impressions", "unique_impressions", "clicks", "reactions", "comments", "page_views", "unique_visitors", "new_followers"):
        out["d_" + f] = q(getattr(d, f) for d in win)
    for aud in ("followers", "visitors"):
        as_of = PageAudience.objects.filter(account=acc, audience=aud).order_by("-as_of").values_list("as_of", flat=True).first()
        rows_ = list(PageAudience.objects.filter(account=acc, audience=aud, as_of=as_of))
        out[aud + "_total"] = rows_[0].total if rows_ else None
        out[aud + "_uae"] = page_audience_shares(rows_).get("uae_share") if rows_ else None
        for dim in ("location", "seniority", "job_function", "industry"):
            top = sorted((r for r in rows_ if r.dimension == dim), key=lambda r: -(r.count or 0))[:3]
            out[f"{aud}_{dim}"] = ", ".join(f"{r.value} ({r.count / r.total:.0%})" for r in top if r.total)
    return out


class Command(BaseCommand):
    help = "Compare the dummy (mock API) company with the real exported account"

    def add_arguments(self, parser):
        parser.add_argument("--real", type=int, default=3)
        parser.add_argument("--demo", default="Demo company")

    def handle(self, *args, **opts):
        real = Account.objects.get(id=opts["real"])
        demo = Account.objects.get(name=opts["demo"])
        R, D = profile(real), profile(demo)
        lines = [f"| | Real export ({real.name}) | Dummy via mock API ({demo.name}) |", "|---|---|---|"]

        def row(label, key, fmt=str):
            lines.append(f"| {label} | {fmt(R[key]) if R.get(key) is not None else '—'} | {fmt(D[key]) if D.get(key) is not None else '—'} |")

        row("Window (last 90 days of data)", "window")
        row("Posts", "posts")
        row("Posts per week", "per_week", lambda v: f"{v:.1f}")
        row("Posts with exact time", "time_known")
        lines.append("| *Per post (p25 / median / p75 / p90 / max)* | | |")
        for k in ("impressions", "reactions", "comments", "clicks", "reposts"):
            row(k.capitalize(), k)
        row("Engagement rate (median)", "engagement", lambda v: f"{v:.1%}")
        row("Formats", "formats", lambda c: ", ".join(f"{k} {v}" for k, v in c.most_common()))
        row("Weekdays", "weekday", lambda c: ", ".join(f"{k} {v}" for k, v in c.most_common()))
        lines.append("| *Page per day (p25 / median / p75 / p90 / max)* | | |")
        for k in ("impressions", "unique_impressions", "clicks", "reactions", "comments", "page_views", "unique_visitors", "new_followers"):
            row(k.replace("_", " ").capitalize(), "d_" + k)
        lines.append("| *Audience* | | |")
        row("Followers", "followers_total")
        row("UAE share of followers", "followers_uae", lambda v: f"{v:.1%}")
        row("UAE share of visitors", "visitors_uae", lambda v: f"{v:.1%}")
        for dim in ("location", "seniority", "job_function", "industry"):
            row(f"Top follower {dim.replace('_', ' ')}", f"followers_{dim}")
        self.stdout.write("\n".join(lines))

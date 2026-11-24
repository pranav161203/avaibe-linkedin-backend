"""Pull a company page's and founders' data from LinkedIn's Community Management API into the app's tables.

Works the same against the real API and the local mock (see linkedin_api.LinkedInAPI).

What is stored, and why (LinkedIn's data storage rules):
- posts: text, exact publish time, format, link              → Post
- per-post lifetime numbers at the post's current age        → Snapshot (7d / 48h / 24h / 6h / 1h)
- page totals per day, page views, new followers per day     → PageDaily (aggregate reporting data: up to 1 year)
- follower and visitor demographics, as of the sync date     → PageAudience
- founders: per-post analytics of posts the app knows about  → Snapshot; daily new followers → PageDaily
Not stored: comments, reactions and the people behind them (48-hour / 24-hour limits). Counts come from the stats.

Founders' posts can't be listed through the API (r_member_social is closed), so only posts the app already
knows (published through the app, or added by link) get analytics.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from django.db import transaction

from core.integrations.linkedin.community_api import (
    LinkedInAPI,
    LinkedInAPIError,
    enc,
    rl_date_range,
    rl_list,
    rl_time,
)
from core.integrations.linkedin.standardized import STAFF_LABELS
from core.models import Account, AccountDoc, PageAudience, PageDaily, Post, Snapshot
from core.services import topics

API_NOTE = "From LinkedIn API"
DAY_MS = 86_400_000


@dataclass
class SyncResult:
    account: str
    calls: int = 0
    posts_created: int = 0
    posts_updated: int = 0
    snapshots: int = 0
    days: int = 0
    demographic_rows: int = 0
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- helpers

def little_to_text(little: str) -> str:
    """LinkedIn 'little' text → plain caption: {hashtag|\\#|tag} → #tag, @[Name](urn) → Name, \\ escapes removed."""
    s = re.sub(r"\{hashtag\|\\?#\|([^}]+)\}", r"#\1", little or "")
    s = re.sub(r"@\[([^\]]+)\]\([^)]*\)", r"\1", s)
    return re.sub(r"\\([\\|{}@\[\]()<>#*_~])", r"\1", s)


def post_format(content: dict | None) -> str:
    if not content:
        return "text"
    if "article" in content:
        return "newsletter"
    if "poll" in content:
        return "poll"
    if "multiImage" in content:
        return "image"
    media = (content.get("media") or {}).get("id", "")
    if media.startswith("urn:li:video:"):
        return "video"
    if media.startswith("urn:li:document:"):
        return "carousel"  # LinkedIn's organic "carousel" is a PDF document post
    return "image"


def checkpoint_for_age(hours: float) -> str | None:
    for cp, h in (("7d", 168), ("48h", 48), ("24h", 24), ("6h", 6), ("1h", 1)):
        if hours >= h:
            return cp
    return None


def ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def save_snapshot(post: Post, now: datetime, values: dict) -> bool:
    """Store lifetime numbers at the post's current age. Never overwrites numbers someone typed in."""
    cp = checkpoint_for_age((now - post.published_at).total_seconds() / 3600)
    if not cp:
        return False
    existing = Snapshot.objects.filter(post=post, checkpoint=cp).first()
    if existing and not (existing.notes or "").startswith((API_NOTE, "From LinkedIn export")):
        return False
    Snapshot.objects.update_or_create(post=post, checkpoint=cp, defaults={**values, "captured_at": now, "notes": API_NOTE})
    return True


# ---------------------------------------------------------------- standardized data (names for codes)

class Names:
    """Turns urn:li:geo:… / function / seniority / industry codes into names with a handful of bulk calls."""

    def __init__(self, api: LinkedInAPI):
        self.api = api
        self.tables: dict[str, dict[str, str]] = {}

    def _all(self, kind: str, path: str) -> dict[str, str]:
        if kind not in self.tables:
            body = self.api.get(path)
            self.tables[kind] = {str(e["id"]): e["name"]["localized"]["en_US"] for e in body.get("elements", [])}
        return self.tables[kind]

    def function(self, urn: str) -> str:
        return self._all("functions", "/rest/functions").get(urn.rsplit(":", 1)[-1], urn)

    def seniority(self, urn: str) -> str:
        return self._all("seniorities", "/rest/seniorities").get(urn.rsplit(":", 1)[-1], urn)

    def industry(self, urn: str) -> str:
        return self._all("industries", "/rest/industryTaxonomyVersions/DEFAULT/industries").get(urn.rsplit(":", 1)[-1], urn)

    def geos(self, urns: list[str]) -> dict[str, str]:
        ids = [u.rsplit(":", 1)[-1] for u in urns]
        out = {}
        for i in range(0, len(ids), 50):
            body = self.api.get("/rest/geo", "ids=List(" + ",".join(ids[i:i + 50]) + ")")
            out.update({k: v["defaultLocalizedName"]["value"] for k, v in body.get("results", {}).items()})
        return {u: out.get(u.rsplit(":", 1)[-1], u) for u in urns}


# ---------------------------------------------------------------- company page

def sync_company(account: Account, api: LinkedInAPI, now: datetime | None = None) -> SyncResult:
    now = now or datetime.now(timezone.utc)
    org = account.linkedin_urn
    res = SyncResult(account.name)
    if not org or not org.startswith("urn:li:organization:"):
        raise ValueError(f"{account.name} has no LinkedIn organization id (urn:li:organization:…)")

    # 1. Posts (newest first, 100 per call)
    items = api.all_pages("/rest/posts", f"q=author&author={enc(org)}&sortBy=CREATED")
    by_urn: dict[str, Post] = {}
    with transaction.atomic():
        for it in items:
            urn = it["id"]
            caption = little_to_text(it.get("commentary", ""))
            fmt = post_format(it.get("content"))
            url = f"https://www.linkedin.com/feed/update/{urn}/"
            post = Post.objects.filter(post_url=url).first()
            fields = {
                "account": account, "linkedin_post_id": urn, "author": account.name,
                "published_at": ms_to_dt(it["publishedAt"]), "time_known": True, "format": fmt,
                "targeted": bool((it.get("distribution") or {}).get("targetEntities")),
                "caption": caption, "hashtags": topics.hashtags(caption),
            }
            if post is None:
                s = topics.suggest(caption)
                post = Post.objects.create(post_url=url, topic=s["topic"], industry=s["industry"], cta=s["cta"],
                                           topic_suggested=bool(s["topic"]), notes=API_NOTE, **fields)
                res.posts_created += 1
            else:
                for k, v in fields.items():
                    setattr(post, k, v)
                post.save()
                res.posts_updated += 1
            by_urn[urn] = post

    # 2. Lifetime numbers per post (only posts from the last 12 months have statistics)
    year_ago = now - timedelta(days=365)
    recent = [u for u, p in by_urn.items() if p.published_at >= year_ago]
    stats: dict[str, dict] = {}
    for key, prefix in (("shares", "urn:li:share:"), ("ugcPosts", "urn:li:ugcPost:")):
        urns = [u for u in recent if u.startswith(prefix)]
        for i in range(0, len(urns), 40):
            body = api.get("/rest/organizationalEntityShareStatistics",
                           f"q=organizationalEntity&organizationalEntity={enc(org)}&{key}={rl_list(urns[i:i + 40])}")
            for el in body.get("elements", []):
                stats[el.get("share") or el.get("ugcPost")] = el["totalShareStatistics"]

    # 3. Video views (videos up to ~6 months old)
    views: dict[str, int] = {}
    for u in recent:
        p = by_urn[u]
        if p.format == "video" and p.published_at >= now - timedelta(days=183):
            body = api.get("/rest/videoAnalytics", f"q=entity&entity={enc(u)}&type=VIDEO_VIEW&aggregation=ALL")
            els = body.get("elements", [])
            if els:
                views[u] = els[0]["value"]

    with transaction.atomic():
        for u in recent:
            s = stats.get(u, {})  # posts with no activity are left out by LinkedIn: count as 0
            values = {
                "impressions": s.get("impressionCount", 0), "clicks": s.get("clickCount", 0),
                "reactions": s.get("likeCount", 0), "comments": s.get("commentCount", 0), "reposts": s.get("shareCount", 0),
            }
            if u in views:
                values["video_views"] = views[u]
            if save_snapshot(by_urn[u], now, values):
                res.snapshots += 1

    # 4. Page totals per day: content, page views, new followers (last 12 months; followers up to 2 days ago)
    start_ms = int((now - timedelta(days=365)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    end_ms = int(now.timestamp() * 1000)
    days: dict[date, dict] = {}

    def day(ms):
        return days.setdefault(ms_to_dt(ms).date(), {})

    body = api.get("/rest/organizationalEntityShareStatistics",
                   f"q=organizationalEntity&organizationalEntity={enc(org)}&timeIntervals={rl_time(start_ms, end_ms)}")
    for el in body.get("elements", []):
        s = el["totalShareStatistics"]
        day(el["timeRange"]["start"]).update(
            impressions=s.get("impressionCount"), unique_impressions=s.get("uniqueImpressionsCount", s.get("uniqueImpressionsCounts")),
            clicks=s.get("clickCount"), reactions=s.get("likeCount"), comments=s.get("commentCount"), reposts=s.get("shareCount"))
    body = api.get("/rest/organizationPageStatistics", f"q=organization&organization={enc(org)}&timeIntervals={rl_time(start_ms, end_ms)}")
    for el in body.get("elements", []):
        v = el["totalPageStatistics"]["views"].get("allPageViews", {})
        day(el["timeRange"]["start"]).update(page_views=v.get("pageViews"), unique_visitors=v.get("uniquePageViews"))
    body = api.get("/rest/organizationalEntityFollowerStatistics",
                   f"q=organizationalEntity&organizationalEntity={enc(org)}&timeIntervals={rl_time(start_ms, end_ms)}")
    for el in body.get("elements", []):
        g = el["followerGains"]
        day(el["timeRange"]["start"])["new_followers"] = (g.get("organicFollowerGain") or 0) + (g.get("paidFollowerGain") or 0)
    with transaction.atomic():
        for d, vals in days.items():
            PageDaily.objects.update_or_create(account=account, date=d, defaults=vals)
    res.days = len(days)

    # 5. Followers and visitors by country, job function, seniority, industry, company size (as of today)
    names = Names(api)
    total = api.get(f"/rest/networkSizes/{enc(org)}", "edgeType=COMPANY_FOLLOWED_BY_MEMBER")["firstDegreeSize"]
    fol = api.get("/rest/organizationalEntityFollowerStatistics", f"q=organizationalEntity&organizationalEntity={enc(org)}")["elements"][0]
    vis = api.get("/rest/organizationPageStatistics", f"q=organization&organization={enc(org)}")["elements"][0]
    geo = names.geos([e["geo"] for e in fol.get("followerCountsByGeo", []) + vis.get("pageStatisticsByGeo", [])])

    def fcount(e):
        return e["followerCounts"]["organicFollowerCount"]  # LinkedIn puts organic + paid in this field

    def vcount(e):
        return e["pageStatistics"]["views"]["allPageViews"]["pageViews"]

    follower_rows = (
        [("location", geo[e["geo"]], fcount(e)) for e in fol.get("followerCountsByGeo", [])]
        + [("job_function", names.function(e["function"]), fcount(e)) for e in fol.get("followerCountsByFunction", [])]
        + [("seniority", names.seniority(e["seniority"]), fcount(e)) for e in fol.get("followerCountsBySeniority", [])]
        + [("industry", names.industry(e["industry"]), fcount(e)) for e in fol.get("followerCountsByIndustry", [])]
        + [("company_size", STAFF_LABELS.get(e["staffCountRange"], e["staffCountRange"]), fcount(e)) for e in fol.get("followerCountsByStaffCountRange", [])]
    )
    visitor_rows = (
        [("location", geo[e["geo"]], vcount(e)) for e in vis.get("pageStatisticsByGeo", [])]
        + [("job_function", names.function(e["function"]), vcount(e)) for e in vis.get("pageStatisticsByFunction", [])]
        + [("seniority", names.seniority(e["seniority"]), vcount(e)) for e in vis.get("pageStatisticsBySeniority", [])]
        + [("industry", names.industry(e["industryV2"]), vcount(e)) for e in vis.get("pageStatisticsByIndustryV2", [])]
        + [("company_size", STAFF_LABELS.get(e["staffCountRange"], e["staffCountRange"]), vcount(e)) for e in vis.get("pageStatisticsByStaffCountRange", [])]
    )
    visitor_total = vis["totalPageStatistics"]["views"]["allPageViews"]["pageViews"]
    as_of = now.date()
    with transaction.atomic():
        for audience, rows, tot in (("followers", follower_rows, total), ("visitors", visitor_rows, visitor_total)):
            PageAudience.objects.filter(account=account, as_of=as_of, audience=audience).delete()
            merged: dict[tuple[str, str], int] = {}
            for dim, value, n in rows:
                merged[(dim, value[:200])] = merged.get((dim, value[:200]), 0) + n
            PageAudience.objects.bulk_create([PageAudience(account=account, as_of=as_of, audience=audience, total=tot,
                                                           dimension=d, value=v, count=n) for (d, v), n in merged.items()])
            res.demographic_rows += len(merged)

    res.calls = api.calls
    return res


# ---------------------------------------------------------------- founders (personal profiles)

MEMBER_METRICS = {
    "IMPRESSION": "impressions", "MEMBERS_REACHED": "members_reached", "REACTION": "reactions", "COMMENT": "comments",
    "RESHARE": "reposts", "POST_SAVE": "saves", "POST_SEND": "sends", "LINK_CLICKS": "clicks",
    "FOLLOWER_GAINED_FROM_CONTENT": "followers_gained", "PROFILE_VIEW_FROM_CONTENT": "profile_views",
}


def sync_member(account: Account, api: LinkedInAPI, now: datetime | None = None, max_age_days: int | None = None) -> SyncResult:
    """Analytics for the founder's posts the app knows (it can't list their posts), plus daily new followers."""
    now = now or datetime.now(timezone.utc)
    res = SyncResult(account.name)
    posts = Post.objects.filter(account=account, linkedin_post_id__isnull=False)
    if max_age_days:
        posts = posts.filter(published_at__gte=now - timedelta(days=max_age_days))
    for post in posts:
        urn = post.linkedin_post_id
        kind = "share" if urn.startswith("urn:li:share:") else "ugc"
        values = {}
        for metric, field_name in MEMBER_METRICS.items():
            try:
                body = api.get("/rest/memberCreatorPostAnalytics",
                               f"q=entity&entity=({kind}:{enc(urn)})&queryType={metric}&aggregation=TOTAL")
            except LinkedInAPIError as e:
                res.notes.append(f"{urn} {metric}: {e}")
                continue
            els = body.get("elements", [])
            values[field_name] = els[0]["count"] if els else 0
        if post.format == "video":
            body = api.get("/rest/memberCreatorVideoAnalytics", f"q=entity&entity=(ugc:{enc(urn)})&queryType=VIDEO_PLAY&aggregation=TOTAL")
            if body.get("elements"):
                values["video_views"] = body["elements"][0]["count"]
        if values and save_snapshot(post, now, values):
            res.snapshots += 1

    start = (now - timedelta(days=365)).date()
    days: dict[date, dict] = {}

    def el_day(el) -> date:
        s = el["dateRange"]["start"]
        return date(s["year"], s["month"], s["day"])

    body = api.get("/rest/memberFollowersCount", f"q=dateRange&dateRange={rl_date_range(start, now.date())}")
    for el in body.get("elements", []):
        days.setdefault(el_day(el), {})["new_followers"] = el["memberFollowersCount"]

    # Totals per day across ALL the founder's posts (q=me), including posts the app didn't publish
    for metric, field_name in (("IMPRESSION", "impressions"), ("REACTION", "reactions"), ("COMMENT", "comments"), ("RESHARE", "reposts")):
        body = api.get("/rest/memberCreatorPostAnalytics", f"q=me&queryType={metric}&aggregation=DAILY&dateRange={rl_date_range(start, now.date())}")
        for el in body.get("elements", []):
            days.setdefault(el_day(el), {})[field_name] = el["count"]
    with transaction.atomic():
        for d, vals in days.items():
            PageDaily.objects.update_or_create(account=account, date=d, defaults=vals)
    res.days = len(days)

    # Lifetime totals across all posts, incl. metrics LinkedIn only gives as totals (reach, followers / profile views from posts)
    totals = {}
    for metric in ("IMPRESSION", "MEMBERS_REACHED", "REACTION", "COMMENT", "RESHARE", "POST_SAVE", "POST_SEND", "LINK_CLICKS",
                   "FOLLOWER_GAINED_FROM_CONTENT", "PROFILE_VIEW_FROM_CONTENT"):
        els = api.get("/rest/memberCreatorPostAnalytics", f"q=me&queryType={metric}&aggregation=TOTAL").get("elements", [])
        totals[metric] = els[0]["count"] if els else 0
    followers = api.get("/rest/memberFollowersCount", "q=me")["elements"][0]["memberFollowersCount"]
    AccountDoc.objects.update_or_create(account=account, kind="member_totals",
                                        defaults={"data": {"as_of": now.date().isoformat(), "followers": followers, "totals": totals}})
    res.notes.append(f"{followers} followers now")
    res.calls = api.calls
    return res

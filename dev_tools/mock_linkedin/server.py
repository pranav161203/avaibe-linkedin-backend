"""A local stand-in for LinkedIn's Community Management API (version 202611), answering from the dummy data.

Same paths as https://api.linkedin.com/rest/… but under /mock-linkedin/rest/…, same response shapes as LinkedIn's
documented samples, and the documented rules:
- share statistics: organic only, rolling 12-month window, per-post stats are lifetime only, posts with no activity
  are left out, no pagination
- follower statistics: lifetime demographics (top 100 per facet) or daily gains without demographics, from
  12 months ago to 2 days ago
- posts by a person (r_member_social) are refused: that permission is closed
- member (founder) analytics only for the authenticated member's own posts; DAILY not allowed for some metrics
- video analytics only for posts up to 6 months old; notifications only for the last 60 days
Calls need "Authorization: Bearer <token>" (tokens below) and a "Linkedin-Version" header.

Not modelled (unknown or not needed): exact error message texts, custom-button click details, rate limits on the
Standard tier. Development-tier limits can be switched on with MOCK_LINKEDIN_TIER=development.
"""

import json
import os
import zlib
from datetime import date, datetime, timedelta, timezone

from django.http import JsonResponse

from dev_tools.mock_linkedin import MOCK_DIR
from dev_tools.mock_linkedin.restli import (
    date_range,
    parse_list,
    parse_obj,
    time_intervals,
)

DAY = 86_400_000
_cache: dict = {"mtime": None, "world": None}
_usage: dict = {}

# Demo tokens: who each one belongs to
TOKENS = {
    "mock-page-admin": {"role": "admin"},
    "mock-founder-ceo": {"role": "member", "index": 0},
    "mock-founder-cto": {"role": "member", "index": 1},
}


def world() -> dict:
    path = MOCK_DIR / "linkedin_world.json"
    mtime = path.stat().st_mtime
    if _cache["mtime"] != mtime:
        w = json.loads(path.read_text(encoding="utf-8"))
        w["_post"] = {p["id"]: p for p in w["posts"]}
        w["_activity"] = {p["activity"]: p for p in w["posts"]}
        for i, m in enumerate(w["members"]):
            for p in m["posts"]:
                p["_member"] = i
                w["_post"][p["id"]] = p
        _cache.update(mtime=mtime, world=w)
    return _cache["world"]


def now_ms(w) -> int:
    """'Now' for the dummy data: the day after its last day of data."""
    end = date.fromisoformat(w["meta"]["dataEnd"]) + timedelta(days=1)
    return int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp() * 1000)


def error(status: int, code: str, message: str, service: int = 100) -> JsonResponse:
    return JsonResponse({"status": status, "serviceErrorCode": service, "code": code, "message": message}, status=status)


def guard(request):
    """Token + version header, like LinkedIn. Returns (caller, error_response)."""
    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    caller = TOKENS.get(token)
    if not caller:
        return None, error(401, "INVALID_ACCESS_TOKEN", "Invalid access token", 65600)
    if not request.headers.get("Linkedin-Version"):
        return None, error(400, "VERSION_MISSING", "A version must be present. Please specify a version by adding the LinkedIn-Version header.")
    day = datetime.now(timezone.utc).date().isoformat()
    key = (day, token)
    _usage[key] = _usage.get(key, 0) + 1
    _usage[(day, "app")] = _usage.get((day, "app"), 0) + 1
    if os.environ.get("MOCK_LINKEDIN_TIER") == "development":
        if _usage[(day, "app")] > 500 or _usage[key] > 100:
            return None, error(429, "TOO_MANY_REQUESTS", "Resource level throttle APPLICATION DAY limit for calls to this resource is reached.", 101)
    return caller, None


def paging(items: list, request, extra: dict | None = None) -> dict:
    start = int(request.GET.get("start", 0))
    count = min(int(request.GET.get("count", 10)), 100)
    page = items[start:start + count]
    links = []
    if start + count < len(items):
        links.append({"href": f"{request.path}?start={start + count}&count={count}", "type": "application/json", "rel": "next"})
    return {"elements": page, "paging": {"count": count, "start": start, "links": links, **(extra or {})}}


def is_admin_of(caller, org_urn, w) -> bool:
    return caller["role"] == "admin" and org_urn == w["organization"]["urn"]


# ---------------------------------------------------------------- organization statistics

def _stats(totals: dict, with_unique: bool) -> dict:
    s = {k: totals[k] for k in ("clickCount", "commentCount", "engagement", "impressionCount", "likeCount", "shareCount")}
    if with_unique:
        s["uniqueImpressionsCount"] = totals["uniqueImpressionsCount"]
    return s


def share_statistics(request):
    caller, err = guard(request)
    if err:
        return err
    w = world()
    org = request.GET.get("organizationalEntity")
    if not is_admin_of(caller, org, w):
        return error(403, "ACCESS_DENIED", f"Not enough permissions to access: organizationalEntityShareStatistics for {org}")
    window_start = now_ms(w) - 365 * DAY
    shares, ugcs = parse_list(request.GET.get("shares")), parse_list(request.GET.get("ugcPosts"))
    shares += [request.GET[k] for k in request.GET if k.startswith("shares[")]
    ugcs += [request.GET[k] for k in request.GET if k.startswith("ugcPosts[")]
    ti = time_intervals(request.GET)

    if shares or ugcs:
        if ti:
            return error(400, "INVALID_PARAM", "Time-bound statistics is not supported for specific share queries.")
        els = []
        for key, urns in (("share", shares), ("ugcPost", ugcs)):
            for urn in urns:
                p = w["_post"].get(urn)
                # Posts with no activity, other authors' posts and posts outside the 12-month window are left out
                if p and p.get("author") == org and p["publishedAt"] >= window_start and p["stats"]["impressionCount"]:
                    els.append({"organizationalEntity": org, key: urn, "totalShareStatistics": _stats(p["stats"], False)})
        return JsonResponse({"elements": els, "paging": {"count": 10, "links": [], "start": 0}})

    if ti:
        days = [d for d in w["pageDays"] if ti["start"] <= d["start"] < ti["end"] and d["start"] >= window_start]
        if ti["granularity"] == "MONTH":
            days = _by_month(days)
        els = [{"timeRange": {"start": d["start"], "end": d.get("end", d["start"] + DAY)}, "totalShareStatistics": d["share"], "organizationalEntity": org} for d in days]
        return JsonResponse({"paging": {"count": 10, "start": 0}, "elements": els})

    posts = [p for p in w["posts"] if p["publishedAt"] >= window_start]
    tot = {k: sum(p["stats"][k] for p in posts) for k in ("clickCount", "commentCount", "impressionCount", "likeCount", "shareCount")}
    tot["uniqueImpressionsCount"] = round(sum(p["stats"]["uniqueImpressionsCount"] for p in posts) * 0.55)
    tot["engagement"] = (tot["clickCount"] + tot["likeCount"] + tot["commentCount"] + tot["shareCount"]) / max(1, tot["impressionCount"])
    return JsonResponse({"paging": {"count": 10, "start": 0}, "elements": [{"totalShareStatistics": _stats(tot, True), "organizationalEntity": org}]})


def _by_month(days: list[dict]) -> list[dict]:
    months: dict[str, dict] = {}
    for d in days:
        dt = datetime.fromtimestamp(d["start"] / 1000, tz=timezone.utc)
        k = f"{dt.year}-{dt.month:02d}"
        m = months.setdefault(k, {"start": d["start"], "end": d["start"], "share": {x: 0 for x in d["share"]}})
        m["end"] = d["start"] + DAY
        for x, v in d["share"].items():
            m["share"][x] += v
    for m in months.values():
        s = m["share"]
        s["engagement"] = (s["clickCount"] + s["likeCount"] + s["commentCount"] + s["shareCount"]) / max(1, s["impressionCount"])
    return list(months.values())


def follower_statistics(request):
    caller, err = guard(request)
    if err:
        return err
    w = world()
    org = request.GET.get("organizationalEntity")
    if not is_admin_of(caller, org, w):
        return error(403, "ACCESS_DENIED", f"Not enough permissions to access: organizationalEntityFollowerStatistics for {org}")
    ti = time_intervals(request.GET)
    if ti:
        lo, hi = now_ms(w) - 365 * DAY, now_ms(w) - 2 * DAY  # 12 months ago … 2 days ago
        days = [d for d in w["pageDays"] if ti["start"] <= d["start"] < ti["end"] and lo <= d["start"] < hi]
        els = [{"timeRange": {"start": d["start"], "end": d["start"] + DAY},
                "followerGains": {"organicFollowerGain": d["followerGain"]["organic"], "paidFollowerGain": d["followerGain"]["paid"]},
                "organizationalEntity": org} for d in days]
        return JsonResponse({"paging": {"count": 10, "start": 0}, "elements": els})
    f = w["followers"]

    def counts(n):
        return {"organicFollowerCount": n, "paidFollowerCount": 0}

    el = {
        "followerCountsByStaffCountRange": [{"followerCounts": counts(c), "staffCountRange": k} for k, c in f["byStaffCountRange"]],
        "followerCountsByFunction": [{"followerCounts": counts(c), "function": f"urn:li:function:{k}"} for k, c in f["byFunction"]],
        "followerCountsByAssociationType": [{"followerCounts": counts(c), "associationType": k} for k, c in f["byAssociationType"]],
        "followerCountsBySeniority": [{"followerCounts": counts(c), "seniority": f"urn:li:seniority:{k}"} for k, c in f["bySeniority"]],
        "followerCountsByGeoCountry": [{"geo": f"urn:li:geo:{k}", "followerCounts": counts(c)} for k, c in f["byGeoCountry"]],
        "followerCountsByGeo": [{"geo": f"urn:li:geo:{k}", "followerCounts": counts(c)} for k, c in f["byGeo"]],
        "followerCountsByIndustry": [{"followerCounts": counts(c), "industry": f"urn:li:industry:{k}"} for k, c in f["byIndustry"]],
        "organizationalEntity": org,
    }
    return JsonResponse({"paging": {"count": 10, "start": 0}, "elements": [el]})


VIEW_KEYS = ["allDesktopPageViews", "allMobilePageViews", "allPageViews", "careersPageViews", "desktopCareersPageViews",
             "desktopJobsPageViews", "desktopLifeAtPageViews", "desktopOverviewPageViews", "jobsPageViews", "lifeAtPageViews",
             "mobileCareersPageViews", "mobileJobsPageViews", "mobileLifeAtPageViews", "mobileOverviewPageViews", "overviewPageViews"]


def _views(total: int, desktop_share: float = 0.62) -> dict:
    desk = round(total * desktop_share)
    v = {k: {"pageViews": 0} for k in VIEW_KEYS}  # no Career Pages: careers / jobs / life views stay 0
    v["allPageViews"]["pageViews"] = v["overviewPageViews"]["pageViews"] = total
    v["allDesktopPageViews"]["pageViews"] = v["desktopOverviewPageViews"]["pageViews"] = desk
    v["allMobilePageViews"]["pageViews"] = v["mobileOverviewPageViews"]["pageViews"] = total - desk
    return v


def page_statistics(request):
    caller, err = guard(request)
    if err:
        return err
    w = world()
    org = request.GET.get("organization")
    if not is_admin_of(caller, org, w):
        return error(403, "ACCESS_DENIED", f"Not enough permissions to access: organizationPageStatistics for {org}")
    clicks = {"desktopCustomButtonClickCounts": [], "mobileCustomButtonClickCounts": []}
    ti = time_intervals(request.GET)
    if ti:
        els = []
        for d in w["pageDays"]:
            if ti["start"] <= d["start"] < ti["end"]:
                v = d["views"]
                els.append({"organization": org, "timeRange": {"start": d["start"], "end": d["start"] + DAY}, "totalPageStatistics": {
                    "clicks": clicks,
                    "views": {
                        "careersPageViews": {"uniquePageViews": 0, "pageViews": 0},
                        "overviewPageViews": {"uniquePageViews": v["overviewUnique"], "pageViews": v["overview"]},
                        "allDesktopPageViews": {"pageViews": v["desktop"]},
                        "allMobilePageViews": {"pageViews": v["mobile"]},
                        "allPageViews": {"uniquePageViews": v["allUnique"], "pageViews": v["all"]},
                    },
                }})
        return JsonResponse({"paging": {"count": 10, "start": 0}, "elements": els})
    vis = w["visitors"]

    def facet(rows, key, fmt):
        return [{key: fmt(k), "pageStatistics": {"views": _views(c)}} for k, c in rows]

    el = {
        "organization": org,
        "pageStatisticsByGeoCountry": facet(vis["byGeoCountry"], "geo", lambda k: f"urn:li:geo:{k}"),
        "pageStatisticsByFunction": facet(vis["byFunction"], "function", lambda k: f"urn:li:function:{k}"),
        "pageStatisticsByIndustryV2": [{"industryV2": f"urn:li:industry:{k}", "pageStatistics": {"views": {"allPageViews": {"pageViews": c}}}} for k, c in vis["byIndustryV2"]],
        "pageStatisticsByGeo": facet(vis["byGeo"], "geo", lambda k: f"urn:li:geo:{k}"),
        "pageStatisticsBySeniority": facet(vis["bySeniority"], "seniority", lambda k: f"urn:li:seniority:{k}"),
        "pageStatisticsByStaffCountRange": facet(vis["byStaffCountRange"], "staffCountRange", lambda k: k),
        "totalPageStatistics": {"clicks": clicks, "views": _views(vis["totalViews"])},
    }
    return JsonResponse({"elements": [el], "paging": {"count": 10, "links": [], "start": 0}})


def network_sizes(request, urn: str):
    _, err = guard(request)
    if err:
        return err
    w = world()
    if urn == w["organization"]["urn"]:
        return JsonResponse({"firstDegreeSize": w["followers"]["total"]})
    if not urn.startswith("urn:li:organization:"):
        return error(400, "INVALID_PARAM", "Invalid organization URN")
    # Any other organization (e.g. a competitor): a stable made-up follower count
    return JsonResponse({"firstDegreeSize": 800 + zlib.crc32(urn.encode()) % 60_000})


def organizations(request, org_id: str | None = None):
    _, err = guard(request)
    if err:
        return err
    w = world()
    o = w["organization"]
    public = {k: o[k] for k in ("id", "localizedName", "vanityName", "localizedWebsite", "primaryOrganizationType", "locations")}
    public["name"] = {"localized": {"en_US": o["localizedName"]}, "preferredLocale": {"country": "US", "language": "en"}}
    if org_id:
        return JsonResponse(public) if int(org_id) == o["id"] else error(404, "NOT_FOUND", "Organization not found")
    if request.GET.get("q") == "vanityName":
        els = [public] if request.GET.get("vanityName", "").lower() == o["vanityName"] else []
        return JsonResponse({"paging": {"start": 0, "count": 10, "links": [], "total": len(els)}, "elements": els})
    return error(400, "INVALID_PARAM", "Unsupported finder")


def organizations_lookup(request):
    _, err = guard(request)
    if err:
        return err
    w = world()
    o = w["organization"]
    results = {}
    for i in parse_list(request.GET.get("ids")):
        if str(i) == str(o["id"]):
            results[str(i)] = {k: o[k] for k in ("id", "localizedName", "vanityName", "localizedWebsite", "primaryOrganizationType")}
    return JsonResponse({"results": results, "statuses": {}, "errors": {}})


# ---------------------------------------------------------------- posts

def _post_out(p: dict) -> dict:
    out = {
        "lifecycleState": "PUBLISHED",
        "lastModifiedAt": p.get("lastModifiedAt", p["publishedAt"]),
        "visibility": "PUBLIC",
        "publishedAt": p["publishedAt"],
        "author": p["author"],
        "distribution": {"feedDistribution": "MAIN_FEED", "thirdPartyDistributionChannels": []},
        "lifecycleStateInfo": {"isEditedByAuthor": p.get("isEditedByAuthor", False)},
        "isReshareDisabledByAuthor": False,
        "createdAt": p.get("createdAt", p["publishedAt"]),
        "id": p["id"],
        "commentary": p["commentary"],
    }
    if p.get("content"):
        out["content"] = p["content"]
    # About 1 in 12 page posts is a targeted organic post (e.g. UAE decision-makers only); stable per post
    if p.get("activity") and zlib.crc32(p["id"].encode()) % 12 == 0:
        out["distribution"]["targetEntities"] = [{"geoLocations": ["urn:li:geo:104305776"], "seniorities": ["urn:li:seniority:6", "urn:li:seniority:8", "urn:li:seniority:10"]}]
    return out


def posts(request):
    caller, err = guard(request)
    if err:
        return err
    w = world()
    if request.GET.get("q") != "author":
        return error(400, "INVALID_PARAM", "Unsupported finder")
    author = request.GET.get("author", "")
    if author.startswith("urn:li:person:"):
        return error(403, "ACCESS_DENIED", "Not enough permissions to access: partnerApiPostsExternal.FINDER-author (requires r_member_social)")
    if not is_admin_of(caller, author, w):
        return error(403, "ACCESS_DENIED", f"Not enough permissions to access posts of {author}")
    key = "createdAt" if request.GET.get("sortBy") == "CREATED" else "lastModifiedAt"
    items = sorted(w["posts"], key=lambda p: p.get(key, p["publishedAt"]), reverse=True)
    return JsonResponse(paging([_post_out(p) for p in items], request))


def post_detail(request, urn: str):
    caller, err = guard(request)
    if err:
        return err
    w = world()
    p = w["_post"].get(urn)
    if not p:
        return error(404, "NOT_FOUND", f"Post {urn} not found")
    member = p.get("_member")
    if member is not None and not (caller["role"] == "member" and caller["index"] == member):
        return error(403, "ACCESS_DENIED", "Not enough permissions to access this post")
    if member is None and caller["role"] != "admin":
        return error(403, "ACCESS_DENIED", "Not enough permissions to access this post")
    return JsonResponse(_post_out(p))


# ---------------------------------------------------------------- comments, reactions, social metadata

def _comment_out(p: dict, c: dict) -> dict:
    out = {
        "actor": c["actor"],
        "commentUrn": f"urn:li:comment:({p['activity']},{c['id']})",
        "created": {"actor": c["actor"], "time": c["time"]},
        "id": c["id"],
        "lastModified": {"actor": c["actor"], "time": c["time"]},
        "likesSummary": {"aggregatedTotalLikes": 0, "selectedLikes": [], "likedByCurrentUser": False, "totalLikes": 0},
        "message": {"attributes": [], "text": c["text"]},
        "object": p["activity"],
    }
    if c.get("agent"):
        out["agent"] = c["agent"]
        out["created"]["impersonator"] = c["agent"]
    if c.get("parent"):
        out["parentComment"] = f"urn:li:comment:({p['activity']},{c['parent']})"
    return out


def comments(request, urn: str):
    caller, err = guard(request)
    if err:
        return err
    w = world()
    if caller["role"] != "admin":
        return error(403, "ACCESS_DENIED", "Not enough permissions to access comments (requires r_member_social_feed for member posts)")
    if urn.startswith("urn:li:comment:"):
        inner = urn[len("urn:li:comment:("):-1]
        activity, _, cid = inner.rpartition(",")
        p = w["_activity"].get(activity)
        items = [c for c in (p["comments"] if p else []) if c.get("parent") == cid]
    else:
        p = w["_post"].get(urn) or w["_activity"].get(urn)
        items = [c for c in (p["comments"] if p and "comments" in p else []) if not c.get("parent")]
    if not p:
        return error(404, "NOT_FOUND", f"{urn} not found")
    return JsonResponse(paging([_comment_out(p, c) for c in items], request, {"total": len(items)}))


def reactions(request, entity: str):
    caller, err = guard(request)
    if err:
        return err
    w = world()
    if caller["role"] != "admin":
        return error(403, "ACCESS_DENIED", "Not enough permissions to access reactions")
    urn = parse_obj(entity).get("entity") if entity.startswith("(") else entity
    p = w["_post"].get(urn) or w["_activity"].get(urn)
    if not p or "reactions" not in p:
        return error(404, "NOT_FOUND", f"{urn} not found")
    sort = (parse_obj(request.GET.get("sort", "(value:REVERSE_CHRONOLOGICAL)")) or {}).get("value", "REVERSE_CHRONOLOGICAL")
    rs = sorted(p["reactions"], key=lambda r: r[2], reverse=sort != "CHRONOLOGICAL")
    els = [{"id": f"urn:li:reaction:({a},{p['activity']})", "lastModified": {"actor": a, "time": t}, "reactionType": typ,
            "created": {"actor": a, "time": t}, "root": p["activity"]} for a, typ, t in rs]
    return JsonResponse(paging(els, request, {"total": len(els)}))


def _metadata(p: dict) -> dict:
    summ: dict[str, dict] = {}
    for _, typ, _ in p.get("reactions", []):
        summ.setdefault(typ, {"reactionType": typ, "count": 0})["count"] += 1
    top = sum(1 for c in p.get("comments", []) if not c.get("parent"))
    return {"reactionSummaries": summ, "commentsState": "OPEN",
            "commentSummary": {"count": len(p.get("comments", [])), "topLevelCount": top}, "entity": p["activity"]}


def social_metadata(request, urn: str | None = None):
    caller, err = guard(request)
    if err:
        return err
    w = world()
    if caller["role"] != "admin":
        return error(403, "ACCESS_DENIED", "Not enough permissions to access social metadata")
    if urn:
        p = w["_post"].get(urn) or w["_activity"].get(urn)
        return JsonResponse(_metadata(p)) if p and "activity" in p else error(404, "NOT_FOUND", f"{urn} not found")
    results, errors = {}, {}
    for u in parse_list(request.GET.get("ids")):
        p = w["_post"].get(u) or w["_activity"].get(u)
        if p and "activity" in p:
            results[p["activity"]] = _metadata(p)
        else:
            errors[u] = {"status": 404, "message": "Not found"}
    return JsonResponse({"statuses": {}, "results": results, "errors": errors})


# ---------------------------------------------------------------- video analytics (company page videos)

def _spread_daily(total: int, start_ms: int, end_ms: int, published: int) -> list[tuple[int, int]]:
    """A post's lifetime total split over the days after publishing, with the same decay the generator uses."""
    from dev_tools.mock_linkedin.generate import DECAY_HEAD, World

    tail = 1 - sum(DECAY_HEAD)
    norm = sum(0.93 ** j for j in range(53))
    weights = DECAY_HEAD + [tail * (0.93 ** i) / norm for i in range(53)]
    vals = World.spread(total, weights)
    d0 = published - published % DAY
    return [(d0 + i * DAY, v) for i, v in enumerate(vals) if v and start_ms <= d0 + i * DAY < end_ms]


def video_analytics(request):
    caller, err = guard(request)
    if err:
        return err
    w = world()
    if request.GET.get("q") != "entity":
        return error(400, "INVALID_PARAM", "Unsupported finder")
    urn = request.GET.get("entity")
    p = w["_post"].get(urn)
    if not p or "video" not in p or p.get("_member") is not None:
        return JsonResponse({"elements": [], "paging": {"count": 10, "links": [], "start": 0, "total": 0}})
    if caller["role"] != "admin":
        return error(403, "ACCESS_DENIED", "Not enough permissions")
    if now_ms(w) - p["publishedAt"] > 183 * DAY:  # data kept ~6 months
        return JsonResponse({"elements": [], "paging": {"count": 10, "links": [], "start": 0, "total": 0}})
    typ = request.GET.get("type", "VIDEO_VIEW")
    total = p["video"].get(typ)
    if total is None:
        return error(400, "INVALID_PARAM", f"Unsupported type {typ}")
    agg = request.GET.get("aggregation", "ALL")
    tr = parse_obj(request.GET.get("timeRange")) if request.GET.get("timeRange") else None
    if agg == "ALL":
        els = [{"entity": urn, "statisticsType": typ, "value": total}]
    else:
        lo = int(tr["start"]) if tr else p["publishedAt"] - DAY
        hi = int(tr["end"]) if tr else now_ms(w)
        els = [{"entity": urn, "statisticsType": typ, "timeRange": {"end": d + DAY, "start": d}, "value": v}
               for d, v in _spread_daily(total, lo, hi, p["publishedAt"])]
    return JsonResponse({"elements": els, "paging": {"count": 10, "links": [], "start": 0, "total": len(els)}})


# ---------------------------------------------------------------- member (founder) analytics

NO_DAILY = {"MEMBERS_REACHED", "LINK_CLICKS", "FOLLOWER_GAINED_FROM_CONTENT", "PROFILE_VIEW_FROM_CONTENT"}


def _member(caller, w):
    if caller["role"] != "member":
        return None
    return w["members"][caller["index"]]


def _dr_out(start: date, end: date) -> dict:
    return {"start": {"month": start.month, "day": start.day, "year": start.year}, "end": {"month": end.month, "day": end.day, "year": end.year}}


def member_post_analytics(request):
    caller, err = guard(request)
    if err:
        return err
    w = world()
    m = _member(caller, w)
    if not m:
        return error(403, "ACCESS_DENIED", "Member analytics need the member's own token (r_member_postAnalytics)")
    metric = request.GET.get("queryType", "IMPRESSION")
    agg = request.GET.get("aggregation", "TOTAL")
    dr = date_range(request.GET)
    if agg == "DAILY" and metric in NO_DAILY:
        return error(400, "INVALID_PARAM", f"DAILY aggregation is not supported for {metric}")
    q = request.GET.get("q")
    if q == "entity":
        ent = parse_obj(request.GET.get("entity", ""))
        kind, urn = next(iter(ent.items())) if isinstance(ent, dict) and ent else (None, None)
        p = w["_post"].get(urn)
        if not p or p.get("_member") != caller["index"]:
            return error(403, "ACCESS_DENIED", "The post is not the authenticated member's own post")
        if agg == "DAILY" and metric == "IMPRESSION":
            return error(400, "INVALID_PARAM", "Daily impression metrics are not supported if given entity is post.")
        target = {"share" if kind == "share" else "ugc": urn}
        posts_ = [p]
    elif q == "me":
        target = None
        posts_ = m["posts"]
    else:
        return error(400, "INVALID_PARAM", "Unsupported finder")
    if posts_ and metric not in posts_[0]["metrics"]:
        return error(400, "INVALID_PARAM", f"Unknown queryType {metric}")

    def in_range(ms: int) -> bool:
        if not dr:
            return True
        d = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()
        return d >= dr[0] and (dr[1] is None or d < dr[1])

    els = []
    if agg == "TOTAL":
        if dr:  # total of the daily numbers inside the range (only metrics with a daily breakdown can be split)
            total = sum(v for p in posts_ for ms, v in p["daily"].get(metric, []) if in_range(ms)) if metric not in NO_DAILY else sum(p["metrics"][metric] for p in posts_ if in_range(p["publishedAt"]))
        else:
            total = sum(p["metrics"][metric] for p in posts_)
        el = {"count": total, "metricType": metric}
        if target:
            el["targetEntity"] = target
        if dr:
            el["dateRange"] = _dr_out(dr[0], dr[1] or dr[0])
        els.append(el)
    else:
        by_day: dict[int, int] = {}
        for p in posts_:
            for ms, v in p["daily"].get(metric, []):
                if in_range(ms):
                    by_day[ms] = by_day.get(ms, 0) + v
        for ms in sorted(by_day):
            d = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()
            el = {"count": by_day[ms], "metricType": metric, "dateRange": _dr_out(d, d + timedelta(days=1))}
            if target:
                el["targetEntity"] = target
            els.append(el)
    return JsonResponse({"elements": els, "paging": {"count": 10, "start": 0, "links": []}})


def member_video_analytics(request):
    caller, err = guard(request)
    if err:
        return err
    w = world()
    m = _member(caller, w)
    if not m:
        return error(403, "ACCESS_DENIED", "Member analytics need the member's own token (r_member_postAnalytics)")
    ent = parse_obj(request.GET.get("entity", ""))
    kind, urn = next(iter(ent.items())) if isinstance(ent, dict) and ent else (None, None)
    p = w["_post"].get(urn)
    if not p or p.get("_member") != caller["index"]:
        return error(403, "ACCESS_DENIED", "The post is not the authenticated member's own post")
    metric = request.GET.get("queryType", "VIDEO_PLAY")
    if "video" not in p:
        return JsonResponse({"elements": [], "paging": {"count": 10, "start": 0, "links": []}})
    return JsonResponse({"elements": [{"count": p["video"].get(metric, 0), "metricType": metric, "targetEntity": {kind: urn}}],
                         "paging": {"count": 10, "start": 0, "links": []}})


def member_followers(request):
    caller, err = guard(request)
    if err:
        return err
    w = world()
    m = _member(caller, w)
    if not m:
        return error(403, "ACCESS_DENIED", "Member follower counts need the member's own token (r_member_profileAnalytics)")
    q = request.GET.get("q")
    if q == "me":
        return JsonResponse({"elements": [{"memberFollowersCount": m["followersNow"]}], "paging": {"count": 10, "start": 0, "total": 1, "links": []}})
    if q == "dateRange":
        dr = date_range(request.GET)
        els = []
        for ms, v in m["followerGains"]:
            d = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()
            if dr and d >= dr[0] and (dr[1] is None or d < dr[1]):
                els.append({"memberFollowersCount": v, "dateRange": {"start": {"month": d.month, "year": d.year, "day": d.day},
                                                                     "end": _dr_out(d, d + timedelta(days=1))["end"]}})
        return JsonResponse({"elements": els, "paging": {"start": 0, "count": 10, "links": [], "total": len(els)}})
    return error(400, "INVALID_PARAM", "Unsupported finder")


# ---------------------------------------------------------------- notifications (last 60 days)

def notifications(request):
    caller, err = guard(request)
    if err:
        return err
    w = world()
    org = request.GET.get("organizationalEntity")
    if not is_admin_of(caller, org, w):
        return error(403, "ACCESS_DENIED", "Not enough permissions to access notifications")
    actions = set(parse_list(request.GET.get("actions"))) or {"LIKE", "COMMENT", "SHARE", "SHARE_MENTION", "ADMIN_COMMENT", "COMMENT_EDIT", "COMMENT_DELETE"}
    tr = parse_obj(request.GET.get("timeRange")) if request.GET.get("timeRange") else None
    src = request.GET.get("sourcePost")
    items = [n for n in reversed(w["notifications"]) if n["action"] in actions
             and (not tr or int(tr["start"]) <= n["lastModifiedAt"] < int(tr["end"]))
             and (not src or n["sourcePost"] == src)]
    return JsonResponse(paging(items, request))


# ---------------------------------------------------------------- standardized data lookups

def lookup(request, kind: str, item_id: str):
    _, err = guard(request)
    if err:
        return err
    table = world()["standardized"].get(kind, {})
    name = table.get(str(item_id))
    if name is None:
        return error(404, "NOT_FOUND", f"{kind} {item_id} not found")
    locale = {"country": "US", "language": "en"}
    if kind == "geo":
        return JsonResponse({"id": int(item_id), "defaultLocalizedName": {"locale": locale, "value": name}})
    return JsonResponse({"id": int(item_id), "name": {"localized": {"en_US": name}, "preferredLocale": locale}})


def lookup_all(request, kind: str):
    """Bulk lookups: all functions / seniorities / industries, or several geos with ?ids=List(1,2,…)."""
    _, err = guard(request)
    if err:
        return err
    table = world()["standardized"].get(kind, {})
    ids = parse_list(request.GET.get("ids"))
    locale = {"country": "US", "language": "en"}
    if kind == "geo":
        results = {i: {"id": int(i), "defaultLocalizedName": {"locale": locale, "value": table[i]}} for i in ids if i in table}
        return JsonResponse({"results": results, "statuses": {}, "errors": {i: {"status": 404} for i in ids if i not in table}})
    els = [{"id": int(k), "name": {"localized": {"en_US": v}, "preferredLocale": locale}} for k, v in table.items()]
    return JsonResponse(paging(els, request, {"total": len(els)}) if "count" in request.GET else {"elements": els, "paging": {"count": len(els), "start": 0, "links": []}})


def usage(request):
    """Not part of LinkedIn: how many calls each demo token made today (to plan for the real rate limits)."""
    day = datetime.now(timezone.utc).date().isoformat()
    return JsonResponse({k[1]: v for k, v in _usage.items() if k[0] == day})

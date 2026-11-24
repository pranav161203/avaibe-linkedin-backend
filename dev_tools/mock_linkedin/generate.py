"""Generate 12 months of a dummy company page + two founder profiles, stored as one JSON "world" file that the
mock LinkedIn server answers from.

Calibration (measured on a real page's LinkedIn export, 97 posts / 90 days, Aug-Nov 2026):
- about 7.5 posts a week, Monday-Friday only; Wednesday the quietest day
- impressions per post: median 148, p25 98, p75 198, p90 302, max ~900 (long right tail)
- reactions about 8 per post with a floor (team members react), comments ~1.4% of impressions, clicks ~2.4%,
  reposts rare; video views ~35% of impressions; article (newsletter) posts reach the most, untagged ones least
- page per day: impressions median ~158, unique impressions ~38% of that, page views ~6-8, unique visitors ~3,
  new followers ~5
- followers ~4,100, mostly India; UAE ~4% of followers but a bigger share of page visitors

ASSUMPTIONS (not in the export, so chosen to be plausible and labelled as such):
- posting times (the export has dates only): UAE business hours, clustered on the hour / half hour
- per-post unique impressions (62-78% of impressions), reaction types, commenters, comment texts
- a 12-month history: the page grows ~25% over the year; quieter posting in Ramadan, late December and summer
- founders: no real data at all; their reach, metrics and follower counts are invented but realistic
"""

import json
import math
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dev_tools.mock_linkedin import captions as C
from dev_tools.mock_linkedin import standardized as S

SEED = 2026
DAY_MS = 86_400_000
UAE = timezone(timedelta(hours=4))
B62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

# Share of a post's lifetime numbers that arrives on day 0, 1, 2 … after publishing; the rest trickles in to day 60
DECAY_HEAD = [0.42, 0.24, 0.09, 0.05, 0.035, 0.025, 0.02]
FORMAT_MIX = {"article": 0.30, "image": 0.30, "video": 0.18, "document": 0.10, "text": 0.06, "poll": 0.03, "multiImage": 0.03}
FORMAT_REACH = {"article": 1.15, "video": 1.0, "image": 0.75, "document": 1.0, "text": 0.6, "poll": 1.1, "multiImage": 0.9}
WEEKDAY_RATE = {0: 1.70, 1: 1.46, 2: 0.92, 3: 1.70, 4: 1.70, 5: 0.0, 6: 0.0}  # Mon..Sun, posts per day (real export)
REACTION_TYPES = [("LIKE", 0.71), ("PRAISE", 0.11), ("EMPATHY", 0.07), ("INTEREST", 0.06), ("APPRECIATION", 0.04), ("ENTERTAINMENT", 0.01)]
RAMADAN = (date(2026, 2, 18), date(2026, 3, 19))


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _day_start_ms(d: date) -> int:
    return _ms(datetime(d.year, d.month, d.day, tzinfo=timezone.utc))


class World:
    def __init__(self, end: date, real_demo: dict, seed: int = SEED):
        self.rng = random.Random(seed)
        self.end = end  # last full day of data (UTC)
        self.start = end - timedelta(days=364)
        self.real = real_demo
        self.geo: dict[int, str] = {}
        self.industries: dict[int, str] = {}

    # ------------------------------------------------------------------ helpers
    def b62(self, n: int) -> str:
        return "".join(self.rng.choice(B62) for _ in range(n))

    def li_id(self, ms: int) -> int:
        """LinkedIn post/activity ids are time-based (the top bits are the creation time in ms)."""
        return (ms << 22) | self.rng.getrandbits(22)

    def person(self) -> str:
        return f"urn:li:person:{self.b62(10)}"

    def lognorm(self, median: float, sigma: float) -> float:
        return median * math.exp(self.rng.gauss(0, sigma))

    def poisson(self, lam: float) -> int:
        if lam <= 0:
            return 0
        if lam > 50:
            return max(0, round(self.rng.gauss(lam, math.sqrt(lam))))
        limit, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= self.rng.random()
            if p < limit:
                return k
            k += 1

    def pick(self, weights: dict):
        r, acc = self.rng.random() * sum(weights.values()), 0.0
        for k, w in weights.items():
            acc += w
            if r <= acc:
                return k
        return k

    def trend(self, d: date) -> float:
        """The page grows over the year: 0.8 a year ago, 1.0 now."""
        return 0.8 + 0.2 * ((d - self.start).days / 364)

    def season(self, d: date) -> float:
        if RAMADAN[0] <= d <= RAMADAN[1]:
            return 0.6
        if (d.month == 12 and d.day >= 20) or (d.month == 1 and d.day <= 3):
            return 0.65
        if d.month in (7, 8):
            return 0.85
        return 1.0

    @staticmethod
    def spread(total: int, fractions: list[float]) -> list[int]:
        """Split an integer total by fractions, keeping the sum exact (largest remainders)."""
        raw = [total * f for f in fractions]
        out = [math.floor(x) for x in raw]
        rest = total - sum(out)
        for i in sorted(range(len(raw)), key=lambda i: raw[i] - out[i], reverse=True)[:rest]:
            out[i] += 1
        return out

    def decay(self, days: int = 60) -> list[float]:
        tail = 1 - sum(DECAY_HEAD)
        n = days - len(DECAY_HEAD)
        weights = [0.93 ** i for i in range(n)]
        s = sum(weights)
        return DECAY_HEAD + [tail * w / s for w in weights]

    # ------------------------------------------------------------------ captions → LinkedIn "little" text
    def caption(self, topic: dict, fmt: str, voice: str = "page") -> tuple[str, dict | None]:
        rng = self.rng
        hook = rng.choice(topic["hooks"])
        if "{a}" in hook:
            a, b = rng.choice(topic["pairs"])
            hook = hook.format(a=a, b=b)
        if voice == "founder":
            hook = rng.choice(["", "Something I keep telling clients: ", "A thought after this week's meetings: ", "Hot take: "]) + hook
        body = rng.sample(topic["body"], k=min(len(topic["body"]), rng.choice([1, 2])))
        cta = rng.choice(C.CTAS)
        tags = rng.sample(topic["hashtags"], k=min(len(topic["hashtags"]), rng.randint(3, 5)))
        poll = None
        if fmt == "poll":
            q, opts = C.POLL_QUESTIONS.get(topic["name"], ("What do you think?", ["Agree", "Disagree", "Depends"]))
            if opts is None:
                a, b = rng.choice(topic["pairs"])
                opts = [a, b, "Both", "Neither"]
            poll = {"question": q, "options": opts}
        text = "\n\n".join(x for x in [hook, *body, cta] if x)
        little = text + "\n\n" + " ".join("{hashtag|\\#|" + t.lstrip("#") + "}" for t in tags)
        return little, poll

    def content(self, fmt: str, topic: dict, poll: dict | None) -> dict | None:
        rng = self.rng
        if fmt == "text":
            return None
        if fmt == "image":
            return {"media": {"id": f"urn:li:image:C4D22AQ{self.b62(12)}", "altText": ""}}
        if fmt == "multiImage":
            return {"multiImage": {"images": [{"id": f"urn:li:image:C4D22AQ{self.b62(12)}", "altText": ""} for _ in range(rng.randint(2, 5))]}}
        if fmt == "video":
            return {"media": {"id": f"urn:li:video:C4D05AQ{self.b62(12)}", "title": topic["name"]}}
        if fmt == "document":
            title = rng.choice(C.ARTICLE_TITLES.get(topic["name"], [topic["name"] + " guide"]))
            return {"media": {"id": f"urn:li:document:D4D10AQ{self.b62(12)}", "title": title + ".pdf"}}
        if fmt == "poll":
            dur = rng.choice(["ONE_DAY", "THREE_DAYS", "SEVEN_DAYS", "FOURTEEN_DAYS"])
            return {"poll": {"question": poll["question"], "options": [{"text": o} for o in poll["options"]], "settings": {"duration": dur}}}
        if fmt == "article":
            title = rng.choice(C.ARTICLE_TITLES.get(topic["name"], ["Tech in the UAE this month"]))
            slug = "-".join(title.lower().replace(":", "").replace("'", "").split())[:60]
            return {
                "article": {
                    "source": f"https://www.linkedin.com/pulse/{slug}-{self.b62(5).lower()}",
                    "title": title,
                    "description": "Our monthly newsletter on technology and business in the UAE.",
                    "thumbnail": f"urn:li:image:C4D12AQ{self.b62(12)}",
                }
            }
        return None

    # ------------------------------------------------------------------ the company page
    def org_posts(self, org_urn: str, employees: list[str], audience: list[str], admin: str) -> list[dict]:
        rng = self.rng
        topics = {t["name"]: t for t in C.TOPICS}
        posts = []
        d = self.start
        while d <= self.end:
            n = self.poisson(WEEKDAY_RATE[d.weekday()] / 1.0 * self.season(d))
            for _ in range(n):
                topic = topics[self.pick({t["name"]: t["weight"] for t in C.TOPICS})]
                fmt = self.pick({f: FORMAT_MIX[f] * (3 if f in topic["formats"] else 0.25) for f in FORMAT_MIX})
                hour = self.pick({9: 3, 10: 4, 11: 3, 12: 2, 13: 1, 15: 1, 16: 2, 17: 1})
                minute = self.pick({0: 5, 30: 4, 15: 1, 45: 1}) if rng.random() < 0.85 else rng.randint(0, 59)
                pub = datetime(d.year, d.month, d.day, hour, minute, rng.randint(0, 59), tzinfo=UAE)
                posts.append({"date": d, "pub": pub, "topic": topic, "fmt": fmt})
            d += timedelta(days=1)

        # Impressions: lognormal around a format/topic/trend-adjusted median, then calibrated so the
        # last 90 days have a median close to the real page's 148
        for p in posts:
            p["raw"] = self.lognorm(1.0, 0.56) * FORMAT_REACH[p["fmt"]] * p["topic"]["lift"] * self.trend(p["date"]) * (0.9 + 0.1 * self.season(p["date"]))
        recent = sorted(p["raw"] for p in posts if (self.end - p["date"]).days < 90)
        scale = 148 / recent[len(recent) // 2]

        out = []
        for p in posts:
            ms = _ms(p["pub"])
            imp = max(12, round(p["raw"] * scale))
            is_ugc = p["fmt"] in ("video", "document", "poll", "multiImage")
            pid = f"urn:li:{'ugcPost' if is_ugc else 'share'}:{self.li_id(ms)}"
            activity = f"urn:li:activity:{self.li_id(ms + rng.randint(0, 3))}"
            little, poll = self.caption(p["topic"], p["fmt"])
            debate = p["topic"]["name"] == "Team Tech Debate"
            likes = max(1, round(3 + imp * 0.034 * self.lognorm(1, 0.35)))
            clicks = self.poisson(imp * 0.024 * self.lognorm(1, 0.9) * (3 if debate else 1))
            comments = self.poisson(imp * 0.0137 * self.lognorm(1, 0.6) * (2.2 if debate else 1)) + (1 if rng.random() < 0.35 else 0)
            shares = self.poisson(imp * 0.003)
            stats = {
                "clickCount": clicks,
                "commentCount": comments,
                "engagement": (clicks + likes + comments + shares) / imp,
                "impressionCount": imp,
                "likeCount": likes,
                "shareCount": shares,
                "uniqueImpressionsCount": round(imp * rng.uniform(0.62, 0.78)),
            }
            post = {
                "id": pid,
                "activity": activity,
                "author": org_urn,
                "format": p["fmt"],
                "topic": p["topic"]["name"],
                "createdAt": ms - rng.randint(0, 3) * 60_000,
                "publishedAt": ms,
                "lastModifiedAt": ms + (rng.randint(60_000, 3_600_000) if rng.random() < 0.15 else 0),
                "isEditedByAuthor": False,
                "commentary": little,
                "content": self.content(p["fmt"], p["topic"], poll),
                "stats": stats,
            }
            post["isEditedByAuthor"] = post["lastModifiedAt"] != ms
            post["daily"] = self.post_daily(post)
            post["reactions"] = self.reactions(post, likes, employees, audience)
            post["comments"] = self.comments(post, comments, employees, audience, org_urn, admin)
            if p["fmt"] == "video":
                views = max(1, round(imp * 0.35 * self.lognorm(1, 0.4)))
                viewers = max(1, round(views * rng.uniform(0.72, 0.9)))
                watched = round(views * self.lognorm(14_000, 0.4))
                post["video"] = {"VIDEO_VIEW": views, "VIEWER": viewers, "TIME_WATCHED": watched,
                                 "TIME_WATCHED_FOR_VIDEO_VIEWS": round(watched * rng.uniform(0.85, 0.95))}
            out.append(post)
        return out

    def post_daily(self, post: dict) -> list[list[int]]:
        """A post's numbers per UTC day after publishing: [dayStartMs, impressions, unique, clicks, likes, comments, shares]."""
        s = post["stats"]
        fr = self.decay()
        cols = [self.spread(s[k], fr) for k in ("impressionCount", "uniqueImpressionsCount", "clickCount", "likeCount", "commentCount", "shareCount")]
        d0 = datetime.fromtimestamp(post["publishedAt"] / 1000, tz=timezone.utc).date()
        rows = []
        for i in range(len(fr)):
            day = d0 + timedelta(days=i)
            if day > self.end:
                break
            vals = [c[i] for c in cols]
            if any(vals):
                rows.append([_day_start_ms(day), *vals])
        return rows

    def reactions(self, post: dict, n: int, employees: list[str], audience: list[str]) -> list[list]:
        rng = self.rng
        actors = rng.sample(employees, k=min(len(employees), rng.randint(2, 6)))
        actors += rng.sample(audience, k=max(0, n - len(actors)))
        out = []
        for a in actors[:n]:
            t = post["publishedAt"] + round(rng.expovariate(1 / (6 * 3_600_000)))
            out.append([a, self.pick(dict(REACTION_TYPES)), t])
        return sorted(out, key=lambda r: r[2])

    def comments(self, post: dict, n: int, employees: list[str], audience: list[str], org: str, admin: str) -> list[dict]:
        rng = self.rng
        bank = C.COMMENTS.get(post["topic"], []) + C.COMMENTS["generic"]
        out: list[dict] = []
        for i in range(n):
            t = post["publishedAt"] + round(rng.expovariate(1 / (5 * 3_600_000)))
            reply_to = rng.choice(out) if out and rng.random() < 0.2 else None
            if reply_to:
                out.append({"id": str(self.li_id(t)), "actor": org, "agent": admin, "time": t,
                            "text": rng.choice(["Thank you! 🙏", "Glad you found it useful.", "Thanks for sharing your view!", "Happy to help, send us a message."]),
                            "parent": reply_to["id"]})
            else:
                actor = rng.choice(employees) if rng.random() < 0.3 else rng.choice(audience)
                out.append({"id": str(self.li_id(t)), "actor": actor, "time": t, "text": rng.choice(bank), "parent": None})
        return sorted(out, key=lambda c: c["time"])

    # ------------------------------------------------------------------ page-level days
    def page_days(self, posts: list[dict]) -> list[dict]:
        rng = self.rng
        by_day: dict[int, list[int]] = {}
        for p in posts:
            for row in p["daily"]:
                acc = by_day.setdefault(row[0], [0] * 6)
                for i in range(6):
                    acc[i] += row[i + 1]
        days = []
        d = self.start
        while d <= self.end:
            k = _day_start_ms(d)
            imp, _uniq_posts, clicks, likes, comments, shares = by_day.get(k, [0] * 6)
            weekend = d.weekday() >= 5
            views = self.poisson((3 + 0.02 * imp) * self.trend(d) * (0.45 if weekend else 1.0))
            uviews = min(views, self.poisson(views * 0.42) if views else 0)
            desktop = round(views * rng.uniform(0.55, 0.7))
            overview = max(0, views - self.poisson(0.3))
            gain = self.poisson(5.3 * (0.75 + 0.3 * (d - self.start).days / 364) * (0.6 if weekend else 1.0) * self.season(d) + imp / 450)
            buttons = self.poisson(views * 0.05)
            days.append({
                "start": k,
                "share": {
                    "clickCount": clicks, "commentCount": comments, "likeCount": likes, "shareCount": shares,
                    "impressionCount": imp, "uniqueImpressionsCounts": round(imp * rng.uniform(0.33, 0.43)),
                    "engagement": (clicks + likes + comments + shares) / imp if imp else 0,
                },
                "views": {"all": views, "allUnique": uviews, "desktop": desktop, "mobile": views - desktop,
                          "overview": overview, "overviewUnique": min(uviews, overview)},
                "buttons": buttons,
                "followerGain": {"organic": gain, "paid": 0},
            })
            d += timedelta(days=1)
        return days

    # ------------------------------------------------------------------ demographics from the real export, scaled
    def scaled(self, rows: list, total_real: int, total_new: int) -> list[tuple[str, int]]:
        f = total_new / total_real if total_real else 1
        out = [(name, max(1, round(c * f * self.rng.uniform(0.88, 1.12)))) for name, c in rows]
        return sorted(out, key=lambda x: -x[1])[:100]

    def followers(self, total: int) -> dict:
        R = self.real
        loc = self.scaled(R["followers/location"]["rows"], R["followers/location"]["total"], total)
        countries: dict[str, int] = {}
        for name, c in loc:
            country = name.rsplit(",", 1)[-1].strip()
            countries[country] = countries.get(country, 0) + c
        for name in [n for n, _ in loc] + list(countries):
            self.geo[S.geo_id(name)] = name
        inds = self.scaled(R["followers/industry"]["rows"], R["followers/industry"]["total"], total)
        for name, _ in inds:
            self.industries[S.industry_id(name)] = name

        def facet(rows, key):
            return [(key(n), c) for n, c in rows if key(n) is not None]

        return {
            "total": total,
            "byAssociationType": [("EMPLOYEE", 24)],
            "byGeoCountry": sorted(((S.geo_id(k), v) for k, v in countries.items()), key=lambda x: -x[1])[:100],
            "byGeo": [(S.geo_id(n), c) for n, c in loc],
            "byFunction": facet(self.scaled(R["followers/job_function"]["rows"], R["followers/job_function"]["total"], total), S.function_id),
            "bySeniority": facet(self.scaled(R["followers/seniority"]["rows"], R["followers/seniority"]["total"], total), S.seniority_id),
            "byIndustry": [(S.industry_id(n), c) for n, c in inds],
            "byStaffCountRange": facet(self.scaled(R["followers/company_size"]["rows"], R["followers/company_size"]["total"], total), S.STAFF_RANGES.get),
        }

    def visitors(self, total_views: int) -> dict:
        R = self.real

        def sc(dim):
            return self.scaled(R[f"visitors/{dim}"]["rows"], R[f"visitors/{dim}"]["total"], total_views)

        loc = sc("location")
        countries: dict[str, int] = {}
        for name, c in loc:
            country = name.rsplit(",", 1)[-1].strip()
            countries[country] = countries.get(country, 0) + c
        for name in [n for n, _ in loc] + list(countries):
            self.geo[S.geo_id(name)] = name
        inds = sc("industry")
        for name, _ in inds:
            self.industries[S.industry_id(name)] = name
        return {
            "totalViews": total_views,
            "byGeoCountry": sorted(((S.geo_id(k), v) for k, v in countries.items()), key=lambda x: -x[1]),
            "byGeo": [(S.geo_id(n), c) for n, c in loc],
            "byFunction": [(S.function_id(n), c) for n, c in sc("job_function") if S.function_id(n)],
            "bySeniority": [(S.seniority_id(n), c) for n, c in sc("seniority") if S.seniority_id(n)],
            "byIndustryV2": [(S.industry_id(n), c) for n, c in inds],
            "byStaffCountRange": [(S.STAFF_RANGES[n], c) for n, c in sc("company_size") if n in S.STAFF_RANGES],
        }

    # ------------------------------------------------------------------ founders (no real data: invented, labelled)
    def founder(self, name: str, title: str, followers_now: int, per_week: float, median_imp: float) -> dict:
        rng = self.rng
        urn = self.person()
        topics = [t for t in C.TOPICS if t["name"] != "Company & culture"]
        posts = []
        d = self.start
        while d <= self.end:
            if d.weekday() < 5:
                for _ in range(self.poisson(per_week / 5 * self.season(d))):
                    topic = rng.choice(topics)
                    fmt = self.pick({"text": 4, "image": 4, "document": 1, "video": 1, "poll": 0.5})
                    pub = datetime(d.year, d.month, d.day, self.pick({8: 2, 9: 3, 10: 2, 13: 1, 18: 1, 20: 1}), rng.randint(0, 59), tzinfo=UAE)
                    ms = _ms(pub)
                    imp = max(40, round(self.lognorm(median_imp, 0.85) * self.trend(d)))
                    has_link = rng.random() < 0.25
                    m = {
                        "IMPRESSION": imp,
                        "MEMBERS_REACHED": round(imp * rng.uniform(0.55, 0.72)),
                        "REACTION": max(2, round(imp * 0.024 * self.lognorm(1, 0.4))),
                        "COMMENT": self.poisson(imp * 0.0055 * self.lognorm(1, 0.6)),
                        "RESHARE": self.poisson(imp * 0.0012),
                        "POST_SAVE": self.poisson(imp * 0.0018),
                        "POST_SEND": self.poisson(imp * 0.0012),
                        "LINK_CLICKS": self.poisson(imp * 0.006) if has_link else 0,
                        "PREMIUM_CTA_CLICKS": 0,
                        "FOLLOWER_GAINED_FROM_CONTENT": self.poisson(imp * 0.0018),
                        "PROFILE_VIEW_FROM_CONTENT": self.poisson(imp * 0.007),
                    }
                    little, poll = self.caption(topic, fmt, voice="founder")
                    is_ugc = fmt in ("video", "document", "poll")
                    post = {
                        "id": f"urn:li:{'ugcPost' if is_ugc else 'share'}:{self.li_id(ms)}",
                        "author": urn, "format": fmt, "topic": topic["name"], "publishedAt": ms,
                        "commentary": little, "content": self.content(fmt, topic, poll), "metrics": m,
                    }
                    fr = self.decay(30)
                    d0 = pub.astimezone(timezone.utc).date()
                    post["daily"] = {}
                    for k in ("IMPRESSION", "REACTION", "COMMENT", "RESHARE", "POST_SAVE", "POST_SEND"):
                        vals = self.spread(m[k], fr)
                        post["daily"][k] = [[_day_start_ms(d0 + timedelta(days=i)), v] for i, v in enumerate(vals)
                                            if v and d0 + timedelta(days=i) <= self.end]
                    if fmt == "video":
                        plays = max(1, round(imp * 0.3 * self.lognorm(1, 0.4)))
                        post["video"] = {"VIDEO_PLAY": plays, "VIDEO_VIEWER": round(plays * 0.8), "VIDEO_WATCH_TIME": round(plays * self.lognorm(12_000, 0.4))}
                    posts.append(post)
            d += timedelta(days=1)

        # Daily follower gains, ending at today's follower count
        gains = []
        d = self.start
        by_day_followers: dict[int, int] = {}
        for p in posts:
            day = _day_start_ms(datetime.fromtimestamp(p["publishedAt"] / 1000, tz=timezone.utc).date())
            by_day_followers[day] = by_day_followers.get(day, 0) + p["metrics"]["FOLLOWER_GAINED_FROM_CONTENT"]
        while d <= self.end:
            k = _day_start_ms(d)
            gains.append([k, self.poisson(followers_now / 2400 * (0.6 if d.weekday() >= 5 else 1)) + by_day_followers.get(k, 0)])
            d += timedelta(days=1)
        return {"urn": urn, "name": name, "headline": title, "followersNow": followers_now, "followerGains": gains, "posts": posts}

    # ------------------------------------------------------------------ notifications (last 60 days)
    def notifications(self, org: str, posts: list[dict], audience: list[str]) -> list[dict]:
        rng = self.rng
        cutoff = _day_start_ms(self.end) - 59 * DAY_MS
        out = []
        for p in posts:
            for c in p["comments"]:
                if c["time"] >= cutoff and c["actor"] != org:
                    out.append({"action": "COMMENT", "time": c["time"], "post": p, "comment": c})
            for actor, _, t in p["reactions"]:
                if t >= cutoff:
                    out.append({"action": "LIKE", "time": t, "post": p, "actor": actor})
            for _ in range(p["stats"]["shareCount"]):
                t = p["publishedAt"] + round(rng.expovariate(1 / 86_400_000))
                if t >= cutoff:
                    out.append({"action": "SHARE", "time": t, "post": p, "actor": rng.choice(audience)})
        for _ in range(6):  # a few mentions of the page by others
            t = cutoff + rng.randint(0, 59 * DAY_MS)
            out.append({"action": "SHARE_MENTION", "time": t, "post": None, "actor": rng.choice(audience)})
        out.sort(key=lambda n: n["time"])
        res = []
        for i, n in enumerate(out):
            item = {"notificationId": 4_406_000 + i, "lastModifiedAt": n["time"], "action": n["action"], "organizationalEntity": org}
            if n["action"] == "COMMENT":
                item["generatedActivity"] = f"urn:li:comment:({n['post']['activity']},{n['comment']['id']})"
                item["sourcePost"] = n["post"]["activity"]
            elif n["action"] == "LIKE":
                item["generatedActivity"] = f"urn:li:reaction:({n['actor']},{n['post']['activity']})"
                item["sourcePost"] = n["post"]["activity"]
            elif n["action"] == "SHARE":
                item["generatedActivity"] = f"urn:li:share:{self.li_id(n['time'])}"
                item["sourcePost"] = n["post"]["activity"]
            else:
                item["generatedActivity"] = f"urn:li:share:{self.li_id(n['time'])}"
                item["sourcePost"] = f"urn:li:activity:{self.li_id(n['time'])}"
            res.append(item)
        return res

    # ------------------------------------------------------------------ everything
    def build(self) -> dict:
        org_id = 91_234_567
        org = f"urn:li:organization:{org_id}"
        admin = self.person()
        employees = [self.person() for _ in range(24)]
        audience = [self.person() for _ in range(900)]
        posts = self.org_posts(org, employees, audience, admin)
        days = self.page_days(posts)
        gains = sum(d["followerGain"]["organic"] for d in days)
        followers_now = 4_060
        total_views = sum(d["views"]["all"] for d in days)
        world = {
            "meta": {
                "generated": datetime.now(timezone.utc).isoformat(),
                "linkedinVersion": "202611",
                "dataStart": self.start.isoformat(),
                "dataEnd": self.end.isoformat(),
                "note": "Synthetic data in LinkedIn Community Management API format. Not a real company or person.",
                "followersAYearAgo": followers_now - gains,
            },
            "organization": {
                "id": org_id, "urn": org, "localizedName": C.COMPANY, "vanityName": "demo-tech-solutions",
                "localizedWebsite": "https://www.example-demo.com", "primaryOrganizationType": "NONE",
                "locations": [{"address": {"country": "AE", "city": "Dubai", "geographicArea": "Dubai"}, "locationType": "HEADQUARTERS",
                               "geoLocation": f"urn:li:geo:{S.geo_id('Dubai, United Arab Emirates')}", "staffCountRange": "SIZE_11_TO_50"}],
                "admin": admin,
            },
            "posts": posts,
            "pageDays": days,
            "followers": self.followers(followers_now),
            "visitors": self.visitors(total_views),
            "members": [
                self.founder("Demo Founder (CEO)", "CEO & Co-founder at " + C.COMPANY, 6_240, 2.2, 680),
                self.founder("Demo Co-founder (CTO)", "CTO & Co-founder at " + C.COMPANY, 2_910, 1.4, 390),
            ],
        }
        world["notifications"] = self.notifications(org, posts, audience)
        world["standardized"] = {
            "geo": {str(k): v for k, v in sorted(self.geo.items())},
            "functions": {str(k): v for k, v in S.FUNCTIONS.items()},
            "seniorities": {str(k): v for k, v in S.SENIORITIES.items()},
            "industries": {str(k): v for k, v in sorted(self.industries.items())},
        }
        return world


def _jsonable(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if isinstance(o, tuple):
        return list(o)
    raise TypeError(type(o))


def generate(real_demo_path: Path, out_path: Path, end: date) -> dict:
    real = json.loads(real_demo_path.read_text(encoding="utf-8"))
    world = World(end, real).build()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(world, default=_jsonable, ensure_ascii=False), encoding="utf-8")
    return world

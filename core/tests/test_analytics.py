"""Analytics: classification, suggestions and decisions, similar posts, the posting-time model."""

import io
from datetime import date
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Account, Post, Snapshot
from core.services.analytics import performance as analytics
from core.services.imports import linkedin_export
from core.tests.factories import EXPORTED, _post, content_file


class AnalyticsWithImportedPostsTests(TestCase):
    def setUp(self):
        self.acc = Account.objects.create(name="AVAIBE", kind="company")
        posts = [_post(f"https://www.linkedin.com/feed/update/urn:li:activity:{i}", f"09/{i:02d}/2026", "Video", f"Post {i} about AI")
                 for i in range(1, 8)]
        linkedin_export.import_file(self.acc, "c.xls", content_file(posts), EXPORTED)

    def test_heatmap_excludes_date_only_posts_and_weekday_groups_include_them(self):
        posts = analytics.load_posts(self.acc.id)
        self.assertEqual(analytics.main_checkpoint(posts), "7d")
        hm = analytics.heatmap(posts, "7d", "impressions", None)
        self.assertEqual(sum(c["posts"] for c in hm["cells"]), 0)
        self.assertEqual(hm["posts_without_time"], 7)
        days = analytics.groups(posts, "7d", "weekday")
        self.assertEqual(sum(g["posts"] for g in days), 7)
        self.assertEqual(days[0]["key"], "Monday")  # in week order

    def test_api_import_and_edit_confirms_topic(self):
        client = APIClient()
        with mock.patch("core.auth.authentication.auth_enabled", return_value=False):
            data = content_file([_post("https://www.linkedin.com/feed/update/urn:li:activity:77", "08/20/2026", "", "Your school LMS")])
            f = io.BytesIO(data)
            f.name = "avaibe_content_1794812594179.xls"
            res = client.post(f"/api/import/linkedin-export?account_id={self.acc.id}", {"files": [f], "exported_on": "2026-11-16"}, format="multipart")
            self.assertEqual(res.status_code, 200, res.content)
            self.assertEqual(res.json()["files"][0]["posts_created"], 1)

            p = Post.objects.get(linkedin_post_id="77")
            body = {"account_id": self.acc.id, "published_at": "2026-08-20T12:00:00", "format": "image", "topic": "Education & LMS",
                    "post_url": p.post_url, "keywords": [], "hashtags": []}
            res = client.put(f"/api/posts/{p.id}", body, format="json")
            self.assertEqual(res.status_code, 200, res.content)
            p.refresh_from_db()
            self.assertFalse(p.topic_suggested)
            self.assertFalse(p.time_known)  # the edit form doesn't send it, so it stays date-only
            self.assertEqual(p.format, "image")

    def test_linkedin_export_saved_as_csv_gets_a_clear_message(self):
        client = APIClient()
        with mock.patch("core.auth.authentication.auth_enabled", return_value=False):
            f = io.BytesIO(b"Date,Total followers,Organic followers" + bytes([10]) + b"11/01/2026,5,5" + bytes([10]))
            f.name = "followers.csv"
            res = client.post(f"/api/import/csv?account_id={self.acc.id}", {"file": f}, format="multipart")
            self.assertEqual(res.status_code, 400, res.content)
            self.assertIn("original Excel file", res.content.decode())

    def test_company_export_into_a_profile_needs_confirmation(self):
        founder = Account.objects.create(name="Founder", kind="founder", parent=self.acc)
        client = APIClient()

        def upload(**extra):
            f = io.BytesIO(content_file([_post("https://www.linkedin.com/feed/update/urn:li:activity:88", "08/21/2026", "", "Hello")]))
            f.name = "avaibe_content_1794812594179.xls"
            return client.post(f"/api/import/linkedin-export?account_id={founder.id}", {"files": [f], **extra}, format="multipart")

        with mock.patch("core.auth.authentication.auth_enabled", return_value=False):
            res = upload()
            self.assertEqual(res.status_code, 409, res.content)
            self.assertFalse(Post.objects.filter(account=founder).exists())  # nothing saved without a yes
            res = upload(confirm_profile="1")
            self.assertEqual(res.status_code, 200, res.content)
            self.assertEqual(Post.objects.filter(account=founder).count(), 1)

class SuggestionDecisionTests(TestCase):
    """Do it / Later / Dismiss are shared by the team, and "Later" comes back after a week."""

    def setUp(self):
        self.acc = Account.objects.create(name="AVAIBE", kind="company")
        self.client = APIClient()

    def _put(self, key, status):
        return self.client.put("/api/suggestions/decisions", {"account_id": self.acc.id, "key": key, "status": status}, format="json")

    def test_decide_undo_and_later_expires(self):
        from datetime import timedelta

        from core.common.timeutil import now_utc
        from core.models import SuggestionDecision

        with mock.patch("core.auth.authentication.auth_enabled", return_value=False):
            self.assertEqual(self._put("rule:tag-imported", "doing").status_code, 422)  # no "In progress" any more
            self.assertEqual(self._put("rule:tag-imported", "later").status_code, 200)
            self.assertEqual(self._put("rule:tag-imported", "done").json()["status"], "done")  # same row updated
            self.assertEqual(SuggestionDecision.objects.count(), 1)
            self.assertEqual(self._put("ai:1:2", "later").status_code, 200)
            keys = {d["key"] for d in self.client.get(f"/api/suggestions/decisions?account_id={self.acc.id}").json()}
            self.assertEqual(keys, {"rule:tag-imported", "ai:1:2"})

            SuggestionDecision.objects.filter(key="ai:1:2").update(until=now_utc() - timedelta(minutes=1))
            keys = {d["key"] for d in self.client.get(f"/api/suggestions/decisions?account_id={self.acc.id}").json()}
            self.assertEqual(keys, {"rule:tag-imported"})  # the week is up: back in the list

            self.assertEqual(self._put("rule:tag-imported", None).status_code, 200)  # undo
            self.assertFalse(SuggestionDecision.objects.filter(key="rule:tag-imported").exists())

            self.assertEqual(self._put("bad key!", "done").status_code, 422)
            self.assertEqual(self._put("rule:x", "maybe").status_code, 422)

class SimilarPostsTests(TestCase):
    """Ideas are compared with past posts on the same topic, most-alike first, against the account's typical post."""

    def test_same_topic_and_verdict(self):
        from datetime import datetime, timedelta, timezone

        acc = Account.objects.create(name="AVAIBE", kind="company")
        base = datetime(2026, 9, 1, 8, tzinfo=timezone.utc)
        rows = [
            ("AVAIBE Tech Debate", "Tech Debate: Team A vs Team B on AI coding tools", 400),
            ("AVAIBE Tech Debate", "Our latest debate brought two teams together", 300),
            ("Education & LMS", "Is your school LMS slowing teachers down?", 60),
            ("Education & LMS", "How UAE schools choose an LMS", 80),
            ("ERP & CRM", "ERP for UAE trading firms", 150),
        ]
        for i, (topic, cap, imp) in enumerate(rows):
            p = Post.objects.create(account=acc, published_at=base + timedelta(days=i), format="image", topic=topic, caption=cap)
            Snapshot.objects.create(post=p, checkpoint="24h", impressions=imp, captured_at=p.published_at + timedelta(hours=24))
        client = APIClient()
        q = [
            {"key": "debate", "text": "Turn the Tech Debate into a UAE business debate between two teams"},
            {"key": "school", "text": "School leaders series", "topic": "Education & LMS"},
            {"key": "none", "text": "Ask founders to share posts"},
        ]
        with mock.patch("core.auth.authentication.auth_enabled", return_value=False):
            r = client.post("/api/analytics/similar-posts", {"account_id": acc.id, "queries": q}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        res = r.json()["results"]
        self.assertEqual((res["debate"]["topic"], res["debate"]["count"], res["debate"]["verdict"]), ("AVAIBE Tech Debate", 2, "above"))
        self.assertEqual(res["debate"]["posts"][0]["impressions"], 400)  # "Team A vs Team B" shares more words
        self.assertEqual((res["school"]["count"], res["school"]["verdict"]), (2, "below"))

class TimingModelTests(TestCase):
    """The posting-time model finds effects that are really there, and doesn't invent ones that aren't."""

    @staticmethod
    def _posts(plant: bool, seed: int = 7):
        import math
        import random
        from datetime import timedelta

        from core.services.analytics.timing import WORK_SLOTS, Obs, day_labels

        rng = random.Random(seed)
        topics_ = {"erp": 0.3, "ai": 0.0, "lms": -0.2, "cyber": 0.1}
        fmts = {"video": 0.4, "image": -0.2, "newsletter": 0.1}
        obs, d = [], date(2025, 11, 20)
        while d <= date(2026, 11, 15):
            if d.weekday() < 5:
                for _ in range(rng.choice([1, 1, 2])):
                    slot, fmt, topic = rng.choice(WORK_SLOTS), rng.choice(list(fmts)), rng.choice(list(topics_))
                    labels = day_labels(d)
                    y = math.log(150) + 0.25 * (d - date(2025, 11, 20)).days / 360 + fmts[fmt] + topics_[topic]
                    if plant:
                        y += (0.35 if d.weekday() == 1 else 0) + (0.3 if slot == "4-6 PM" else 0) + (-0.45 if "ramadan" in labels else 0)
                    y += rng.gauss(0, 0.35)
                    obs.append(Obs(d, d.strftime("%A"), slot, fmt, topic, y, labels))
            d += timedelta(days=1)
        return obs

    def test_finds_planted_effects(self):
        from core.services.analytics.timing import _effect, fit

        obs = self._posts(plant=True)
        m = fit(obs)
        self.assertEqual(_effect(m, "Tuesday", m.day["Tuesday"], m.n_day["Tuesday"])["verdict"], "better")
        self.assertEqual(_effect(m, "4-6 PM", m.slot["4-6 PM"], m.n_slot["4-6 PM"])["verdict"], "better")
        self.assertEqual(_effect(m, "ramadan", m.special["ramadan"], m.n_special["ramadan"])["verdict"], "worse")
        # The video format effect is credited to the format, not to timing
        self.assertGreater(m.fmt["video"], m.fmt["image"] + 0.4)

    def test_no_false_best_time(self):
        from core.services.analytics.timing import _effect, fit

        obs = self._posts(plant=False)
        m = fit(obs)
        verdicts = [_effect(m, k, m.day[k], m.n_day[k])["verdict"] for k in m.day] + [
            _effect(m, k, m.slot[k], m.n_slot[k])["verdict"] for k in m.slot
        ]
        self.assertFalse({"better", "worse"} & set(verdicts), verdicts)

    def test_backtest_rates(self):
        """Over 10 datasets: the self-test usually confirms real timing effects and rarely 'confirms' noise."""
        from core.services.analytics.timing import backtest

        helps_real = sum(backtest(self._posts(True, s))["verdict"] == "helps" for s in range(1, 11))
        helps_noise = sum(backtest(self._posts(False, s))["verdict"] == "helps" for s in range(1, 11))
        self.assertGreaterEqual(helps_real, 7)
        self.assertLessEqual(helps_noise, 1)

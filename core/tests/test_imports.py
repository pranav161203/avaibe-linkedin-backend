"""Importing LinkedIn page-analytics exports (.xls/.xlsx) and CSV."""

from datetime import date

from django.test import TestCase

from core.models import Account, AccountDoc, PageAudience, PageDaily, Post, Snapshot
from core.services.imports import linkedin_export
from core.tests.factories import EXPORTED, _post, _xlsx, content_file


class ExportImportTests(TestCase):
    def setUp(self):
        self.acc = Account.objects.create(name="AVAIBE", kind="company")

    def _import(self, data: bytes, name="avaibe_content_1794812594179.xls"):
        return linkedin_export.import_file(self.acc, name, data, EXPORTED)

    def test_posts_snapshots_and_flags(self):
        r = self._import(content_file([
            _post("https://www.linkedin.com/feed/update/urn:li:activity:1", "08/20/2026", "Article",
                  "The UAE ERP market is changing. #ERP #UAE", impressions=209, views=5),
            _post("https://www.linkedin.com/feed/update/urn:li:activity:2", "11/13/2026", "", "Is your school ready? #LMS"),
            _post("https://www.linkedin.com/feed/update/urn:li:activity:3", "11/16/2026", "Video", "Posted today"),
        ]))
        self.assertEqual((r["posts_created"], r["snapshots_saved"], r["posts_too_new"]), (3, 2, 1))
        self.assertEqual(r["days_saved"], 1)

        old = Post.objects.get(linkedin_post_id="1")
        self.assertEqual(old.format, "newsletter")
        self.assertFalse(old.time_known)
        self.assertTrue(old.topic_suggested)
        self.assertEqual(old.topic, "ERP & CRM")
        self.assertEqual(old.hashtags, ["#erp", "#uae"])
        snap = old.snapshot_items.get()
        self.assertEqual((snap.checkpoint, snap.impressions, snap.newsletter_views, snap.reactions), ("7d", 209, 5, 8))
        self.assertIsNone(snap.followers_gained)  # LinkedIn left Follows blank: not recorded, not zero

        recent = Post.objects.get(linkedin_post_id="2")
        self.assertEqual(recent.format, "untagged")
        self.assertEqual(recent.snapshot_items.get().checkpoint, "48h")  # 3 days old at export

        self.assertEqual(PageDaily.objects.get(account=self.acc, date=date(2026, 11, 14)).impressions, 22)

    def test_reimport_keeps_manual_work(self):
        link = "https://www.linkedin.com/feed/update/urn:li:activity:9"
        self._import(content_file([_post(link, "08/20/2026", "", "Some caption about AI")]))
        p = Post.objects.get(post_url=link)
        p.format, p.topic, p.topic_suggested = "carousel", "My topic", False
        p.save()
        Snapshot.objects.filter(post=p).update(impressions=999, notes="typed in by hand")

        r = self._import(content_file([_post(link, "08/20/2026", "", "Some caption about AI", impressions=300)]))
        # The hand-typed numbers win, so nothing about the post changed
        self.assertEqual((r["posts_created"], r["posts_updated"], r["posts_unchanged"], r["snapshots_kept_manual"]), (0, 0, 1, 1))
        p.refresh_from_db()
        self.assertEqual((p.format, p.topic, p.topic_suggested), ("carousel", "My topic", False))
        self.assertEqual(p.snapshot_items.get().impressions, 999)

    def test_same_file_twice_is_reported_unchanged_and_adds_nothing(self):
        link = "https://www.linkedin.com/feed/update/urn:li:activity:11"
        first = self._import(content_file([_post(link, "08/20/2026", "Video", "x", impressions=100)]))
        self.assertEqual((first["posts_created"], first["posts_updated"], first["posts_unchanged"]), (1, 0, 0))
        again = self._import(content_file([_post(link, "08/20/2026", "Video", "x", impressions=100)]))
        self.assertEqual((again["posts_created"], again["posts_updated"], again["posts_unchanged"], again["snapshots_saved"]), (0, 0, 1, 0))
        self.assertEqual((again["days_new"], again["days_changed"], again["days_unchanged"]), (0, 0, again["days_saved"]))
        newer = self._import(content_file([_post(link, "08/20/2026", "Video", "x", impressions=180)]))
        self.assertEqual((newer["posts_created"], newer["posts_updated"], newer["posts_unchanged"]), (0, 1, 0))
        self.assertEqual((Post.objects.count(), Snapshot.objects.count()), (1, 1))  # never doubled
        last = AccountDoc.objects.get(account=self.acc, kind="last_imports").data
        self.assertEqual(last["content"]["exported_on"], "2026-11-16")

    def test_reimport_updates_export_snapshot(self):
        link = "https://www.linkedin.com/feed/update/urn:li:activity:10"
        self._import(content_file([_post(link, "08/20/2026", "Video", "x", impressions=100)]))
        self._import(content_file([_post(link, "08/20/2026", "Video", "x", impressions=150)]))
        self.assertEqual(Post.objects.get(post_url=link).snapshot_items.get().impressions, 150)
        self.assertEqual(Post.objects.count(), 1)

    def test_followers_and_visitors(self):
        followers = _xlsx({
            "New followers": [["Date", "Sponsored followers", "Organic followers", "Auto-invited followers", "Total followers"],
                              ["08/17/2026", 0, 6, 0, 6]],
            "Location": [["Location", "Total followers"], ["Dubai, United Arab Emirates", 88], ["Kochi, India", 139]],
            "Seniority": [["Seniority", "Total followers"], ["Senior", 300], ["Director", 100]],
        })
        r = self._import(followers, "avaibe_followers_1794812611016.xls")
        self.assertEqual((r["kind"], r["days_saved"], r["demographic_rows"], r["demographic_total"]), ("followers", 1, 4, 400))
        self.assertEqual(PageDaily.objects.get(date=date(2026, 8, 17)).new_followers, 6)
        self.assertEqual(PageAudience.objects.get(audience="followers", value="Dubai, United Arab Emirates").count, 88)
        self.assertEqual(r["demographic_status"], "new")
        again = self._import(followers, "avaibe_followers_1794812611016.xls")
        self.assertEqual((again["days_unchanged"], again["demographic_status"]), (1, "unchanged"))
        self.assertEqual(PageAudience.objects.filter(audience="followers").count(), 4)  # replaced, not doubled

        visitors = _xlsx({
            "Visitor metrics": [["Date", "Total page views (total)", "Total unique visitors (total)"], ["08/17/2026", 9, 4]],
            "Industry": [["Industry", "Total views"], ["Primary and Secondary Education", 26]],
        })
        self._import(visitors, "avaibe_visitors_1.xls")
        day = PageDaily.objects.get(date=date(2026, 8, 17))
        self.assertEqual((day.page_views, day.unique_visitors, day.new_followers), (9, 4, 6))  # merged, not replaced

    def test_empty_competitor_file_and_junk(self):
        r = self._import(_xlsx({"COMPETITORS": [["8/17/2026"]]}), "AVAIBE_competitor_analytics.xlsx")
        self.assertIn("empty", r["skipped"])
        with self.assertRaises(linkedin_export.ExportError):
            self._import(b"not a spreadsheet", "notes.txt")

    def test_export_date_from_filename(self):
        self.assertEqual(linkedin_export.export_date_from_filename("avaibe_content_1794812594179.xls").year, 2026)
        self.assertIsNone(linkedin_export.export_date_from_filename("content.xls"))



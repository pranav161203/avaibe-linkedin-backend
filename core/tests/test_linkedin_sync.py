"""LinkedIn sync end to end against the mock LinkedIn API (dev_tools/mock_linkedin)."""

from unittest import mock, skipUnless

from django.test import TestCase

from dev_tools.mock_linkedin import MOCK_DIR

CALIBRATION = MOCK_DIR / "calibration_demographics.json"


@skipUnless(CALIBRATION.exists(), "needs mock_data/calibration_demographics.json (private, kept off GitHub)")
class MockLinkedInSyncTests(TestCase):
    """End to end: dummy data → mock LinkedIn API (LinkedIn's formats and rules) → API client → sync → app tables."""

    def test_generate_serve_and_sync(self):
        import shutil
        import tempfile
        from datetime import date, datetime, timezone
        from pathlib import Path

        import httpx
        from django.core import signals
        from django.core.wsgi import get_wsgi_application
        from django.db import close_old_connections
        from django.test import override_settings

        from core.integrations.linkedin.community_api import (
            LinkedInAPI,
            LinkedInAPIError,
        )
        from core.models import Account, PageAudience, PageDaily, Post
        from core.services.linkedin_sync import sync_company, sync_member
        from dev_tools import mock_linkedin
        from dev_tools.mock_linkedin import generate, server

        # The mock API is called in-process through Django; Django closes the DB connection after each
        # request, which would close this test's own transaction. Keep it open for the test.
        signals.request_started.disconnect(close_old_connections)
        signals.request_finished.disconnect(close_old_connections)
        self.addCleanup(signals.request_started.connect, close_old_connections)
        self.addCleanup(signals.request_finished.connect, close_old_connections)

        tmp = Path(tempfile.mkdtemp())
        try:
            world = generate.generate(mock_linkedin.MOCK_DIR / "calibration_demographics.json", tmp / "linkedin_world.json", date(2026, 11, 17))
            with mock.patch.object(server, "MOCK_DIR", tmp), override_settings(ROOT_URLCONF="dev_tools.mock_linkedin.test_urls"):
                server._cache.update(mtime=None, world=None)
                transport = httpx.WSGITransport(app=get_wsgi_application())

                def client(token):
                    api = LinkedInAPI(token, base="http://testserver/mock-linkedin")
                    api.http = httpx.Client(transport=transport)
                    return api

                # LinkedIn's rules: wrong token refused, a person's post list refused
                with self.assertRaises(LinkedInAPIError) as e:
                    client("nope").get("/rest/posts", "q=author&author=urn%3Ali%3Aorganization%3A91234567")
                self.assertEqual(e.exception.status, 401)
                with self.assertRaises(LinkedInAPIError) as e:
                    client("mock-page-admin").get("/rest/posts", "q=author&author=urn%3Ali%3Aperson%3Aabc")
                self.assertEqual(e.exception.status, 403)

                now = datetime(2026, 11, 18, 6, tzinfo=timezone.utc)
                company = Account.objects.create(name="Demo company", kind="company", is_test=True, linkedin_urn=world["organization"]["urn"])
                r = sync_company(company, client("mock-page-admin"), now=now)
                self.assertEqual(r.posts_created, len(world["posts"]))
                self.assertTrue(all(p.time_known for p in Post.objects.filter(account=company)))
                self.assertEqual(PageDaily.objects.filter(account=company).count(), 365)
                self.assertEqual(PageAudience.objects.filter(account=company, audience="followers").first().total, 4060)
                self.assertTrue(PageAudience.objects.filter(account=company, value__contains="United Arab Emirates").exists())
                # Per-post lifetime numbers match what the dummy data says
                p0 = world["posts"][0]
                snap = Post.objects.get(linkedin_post_id=p0["id"]).snapshot_items.get()
                self.assertEqual((snap.impressions, snap.checkpoint), (p0["stats"]["impressionCount"], "7d"))

                founder = Account.objects.create(name="Founder", kind="founder", is_test=True, linkedin_urn=world["members"][0]["urn"])
                fp = world["members"][0]["posts"][-1]
                Post.objects.create(account=founder, post_url="https://x/1", linkedin_post_id=fp["id"], format="text",
                                    published_at=datetime.fromtimestamp(fp["publishedAt"] / 1000, tz=timezone.utc))
                r = sync_member(founder, client("mock-founder-ceo"), now=now)
                self.assertEqual(r.snapshots, 1)
                s = Post.objects.get(account=founder).snapshot_items.get()
                self.assertEqual((s.impressions, s.saves), (fp["metrics"]["IMPRESSION"], fp["metrics"]["POST_SAVE"]))
                # A founder token can't read the other founder's analytics
                other = world["members"][1]["posts"][0]["id"]
                with self.assertRaises(LinkedInAPIError):
                    client("mock-founder-ceo").get("/rest/memberCreatorPostAnalytics", f"q=entity&entity=(share:{other})&queryType=IMPRESSION&aggregation=TOTAL")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            server._cache.update(mtime=None, world=None)

"""Publishing queue: planned post formats, publishing, and the Excel plan import."""

import io
from unittest import mock

import openpyxl
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Account, Post


class PlannedFormatTests(TestCase):
    """Publishing queue by format: hand-posted formats are never auto-published, and Mark as posted starts tracking."""

    def setUp(self):
        self.acc = Account.objects.create(name="AVAIBE", kind="company")
        self.client = APIClient()

    def _create(self, **kw):
        body = {"account_id": self.acc.id, "caption": "Hello #UAE", "goal": "brand", **kw}
        return self.client.post("/api/planner", body, format="json")

    def test_unconnected_account_is_scheduled_by_hand(self):
        from core.models import PlannedPost
        from core.services import publishing as publisher

        with mock.patch("core.auth.authentication.auth_enabled", return_value=False):
            r = self._create(scheduled_at="2030-01-01T06:00:00Z").json()  # a text post, but no LinkedIn connection
            self.assertTrue(r["by_hand"])
            self.assertFalse(r["manual"])
            self.assertEqual(self.client.post(f"/api/planner/{r['id']}/approve").json()["status"], "approved")
            PlannedPost.objects.filter(id=r["id"]).update(scheduled_at="2026-01-01T00:00:00Z")
            publisher.run_due()  # due, but the app can't post it: left for the team, not failed or missed
            self.assertEqual(PlannedPost.objects.get(id=r["id"]).status, "approved")

    def test_publish_now_works_after_the_planned_time_passed(self):
        from core.models import PlannedPost

        with mock.patch("core.auth.authentication.auth_enabled", return_value=False):
            pid = self._create().json()["id"]
            PlannedPost.objects.filter(id=pid).update(scheduled_at="2020-01-01T06:00:00Z")
            self.assertEqual(self.client.post(f"/api/planner/{pid}/approve").status_code, 400)  # can't schedule into the past
            self.assertEqual(self.client.post(f"/api/planner/{pid}/approve", {"now": True}, format="json").status_code, 200)

    def test_editing_an_approved_post_needs_approval_again(self):
        with mock.patch("core.auth.authentication.auth_enabled", return_value=False):
            pid = self._create(scheduled_at="2030-01-01T06:00:00Z").json()["id"]
            self.assertEqual(self.client.post(f"/api/planner/{pid}/approve").status_code, 200)
            r = self.client.put(f"/api/planner/{pid}", {"account_id": self.acc.id, "caption": "Changed", "goal": "brand"}, format="json")
            self.assertEqual((r.status_code, r.json()["status"]), (200, "draft"))

    def test_goal_is_required_and_kept(self):
        with mock.patch("core.auth.authentication.auth_enabled", return_value=False):
            r = self.client.post("/api/planner", {"account_id": self.acc.id, "caption": "Hello"}, format="json")
            self.assertEqual(r.status_code, 422)
            self.assertEqual(self._create(goal="nonsense").status_code, 422)
            r = self._create(goal="sales")
            self.assertEqual((r.status_code, r.json()["goal"]), (201, "sales"))

    def test_carousel_slides_are_kept_with_the_post(self):
        slides = [{"headline": "5 signs your LMS is too old", "body": ""}, {"headline": "1. Teachers export to Excel", "body": "Every week."}]
        with mock.patch("core.auth.authentication.auth_enabled", return_value=False):
            r = self._create(format="carousel", details={"document_title": "LMS signs", "slides": slides, "carousel_theme": "dark", "carousel_accent": "#4F46E5"})
            self.assertEqual(r.status_code, 201, r.content)
            self.assertEqual(r.json()["details"]["slides"], slides)
            self.assertEqual(r.json()["details"]["carousel_theme"], "dark")
            # Slides belong to carousels only; a bad colour is refused
            r = self._create(format="text", details={"slides": slides})
            self.assertNotIn("slides", r.json()["details"])
            self.assertEqual(self._create(format="carousel", details={"carousel_accent": "blue"}).status_code, 422)

    def test_formats_details_and_mark_posted(self):
        from core.models import PlannedPost
        from core.services import publishing as publisher

        with mock.patch("core.auth.authentication.auth_enabled", return_value=False):
            # Poll needs a question and 2-4 options of up to 30 characters
            self.assertEqual(self._create(format="poll", details={"question": "Which?"}).status_code, 422)
            self.assertEqual(self._create(format="poll", details={"question": "Which?", "options": ["a"]}).status_code, 422)
            self.assertEqual(self._create(format="poll", details={"question": "Which?", "options": ["a", "x" * 31]}).status_code, 422)
            r = self._create(format="poll", details={"question": "Which?", "options": ["ERP", "CRM", " "], "duration": "1w", "title": "dropped"})
            self.assertEqual(r.status_code, 201, r.content)
            poll = r.json()
            self.assertEqual(poll["details"], {"question": "Which?", "options": ["ERP", "CRM"], "duration": "1w"})  # other formats' fields dropped
            self.assertTrue(poll["manual"])

            # Approved + scheduled in the past: the scheduler must not touch a hand-posted format
            self.client.post(f"/api/planner/{poll['id']}/approve")
            PlannedPost.objects.filter(id=poll["id"]).update(scheduled_at="2026-01-01T00:00:00Z")
            publisher.run_due()
            self.assertEqual(PlannedPost.objects.get(id=poll["id"]).status, "approved")
            self.assertEqual(self.client.post(f"/api/planner/{poll['id']}/publish").status_code, 409)

            # Mark as posted: bad link refused, good link creates a tracked poll
            self.assertEqual(self.client.post(f"/api/planner/{poll['id']}/mark-posted", {"post_url": "https://example.com/x"}, format="json").status_code, 400)
            link = "https://www.linkedin.com/posts/avaibe_erp-activity-7526958329584267264-AbCd"
            r = self.client.post(f"/api/planner/{poll['id']}/mark-posted", {"post_url": link}, format="json")
            self.assertEqual(r.status_code, 200, r.content)
            self.assertEqual(r.json()["status"], "published")
            # One ID for the post: the tracked post keeps the draft's readable ID
            self.assertRegex(poll["ref"], r"^P-\d{4,}$")
            self.assertEqual(Post.objects.get(id=r.json()["post_id"]).ref, poll["ref"])
            post = Post.objects.get(linkedin_post_id="7526958329584267264")
            self.assertEqual((post.format, post.post_url), ("poll", "https://www.linkedin.com/feed/update/urn:li:activity:7526958329584267264"))

            # Article maps to the tracking format "newsletter"; a link already tracked is reused, not duplicated
            art = self._create(format="article", details={"title": "Gulf brief", "link": "https://avaibe.com/blog/x"}).json()
            self.client.post(f"/api/planner/{art['id']}/approve")
            r = self.client.post(f"/api/planner/{art['id']}/mark-posted", {"post_url": link}, format="json")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(Post.objects.count(), 1)

            # Switching an image post to text removes its image; media only for carousel/video
            text = self._create(format="text").json()
            self.assertEqual(self.client.post(f"/api/planner/{text['id']}/media", {}, format="multipart").status_code, 400)

class PlanImportTests(TestCase):
    """Planning posts from the Excel template: check first, save only ready rows, never twice."""

    def setUp(self):
        self.acc = Account.objects.create(name="AVAIBE", kind="company")
        self.client = APIClient()

    def _file(self, rows):
        from django.core.files.uploadedfile import SimpleUploadedFile

        wb = openpyxl.load_workbook(io.BytesIO(self.client.get("/api/planner/import/template").content))
        ws = wb["Posts"]
        for r in rows:
            ws.append(r)
        buf = io.BytesIO()
        wb.save(buf)
        return SimpleUploadedFile("plan.xlsx", buf.getvalue())

    def _post(self, rows, confirm=False):
        q = f"?account_id={self.acc.id}" + ("&confirm=1" if confirm else "")
        return self.client.post(f"/api/planner/import{q}", {"file": self._file(rows)}, format="multipart")

    def test_template_has_dropdown_sheets(self):
        with mock.patch("core.auth.authentication.auth_enabled", return_value=False):
            wb = openpyxl.load_workbook(io.BytesIO(self.client.get("/api/planner/import/template").content))
        self.assertEqual(wb.sheetnames, ["Posts", "How to fill", "Example"])
        self.assertEqual(wb["Posts"]["C1"].value, "Format")

    def test_check_then_import_ready_rows_once(self):
        from core.models import PlannedPost

        rows = [
            ["2030-01-05", "10:30", "Text", "Sales", "VAT season #ERP", "ERP & CRM"],
            ["2030-01-06", "", "Text", "Sales", "No time given"],
            ["", "", "Poll", "Engagement", "Vote!", None, None, None, None, None, None, "Best day?", "Mon; Tue; Wed", "3 days"],
            ["", "", "Image", "", "No goal"],
        ]
        with mock.patch("core.auth.authentication.auth_enabled", return_value=False):
            check = self._post(rows).json()
            self.assertEqual((check["ready"], check["errors"], check["created"]), (2, 2, 0))
            self.assertEqual(PlannedPost.objects.count(), 0)  # checking never saves
            done = self._post(rows, confirm=True).json()
            self.assertEqual(done["created"], 2)
            poll = PlannedPost.objects.get(format="poll")
            self.assertEqual((poll.status, poll.details["options"], poll.details["duration"]), ("draft", ["Mon", "Tue", "Wed"], "3d"))
            self.assertTrue(PlannedPost.objects.get(format="text").ref.startswith("P-"))
            again = self._post(rows, confirm=True).json()  # the same file twice adds nothing
            self.assertEqual((again["created"], again["duplicates"]), (0, 2))

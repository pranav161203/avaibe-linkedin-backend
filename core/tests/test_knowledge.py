"""Company knowledge base: chunking, files, search, editing and who may change it."""

import io
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Account, KnowledgeChunk, KnowledgeSource
from core.services import knowledge

FAQ = """# Services

AVAIBE builds custom software, ERP systems and school management systems for UAE businesses.

## Education

Our LMS is used by schools in Dubai and Sharjah. It supports Arabic and English.

## Contact

Email hello@example.com for a demo."""


class ChunkingTests(TestCase):
    def test_chunks_keep_their_heading(self):
        chunks = knowledge.chunk_text(FAQ)
        self.assertEqual([h for h, _ in chunks], ["Services", "Education", "Contact"])
        self.assertIn("LMS", chunks[1][1])
        self.assertEqual(knowledge.section_count(FAQ), 3)

    def test_long_text_is_split_near_the_target(self):
        text = " ".join(f"Sentence number {i} about ERP projects in the UAE." for i in range(200))
        chunks = knowledge.chunk_text(text)
        self.assertGreater(len(chunks), 5)
        self.assertTrue(all(len(t) <= knowledge.CHUNK_MAX for _, t in chunks))
        self.assertEqual(" ".join(t for _, t in chunks).count("Sentence number"), 200)  # nothing lost

    def test_word_file_headings_become_sections(self):
        import docx

        d = docx.Document()
        d.add_heading("Case study: Next Generation School", level=1)
        d.add_paragraph("We moved the school to a new LMS in six weeks.")
        d.add_heading("Results", level=2)
        d.add_paragraph("Teachers saved two hours a week.")
        buf = io.BytesIO()
        d.save(buf)
        text = knowledge.read_file("case.docx", buf.getvalue())
        self.assertEqual([h for h, _ in knowledge.chunk_text(text)], ["Case study: Next Generation School", "Results"])

    def test_heading_without_blank_line_still_starts_a_section(self):
        self.assertEqual([h for h, _ in knowledge.chunk_text("# A\nfirst\n## B\nsecond")], ["A", "B"])

    def test_unsupported_and_empty_files(self):
        with self.assertRaises(knowledge.KnowledgeError):
            knowledge.read_file("photo.png", b"x")
        with self.assertRaises(knowledge.KnowledgeError):
            knowledge.add_source("Empty", "   ", None)


class KnowledgeApiTests(TestCase):
    def setUp(self):
        self.acc = Account.objects.create(name="AVAIBE", kind="company")
        self.client = APIClient()
        self.local = mock.patch("core.auth.authentication.auth_enabled", return_value=False)
        self.local.start()
        self.addCleanup(self.local.stop)

    def test_add_search_edit_delete(self):
        r = self.client.post("/api/knowledge", {"title": "About AVAIBE", "content": FAQ}, format="json")
        self.assertEqual(r.status_code, 201)
        sid = r.json()["id"]
        self.assertEqual((r.json()["chunks"], r.json()["sections"]), (3, 3))

        hits = self.client.get("/api/knowledge/search", {"q": "Which schools use the LMS?", "account_id": self.acc.id}).json()["results"]
        self.assertEqual(hits[0]["heading"], "Education")
        self.assertIn("source=\"About AVAIBE\" section=\"Education\"", knowledge.context_block("LMS schools", self.acc.id))

        r = self.client.put(f"/api/knowledge/{sid}", {"title": "About AVAIBE", "content": FAQ + "\n\n## Cloud\n\nWe run DevOps on Azure."}, format="json")
        self.assertEqual(r.json()["chunks"], 4)
        self.assertEqual(KnowledgeChunk.objects.filter(source_id=sid).count(), 4)  # rebuilt, not added to

        listing = self.client.get(f"/api/knowledge?account_id={self.acc.id}").json()
        self.assertEqual((len(listing["sources"]), listing["total_chunks"]), (1, 4))
        self.assertEqual(self.client.delete(f"/api/knowledge/{sid}").status_code, 204)
        self.assertEqual(KnowledgeChunk.objects.count(), 0)

    def test_upload_markdown_file(self):
        f = SimpleUploadedFile("services.md", FAQ.encode())
        r = self.client.post("/api/knowledge", {"file": f}, format="multipart")
        self.assertEqual(r.status_code, 201)
        self.assertEqual((r.json()["title"], r.json()["kind"], r.json()["file_name"]), ("services", "file", "services.md"))

    def test_viewers_cannot_change_it(self):
        from core.models import User

        KnowledgeSource.objects.create(title="x", content="y", chars=1)
        viewer = User.objects.create_user("v@example.com", role="viewer")
        with mock.patch("core.auth.authentication.auth_enabled", return_value=True),                 mock.patch("core.auth.permissions.default_account_id", return_value=self.acc.id):
            self.client.force_login(viewer)
            self.assertEqual(self.client.get(f"/api/knowledge?account_id={self.acc.id}").status_code, 200)
            self.assertEqual(self.client.post("/api/knowledge", {"title": "a", "content": "b"}, format="json").status_code, 403)

    def test_applies_to_keeps_pages_apart(self):
        other = Account.objects.create(name="Sister brand", kind="company")
        shared = self.client.post("/api/knowledge", {"title": "Company-wide", "content": "We build LMS platforms."}, format="json").json()
        own = self.client.post("/api/knowledge", {"title": "Sister only", "content": "Sister brand sells LMS hardware.", "account_ids": [other.id]}, format="json").json()
        self.assertEqual((shared["account_ids"], own["account_ids"]), ([], [other.id]))

        def titles(acc):
            return {s["title"] for s in self.client.get(f"/api/knowledge?account_id={acc.id}").json()["sources"]}

        self.assertEqual(titles(self.acc), {"Company-wide"})
        self.assertEqual(titles(other), {"Company-wide", "Sister only"})
        # Claude for AVAIBE never gets the sister brand's passages
        self.assertNotIn("hardware", knowledge.context_block("LMS", self.acc.id))
        self.assertIn("hardware", knowledge.context_block("LMS", other.id))
        hits = self.client.get(f"/api/knowledge/search?q=LMS&account_id={self.acc.id}").json()["results"]
        self.assertEqual({h["source_title"] for h in hits}, {"Company-wide"})

    def test_people_only_see_and_change_their_accounts(self):
        from core.models import User

        other = Account.objects.create(name="Sister brand", kind="company")
        own = KnowledgeSource.objects.create(title="Sister only", content="x", chars=1)
        own.accounts.set([other])
        editor = User.objects.create_user("e@example.com", role="editor")  # no account switching: default account only
        with mock.patch("core.auth.authentication.auth_enabled", return_value=True), \
                mock.patch("core.auth.permissions.default_account_id", return_value=self.acc.id):
            self.client.force_login(editor)
            self.assertEqual(self.client.get(f"/api/knowledge/{own.id}").status_code, 404)
            self.assertEqual(self.client.delete(f"/api/knowledge/{own.id}").status_code, 404)
            r = self.client.post("/api/knowledge", {"title": "a", "content": "b", "account_ids": [other.id]}, format="json")
            self.assertEqual(r.status_code, 404)

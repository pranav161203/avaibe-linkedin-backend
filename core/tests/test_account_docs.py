"""Account documents (page checklist, competitors, member totals)."""

from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Account


class AccountDocTests(TestCase):
    """Brand → Page checklist and Competitors: shared per account, validated, and fed to Claude."""

    def setUp(self):
        self.acc = Account.objects.create(name="AVAIBE", kind="company")
        self.client = APIClient()

    def test_checklist_and_competitors(self):
        from core.services.account_docs import competitor_names

        base = f"/api/accounts/{self.acc.id}/docs"
        with mock.patch("core.auth.authentication.auth_enabled", return_value=False):
            r = self.client.get(f"{base}/page_checklist").json()
            self.assertEqual((r["data"], r["updated_at"]), ({"items": {}}, None))  # empty until saved
            r = self.client.put(f"{base}/page_checklist", {"items": {"tagline": {"done": True, "note": "Says UAE"}}}, format="json")
            self.assertEqual(r.status_code, 200, r.content)
            self.assertTrue(self.client.get(f"{base}/page_checklist").json()["data"]["items"]["tagline"]["done"])

            comp = {"id": "c1", "name": "Acme ERP", "segment": "erp", "website": "https://acme.example", "followers": 1200, "posts_per_week": 3}
            self.assertEqual(self.client.put(f"{base}/competitors", {"competitors": [comp]}, format="json").status_code, 200)
            self.assertEqual(competitor_names(self.acc.id), ["Acme ERP"])

            self.assertEqual(self.client.put(f"{base}/competitors", {"competitors": [{**comp, "website": "not a link"}]}, format="json").status_code, 422)
            self.assertEqual(self.client.put(f"{base}/competitors", {"competitors": [{**comp, "segment": "bakery"}]}, format="json").status_code, 422)
            self.assertEqual(self.client.get(f"{base}/nonsense").status_code, 404)

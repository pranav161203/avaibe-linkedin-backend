"""Leads API."""

from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Account


class LeadsApiTests(TestCase):
    """Leads log / pipeline: business facts only, closing date follows the stage."""

    def test_create_move_and_reject_personal_fields(self):
        acc = Account.objects.create(name="Co", kind="company")
        client = APIClient()
        body = {"account_id": acc.id, "received_on": "2026-11-10", "source": "company_post", "company": "Example School",
                "in_uae": True, "role": "Principal", "decision_maker": True, "service": "LMS", "value_aed": 40000}
        with mock.patch("core.auth.authentication.auth_enabled", return_value=False):
            r = client.post("/api/leads", body, format="json")
            self.assertEqual(r.status_code, 201, r.content)
            lead = r.json()
            self.assertEqual((lead["stage"], lead["closed_on"]), ("new", None))
            # Won: a closing date is set; reopened: it's cleared
            r = client.put(f"/api/leads/{lead['id']}", {**body, "stage": "won"}, format="json")
            self.assertIsNotNone(r.json()["closed_on"])
            r = client.put(f"/api/leads/{lead['id']}", {**body, "stage": "talking", "closed_on": "2026-11-12"}, format="json")
            self.assertIsNone(r.json()["closed_on"])
            # No personal details: unknown fields such as a name or email are refused
            r = client.post("/api/leads", {**body, "contact_email": "someone@example.com"}, format="json")
            self.assertEqual(r.status_code, 422)
            self.assertEqual(len(client.get("/api/leads", {"account_id": acc.id}).json()), 1)
            # Qualified by default = UAE-based decision-maker; the team can override it
            self.assertTrue(lead["is_qualified"])
            r = client.put(f"/api/leads/{lead['id']}", {**body, "qualified": False}, format="json")
            self.assertEqual((r.json()["qualified"], r.json()["is_qualified"]), (False, False))
            r = client.put(f"/api/leads/{lead['id']}", {**body, "in_uae": None}, format="json")
            self.assertIsNone(r.json()["is_qualified"])  # unknown until UAE is known
            # First reply: recorded once, not moved by a second click
            first = client.post(f"/api/leads/{lead['id']}/replied").json()["replied_at"]
            self.assertIsNotNone(first)
            self.assertEqual(client.post(f"/api/leads/{lead['id']}/replied").json()["replied_at"], first)

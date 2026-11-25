"""Settings sections belong to one company: saving for one never changes another's, and analytics use the
settings of the account's company."""

from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Account, Company, CompanySetting, User
from core.services import settings_store
from core.tests.factories import sign_in

PERF = {"min_history": 12, "min_slot_posts": 4, "cut_high": 0.9, "cut_above": 0.65, "cut_average": 0.35, "cut_below": 0.1, "trend_threshold": 0.1}


class CompanySettingsTests(TestCase):
    def setUp(self):
        on = mock.patch("core.auth.authentication.auth_enabled", return_value=True)
        on.start()
        self.addCleanup(on.stop)
        settings_store.invalidate()
        self.addCleanup(settings_store.invalidate)
        self.a = Company.objects.get_or_create(slug="avaibe", defaults={"name": "AVAIBE"})[0]
        self.b = Company.objects.create(name="Gulf Schools", slug="gulf-schools")
        self.acc_a = Account.objects.create(name="AVAIBE page", kind="company", company=self.a)
        self.acc_b = Account.objects.create(name="Gulf page", kind="company", company=self.b)
        self.owner = User.objects.create_user("owner@avaibe.com", role="superadmin", can_switch_accounts=True)
        self.admin_b = User.objects.create_user("admin@gulf.test", role="admin", company=self.b)

    def as_user(self, user):
        return sign_in(APIClient(), user)

    def test_company_admin_saves_only_their_own_company(self):
        c = self.as_user(self.admin_b)
        # A company_id for another company is ignored: admins only ever manage their own
        res = c.put(f"/api/settings/performance?company_id={self.a.id}", PERF, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(settings_store.get("performance", self.b.id)["min_history"], 12)
        self.assertEqual(settings_store.get("performance", self.a.id)["min_history"], settings_store.DEFAULTS["performance"]["min_history"])
        row = CompanySetting.objects.get(company=self.b, section="performance")
        self.assertEqual(row.created_by_id, self.admin_b.id)
        self.assertEqual(c.get("/api/settings").json()["company_id"], self.b.id)

    def test_owner_chooses_the_company(self):
        c = self.as_user(self.owner)
        self.assertEqual(c.get("/api/settings").status_code, 400)  # two companies: must say which
        res = c.put(f"/api/settings/performance?company_id={self.a.id}", PERF, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(c.get(f"/api/settings?company_id={self.a.id}").json()["current"]["performance"]["min_history"], 12)
        self.assertEqual(c.get(f"/api/settings?company_id={self.b.id}").json()["current"]["performance"]["min_history"], 8)
        c.post(f"/api/settings/performance/reset?company_id={self.a.id}")
        self.assertFalse(CompanySetting.objects.filter(company=self.a, section="performance").exists())

    def test_analytics_use_the_accounts_company_settings(self):
        settings_store.save("performance", PERF, self.b.id)
        c = self.as_user(self.owner)
        meta_b = c.get(f"/api/analytics/meta?account_id={self.acc_b.id}").json()
        meta_a = c.get(f"/api/analytics/meta?account_id={self.acc_a.id}").json()
        self.assertEqual(meta_b["min_history"], 12)
        self.assertEqual(meta_a["min_history"], 8)

    def test_new_company_brand_kit_starts_empty(self):
        self.assertEqual(settings_store.get("brand", self.b.id)["company_summary"], "")

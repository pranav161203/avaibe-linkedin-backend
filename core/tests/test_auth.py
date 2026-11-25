"""Sign-in, tokens, invitations, companies, roles, account access and the read-only demo mode."""

from datetime import timedelta
from unittest import mock

import jwt
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.auth.cookies import ACCESS_COOKIE, REFRESH_COOKIE
from core.common.timeutil import now_utc
from core.conf import jwt_signing_key
from core.models import Account, AuthSession, Company, Invitation, RefreshToken, User
from core.tests.factories import sign_in

PASSWORD = "lime-harbour-42-sunset"


class AuthTestCase(TestCase):
    def setUp(self):
        on = mock.patch("core.auth.authentication.auth_enabled", return_value=True)
        on.start()
        self.addCleanup(on.stop)
        self.company = Company.objects.get_or_create(slug="avaibe", defaults={"name": "AVAIBE"})[0]
        self.acc = Account.objects.create(name="AVAIBE", kind="company", company=self.company)
        self.superadmin = User.objects.create_user("super@avaibe.com", role="superadmin", can_switch_accounts=True)
        self.admin = User.objects.create_user("admin@avaibe.com", PASSWORD, role="admin", company=self.company)
        self.editor = User.objects.create_user("editor@avaibe.com", role="editor", company=self.company)
        self.viewer = User.objects.create_user("viewer@avaibe.com", role="viewer", company=self.company)

    def as_user(self, user):
        return sign_in(APIClient(), user)

    def login(self, email, password, client=None):
        c = client or APIClient()
        return c, c.post("/api/auth/login", {"email": email, "password": password}, format="json")


class RolesAndSecurityTests(AuthTestCase):
    """Who may manage whom, and that the rules hold on the server (not just in the screens)."""

    def member(self, u, **kw):
        return {"email": u.email, "role": u.role, "can_switch_accounts": False, "active": True, **kw}

    def test_admins_manage_viewers_and_editors_only(self):
        c = self.as_user(self.admin)
        self.assertEqual(c.put(f"/api/team/{self.viewer.id}", self.member(self.viewer, role="editor"), format="json").status_code, 200)
        # can't promote to admin, can't touch a super admin, can't invite an admin
        self.assertEqual(c.put(f"/api/team/{self.editor.id}", self.member(self.editor, role="admin"), format="json").status_code, 403)
        self.assertEqual(c.put(f"/api/team/{self.superadmin.id}", self.member(self.superadmin, role="viewer"), format="json").status_code, 404)
        self.assertEqual(c.post("/api/team", {"email": "new@avaibe.com", "role": "admin"}, format="json").status_code, 403)
        r = c.post("/api/team", {"email": "new@avaibe.com", "role": "editor"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertIn("/signup?token=", r.json()["link"])
        self.assertFalse(User.objects.filter(email="new@avaibe.com").exists())  # an invitation, not an account yet

    def test_nobody_changes_their_own_role_and_one_super_admin_always_remains(self):
        c = self.as_user(self.superadmin)
        self.assertEqual(c.put(f"/api/team/{self.superadmin.id}", self.member(self.superadmin, role="viewer"), format="json").status_code, 400)
        self.assertEqual(c.delete(f"/api/team/{self.superadmin.id}").status_code, 400)
        # a super admin without a company can't be given a company role
        c2 = self.as_user(User.objects.create_user("super2@avaibe.com", role="superadmin"))
        self.assertEqual(c2.put(f"/api/team/{self.superadmin.id}", self.member(self.superadmin, role="admin"), format="json").status_code, 400)
        # a company admin can be promoted, keeping their company
        self.assertEqual(c.put(f"/api/team/{self.admin.id}", self.member(self.admin, role="superadmin"), format="json").status_code, 200)

    def test_lower_roles_are_refused_on_the_server(self):
        v = self.as_user(self.viewer)
        self.assertEqual(v.get("/api/accounts").status_code, 200)  # viewers can read
        self.assertEqual(v.post("/api/planner", {"account_id": self.acc.id, "caption": "x", "goal": "brand"}, format="json").status_code, 403)
        self.assertEqual(v.get("/api/team").status_code, 403)
        e = self.as_user(self.editor)
        self.assertEqual(e.put("/api/settings/brand", {}, format="json").status_code, 403)
        self.assertEqual(APIClient().get("/api/accounts").status_code, 401)  # nobody signed in
        self.assertEqual(self.as_user(self.admin).get("/api/companies").status_code, 403)  # super admins only

    def test_database_screens_are_super_admin_only(self):
        self.assertFalse(self.admin.is_staff)
        self.assertTrue(self.superadmin.is_staff)
        c = APIClient()
        c.force_login(self.admin)  # the /admin screens keep Django's own session
        self.assertNotEqual(c.get("/admin/core/user/").status_code, 200)

    def test_open_demo_is_read_only(self):
        with mock.patch("core.auth.authentication.auth_enabled", return_value=False), mock.patch.dict("os.environ", {"READ_ONLY_WITHOUT_SIGNIN": "true"}):
            c = APIClient()
            self.assertEqual(c.get("/api/accounts").status_code, 200)
            r = c.post("/api/planner", {"account_id": self.acc.id, "caption": "x", "goal": "brand"}, format="json")
            self.assertEqual(r.status_code, 403)
            self.assertIn("read-only", r.content.decode())


class PasswordAndTokenTests(AuthTestCase):
    def test_sign_in_sets_two_httponly_cookies(self):
        c, r = self.login("ADMIN@avaibe.com ", PASSWORD)
        self.assertEqual(r.status_code, 200)
        access, refresh = r.cookies[ACCESS_COOKIE], r.cookies[REFRESH_COOKIE]
        self.assertTrue(access["httponly"] and refresh["httponly"])
        self.assertEqual(refresh["path"], "/api/auth/")  # the refresh token only goes to the sign-in endpoints
        self.assertEqual(c.get("/api/auth/me").json()["user"]["company"], {"id": self.company.id, "name": "AVAIBE"})
        self.assertEqual(c.get("/api/accounts").status_code, 200)

    def test_wrong_password_and_unknown_email_look_the_same_then_lock(self):
        _, wrong = self.login("admin@avaibe.com", "nope")
        _, unknown = self.login("nobody@avaibe.com", "nope")
        self.assertEqual((wrong.status_code, unknown.status_code), (401, 401))
        self.assertEqual(wrong.json(), unknown.json())
        for _ in range(4):
            self.login("admin@avaibe.com", "nope")
        _, locked = self.login("admin@avaibe.com", PASSWORD)  # right password, but locked for now
        self.assertEqual(locked.status_code, 429)

    @override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.Argon2PasswordHasher"])
    def test_passwords_are_stored_as_argon2id_hashes(self):
        u = User.objects.create_user("hash@avaibe.com", PASSWORD, role="viewer", company=self.company)
        self.assertTrue(u.password.startswith("argon2$argon2id$"))
        self.assertNotIn(PASSWORD, u.password)
        self.assertTrue(u.check_password(PASSWORD))

    def test_refresh_rotates_and_a_reused_token_signs_the_session_out(self):
        c, r = self.login("admin@avaibe.com", PASSWORD)
        first = r.cookies[REFRESH_COOKIE].value
        r2 = c.post("/api/auth/refresh")
        self.assertEqual(r2.status_code, 200)
        self.assertNotEqual(r2.cookies[REFRESH_COOKIE].value, first)
        self.assertEqual(RefreshToken.objects.filter(used_at__isnull=True).count(), 1)
        self.assertFalse(RefreshToken.objects.filter(token_hash=first).exists())  # stored as a hash, never as is

        thief = APIClient()
        thief.cookies[REFRESH_COOKIE] = first
        with mock.patch("core.services.auth.tokens.REUSE_GRACE", timedelta(0)):
            self.assertEqual(thief.post("/api/auth/refresh").status_code, 401)
        self.assertEqual(AuthSession.objects.get().revoked_reason, "token_reuse")
        self.assertEqual(c.get("/api/accounts").status_code, 401)  # the real browser is signed out too

    def test_two_tabs_refreshing_at_once_are_not_treated_as_theft(self):
        c, r = self.login("admin@avaibe.com", PASSWORD)
        first = r.cookies[REFRESH_COOKIE].value
        c.post("/api/auth/refresh")
        other_tab = APIClient()
        other_tab.cookies[REFRESH_COOKIE] = first
        self.assertEqual(other_tab.post("/api/auth/refresh").status_code, 200)
        self.assertIsNone(AuthSession.objects.get().revoked_at)

    def test_sign_out_ends_the_session_at_once(self):
        c, _ = self.login("admin@avaibe.com", PASSWORD)
        token = c.cookies[ACCESS_COOKIE].value
        self.assertEqual(c.post("/api/auth/logout").status_code, 200)
        replay = APIClient()
        replay.cookies[ACCESS_COOKIE] = token  # a copy of the (still unexpired) access token
        self.assertEqual(replay.get("/api/accounts").status_code, 401)

    def test_turning_someone_off_ends_their_access_at_once(self):
        v = self.as_user(self.viewer)
        self.assertEqual(v.get("/api/accounts").status_code, 200)
        a = self.as_user(self.admin)
        body = {"email": self.viewer.email, "role": "viewer", "can_switch_accounts": False, "active": False}
        self.assertEqual(a.put(f"/api/team/{self.viewer.id}", body, format="json").status_code, 200)
        self.assertEqual(v.get("/api/accounts").status_code, 401)

    def test_forged_or_expired_access_tokens_are_refused(self):
        s = AuthSession.objects.create(user=self.admin, method="password", expires_at=now_utc() + timedelta(days=1))
        claims = {"sub": str(self.admin.id), "sid": str(s.id), "typ": "access", "iss": "avaibe", "iat": now_utc()}
        for token in (
            jwt.encode({**claims, "exp": now_utc() + timedelta(minutes=5)}, "someone-elses-key", algorithm="HS256"),
            jwt.encode({**claims, "exp": now_utc() - timedelta(minutes=1)}, jwt_signing_key(), algorithm="HS256"),
            "not-a-token",
        ):
            c = APIClient()
            c.cookies[ACCESS_COOKIE] = token
            self.assertEqual(c.get("/api/accounts").status_code, 401)

    def test_writes_need_the_csrf_header(self):
        c = APIClient(enforce_csrf_checks=True)
        self.assertEqual(c.post("/api/auth/login", {"email": "admin@avaibe.com", "password": PASSWORD}, format="json").status_code, 403)
        c.get("/api/auth/me")  # hands out the csrftoken cookie
        csrf = c.cookies["csrftoken"].value
        r = c.post("/api/auth/login", {"email": "admin@avaibe.com", "password": PASSWORD}, format="json", HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(r.status_code, 200)

    def test_change_password_signs_out_other_devices(self):
        laptop, _ = self.login("admin@avaibe.com", PASSWORD)
        phone, _ = self.login("admin@avaibe.com", PASSWORD)
        r = laptop.post("/api/auth/password", {"current": PASSWORD, "new": "short"}, format="json")
        self.assertEqual(r.status_code, 400)  # too short / too weak
        r = laptop.post("/api/auth/password", {"current": PASSWORD, "new": "river-copper-77-orbit"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(laptop.get("/api/accounts").status_code, 200)
        self.assertEqual(phone.get("/api/accounts").status_code, 401)


class InvitationTests(AuthTestCase):
    def test_invite_then_sign_up(self):
        link = self.as_user(self.admin).post("/api/team", {"email": "Sara@avaibe.com", "role": "editor"}, format="json").json()
        token = link["token"]
        self.assertFalse(Invitation.objects.filter(token_hash=token).exists())  # only the hash is stored

        c = APIClient()
        info = c.get(f"/api/auth/invitation?token={token}").json()
        self.assertEqual(info, {"email": "sara@avaibe.com", "role": "editor", "company": "AVAIBE"})
        weak = c.post("/api/auth/signup", {"token": token, "name": "Sara", "password": "12345678"}, format="json")
        self.assertEqual(weak.status_code, 400)
        r = c.post("/api/auth/signup", {"token": token, "name": "Sara", "password": PASSWORD}, format="json")
        self.assertEqual(r.status_code, 201)
        u = User.objects.get(email="sara@avaibe.com")
        self.assertEqual((u.role, u.company_id, u.created_by_id), ("editor", self.company.id, self.admin.id))
        self.assertEqual(c.get("/api/auth/me").json()["user"]["email"], "sara@avaibe.com")  # signed in straight away
        again = APIClient().post("/api/auth/signup", {"token": token, "name": "X", "password": PASSWORD}, format="json")
        self.assertEqual(again.status_code, 410)  # one use only

    def test_a_new_link_replaces_the_old_one_and_expired_links_fail(self):
        a = self.as_user(self.admin)
        first = a.post("/api/team", {"email": "sam@avaibe.com", "role": "viewer"}, format="json").json()
        second = a.post(f"/api/team/invitations/{first['id']}/renew").json()
        c = APIClient()
        self.assertEqual(c.get(f"/api/auth/invitation?token={first['token']}").status_code, 404)
        self.assertEqual(c.get(f"/api/auth/invitation?token={second['token']}").status_code, 200)
        Invitation.objects.update(expires_at=now_utc() - timedelta(minutes=1))
        self.assertEqual(c.get(f"/api/auth/invitation?token={second['token']}").status_code, 410)


class CompanyTests(AuthTestCase):
    def test_super_admin_creates_a_company_and_invites_its_admin(self):
        s = self.as_user(self.superadmin)
        r = s.post("/api/companies", {"name": "Gulf Schools Group", "country": "AE", "industry": "Education"}, format="json")
        self.assertEqual(r.status_code, 201)
        co = r.json()
        self.assertEqual((co["slug"], co["created_by"]), ("gulf-schools-group", "super@avaibe.com"))
        self.assertEqual(s.post("/api/companies", {"name": "gulf schools group"}, format="json").status_code, 409)

        inv = s.post(f"/api/team?company_id={co['id']}", {"email": "head@gsg.example", "role": "admin"}, format="json")
        self.assertEqual(inv.status_code, 201)
        c = APIClient()
        c.post("/api/auth/signup", {"token": inv.json()["token"], "name": "Head", "password": PASSWORD}, format="json")
        self.assertEqual(c.get("/api/accounts").json(), [])  # sees none of AVAIBE's accounts
        self.assertEqual(c.get(f"/api/accounts/{self.acc.id}/page-daily").status_code, 404)
        self.assertEqual(c.put(f"/api/team/{self.viewer.id}", {"email": "viewer@avaibe.com", "role": "editor"}, format="json").status_code, 404)
        self.assertEqual({m["email"] for m in c.get("/api/team").json()["members"]}, {"head@gsg.example"})

        # pausing the company signs its people out at once
        self.assertEqual(s.put(f"/api/companies/{co['id']}", {"is_active": False}, format="json").status_code, 200)
        self.assertEqual(c.get("/api/accounts").status_code, 401)

    def test_new_accounts_belong_to_the_admins_company(self):
        r = self.as_user(self.admin).post("/api/accounts", {"name": "Founder", "kind": "founder"}, format="json")
        self.assertEqual(r.json()["company_id"], self.company.id)


class SetupDetailTests(AuthTestCase):
    """Setting names and platform-wide usage are for owners; everyone else gets a plain message."""

    def test_ai_not_configured_message_depends_on_role(self):
        body = {"account_id": self.acc.id, "format": "text", "caption": "Hi"}
        with mock.patch("core.integrations.claude.configured", return_value=False):
            admin = self.as_user(self.admin).post("/api/ai/post-assist", body, format="json").json()["detail"]
            owner = self.as_user(self.superadmin).post("/api/ai/post-assist", body, format="json").json()["detail"]
        self.assertNotIn("ANTHROPIC_API_KEY", admin)
        self.assertIn("Contact the platform owner", admin)
        self.assertIn("ANTHROPIC_API_KEY", owner)

    def test_claude_status_hides_key_hint_and_usage_from_admins(self):
        with mock.patch("core.api.views.settings.ANTHROPIC_API_KEY", "sk-test-abcdefgh"):
            admin = self.as_user(self.admin).get("/api/settings/claude").json()
            owner = self.as_user(self.superadmin).get("/api/settings/claude").json()
        self.assertIsNone(admin["key_hint"])
        self.assertIsNone(admin["usage"])
        self.assertIn("daily_limit_per_account", admin)
        self.assertEqual(owner["key_hint"], "…efgh")
        self.assertIsNotNone(owner["usage"])

    def test_linkedin_config_lists_missing_settings_to_owners_only(self):
        with mock.patch("core.api.views.linkedin.LINKEDIN_CLIENT_ID", ""):
            admin = self.as_user(self.admin).get("/api/linkedin/config").json()
            owner = self.as_user(self.superadmin).get("/api/linkedin/config").json()
        self.assertFalse(admin["configured"])
        self.assertEqual(admin["missing"], [])
        self.assertIn("LINKEDIN_CLIENT_ID", owner["missing"])

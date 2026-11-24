"""Roles, account access, read-only demo mode."""

from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Account


class RolesAndSecurityTests(TestCase):
    """Who may manage whom, and that the rules hold on the server (not just in the screens)."""

    def setUp(self):
        from core.models import User

        self.acc = Account.objects.create(name="AVAIBE", kind="company")
        self.superadmin = User.objects.create_user("super@avaibe.com", role="superadmin", can_switch_accounts=True)
        self.admin = User.objects.create_user("admin@avaibe.com", role="admin")
        self.editor = User.objects.create_user("editor@avaibe.com", role="editor")
        self.viewer = User.objects.create_user("viewer@avaibe.com", role="viewer")

    def as_user(self, user):
        c = APIClient()
        c.force_login(user)
        return c

    def member(self, u, **kw):
        return {"email": u.email, "role": u.role, "can_switch_accounts": False, "active": True, **kw}

    def test_admins_manage_viewers_and_editors_only(self):
        with mock.patch("core.auth.authentication.auth_enabled", return_value=True):
            c = self.as_user(self.admin)
            self.assertEqual(c.put(f"/api/team/{self.viewer.id}", self.member(self.viewer, role="editor"), format="json").status_code, 200)
            # can't promote to admin, can't touch a super admin, can't invite an admin
            self.assertEqual(c.put(f"/api/team/{self.editor.id}", self.member(self.editor, role="admin"), format="json").status_code, 403)
            self.assertEqual(c.put(f"/api/team/{self.superadmin.id}", self.member(self.superadmin, role="viewer"), format="json").status_code, 403)
            self.assertEqual(c.post("/api/team", {"email": "new@avaibe.com", "role": "admin"}, format="json").status_code, 403)
            self.assertEqual(c.post("/api/team", {"email": "new@avaibe.com", "role": "editor"}, format="json").status_code, 201)

    def test_nobody_changes_their_own_role_and_one_super_admin_always_remains(self):
        with mock.patch("core.auth.authentication.auth_enabled", return_value=True):
            c = self.as_user(self.superadmin)
            self.assertEqual(c.put(f"/api/team/{self.superadmin.id}", self.member(self.superadmin, role="viewer"), format="json").status_code, 400)
            self.assertEqual(c.delete(f"/api/team/{self.superadmin.id}").status_code, 400)
            # a super admin can promote an admin; then the first can step down via the other
            self.assertEqual(c.put(f"/api/team/{self.admin.id}", self.member(self.admin, role="superadmin"), format="json").status_code, 200)
            c2 = self.as_user(self.admin)
            self.assertEqual(c2.put(f"/api/team/{self.superadmin.id}", self.member(self.superadmin, role="admin"), format="json").status_code, 200)
            # now only one super admin is left: they can't be demoted
            c3 = self.as_user(self.superadmin)  # now an admin
            self.assertEqual(c3.put(f"/api/team/{self.admin.id}", self.member(self.admin, role="admin"), format="json").status_code, 403)

    def test_lower_roles_are_refused_on_the_server(self):
        with mock.patch("core.auth.authentication.auth_enabled", return_value=True):
            v = self.as_user(self.viewer)
            self.assertEqual(v.get("/api/accounts").status_code, 200)  # viewers can read
            self.assertEqual(v.post("/api/planner", {"account_id": self.acc.id, "caption": "x", "goal": "brand"}, format="json").status_code, 403)
            self.assertEqual(v.get("/api/team").status_code, 403)
            e = self.as_user(self.editor)
            self.assertEqual(e.put("/api/settings/brand", {}, format="json").status_code, 403)
            self.assertEqual(APIClient().get("/api/accounts").status_code, 401)  # nobody signed in

    def test_database_screens_are_super_admin_only(self):
        self.assertFalse(self.admin.is_staff)
        self.assertTrue(self.superadmin.is_staff)
        c = APIClient()
        c.force_login(self.admin)
        self.assertNotEqual(c.get("/admin/core/user/").status_code, 200)

    def test_open_demo_is_read_only(self):
        with mock.patch("core.auth.authentication.auth_enabled", return_value=False), mock.patch.dict("os.environ", {"READ_ONLY_WITHOUT_SIGNIN": "true"}):
            c = APIClient()
            self.assertEqual(c.get("/api/accounts").status_code, 200)
            r = c.post("/api/planner", {"account_id": self.acc.id, "caption": "x", "goal": "brand"}, format="json")
            self.assertEqual(r.status_code, 403)
            self.assertIn("read-only", r.content.decode())

"""Who is using the app, and what they may do.

- Sign-in: Microsoft Entra ID (single tenant) via MSAL; Django's session framework holds the login
  (httpOnly cookie, server-side session row).
- Invite-only: a Microsoft account can sign in only if an admin added that email on the Team page
  (or it is listed in ADMIN_EMAILS, which bootstraps the first admins).
- Roles: viewer < editor < admin < superadmin. Editors write, schedule and publish. Admins manage viewers and editors;
  only super admins manage admins and super admins. Nobody changes their own role.
- Account access: people without "can switch accounts" (and not admins) only see the default account.
  Enforced on every API call, not just hidden in the UI.
- Local mode: until Microsoft sign-in is configured, every request acts as a super admin so the app stays
  usable on a laptop. The UI shows that sign-in is off. With READ_ONLY_WITHOUT_SIGNIN=true (the hosted demo),
  local mode can only read: every change is refused, so nobody can alter data on an open server.
"""


from rest_framework.exceptions import NotFound, PermissionDenied

from core.auth.authentication import CurrentUser
from core.models import ROLE_LABELS, Account
from core.services import settings_store


def require(user: CurrentUser, role: str) -> None:
    if not user.at_least(role):
        raise PermissionDenied(f"This needs the {ROLE_LABELS[role]} role or higher")


# ------------------------------------------------------------------ account access


def default_account_id() -> int | None:
    configured = settings_store.get("access").get("default_account_id")
    if configured and Account.objects.filter(id=configured).exists():
        return configured
    first_company = Account.objects.filter(kind="company").order_by("id").values_list("id", flat=True).first()
    return first_company or Account.objects.order_by("id").values_list("id", flat=True).first()


def allowed_account_ids(user: CurrentUser) -> list[int]:
    if user._accounts is None:
        if user.switcher:
            user._accounts = list(Account.objects.order_by("id").values_list("id", flat=True))
        else:
            d = default_account_id()
            user._accounts = [d] if d else []
    return user._accounts


def check_account(user: CurrentUser, account_id: int) -> None:
    if account_id not in allowed_account_ids(user):
        # 404 rather than 403, so people can't probe which accounts exist
        raise NotFound("Account not found")

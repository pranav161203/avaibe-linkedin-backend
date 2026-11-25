"""Who is using the app, and what they may do.

- Sign-in: email + password or Microsoft Entra ID; both give the same access and refresh tokens (docs/auth.md).
- Invite-only: people join through an invitation (Team page, or Companies for a company's first admin).
  ADMIN_EMAILS bootstraps the first super admins through Microsoft sign-in.
- Companies: everyone except a super admin belongs to one company and only ever sees that company's accounts,
  posts and knowledge. Super admins work across companies.
- Roles: viewer < editor < admin < superadmin. Editors write, schedule and publish. Admins manage viewers and editors
  of their own company; only super admins manage admins and super admins. Nobody changes their own role.
- Account access: people without "can switch accounts" (and not admins) only see their company's default account.
  Enforced on every API call, not just hidden in the UI.
- Local mode: until Microsoft sign-in is configured, every request acts as a super admin so the app stays
  usable on a laptop. The UI shows that sign-in is off. With READ_ONLY_WITHOUT_SIGNIN=true (the hosted demo),
  local mode can only read: every change is refused, so nobody can alter data on an open server.
"""


from rest_framework.exceptions import NotFound, PermissionDenied

from core.auth.authentication import CurrentUser
from core.models import ROLE_LABELS, Account, Company
from core.services import settings_store


def require(user: CurrentUser, role: str) -> None:
    if not user.at_least(role):
        raise PermissionDenied(f"Requires the {ROLE_LABELS[role]} role or higher")


# ------------------------------------------------------------------ account access


def default_account_id(user: CurrentUser) -> int | None:
    """The account people without the switcher are limited to: their company's chosen default, else its first
    company page, else its first account. Super admins: their first visible account."""
    if user.company_id is None and not user.is_superadmin:
        return None
    qs = Account.objects.all() if user.company_id is None else Account.objects.filter(company_id=user.company_id)
    if user.company_id is not None:
        chosen = Company.objects.filter(id=user.company_id).values_list("default_account_id", flat=True).first()
        if chosen and qs.filter(id=chosen).exists():
            return chosen
    first_company = qs.filter(kind="company").order_by("id").values_list("id", flat=True).first()
    return first_company or qs.order_by("id").values_list("id", flat=True).first()


def company_account_ids(user: CurrentUser) -> list[int]:
    """Every account of the person's company (super admins: every account)."""
    qs = Account.objects.order_by("id")
    if not user.is_superadmin:
        qs = qs.filter(company_id=user.company_id) if user.company_id else qs.none()
    return list(qs.values_list("id", flat=True))


def allowed_account_ids(user: CurrentUser) -> list[int]:
    if user._accounts is None:
        if user.switcher:
            user._accounts = company_account_ids(user)
        else:
            d = default_account_id(user)
            user._accounts = [d] if d else []
    return user._accounts


def check_account(user: CurrentUser, account_id: int) -> None:
    """The person may see this account. Also makes the account's company the one whose Settings apply for the
    rest of the request (an owner can look at any company's account)."""
    if account_id not in allowed_account_ids(user):
        # 404 rather than 403, so people can't probe which accounts exist
        raise NotFound("Account not found")
    company_id = user.company_id if user.company_id else Account.objects.filter(id=account_id).values_list("company_id", flat=True).first()
    settings_store.use_company(company_id)


def is_owner(user) -> bool:
    """Owner (role superadmin). Safe on anonymous users, e.g. an OAuth callback without a session."""
    return bool(getattr(user, "is_superadmin", False))


def for_viewer(user, message: str, owner_detail: str | None = None) -> str:
    """Setup details (setting names, server files) are for owners only; everyone else gets the plain message."""
    return owner_detail if owner_detail and is_owner(user) else message


def require_superadmin(user: CurrentUser) -> None:
    if not user.is_superadmin:
        raise PermissionDenied("Requires the Owner role")

"""Who is making the request: the access-token cookie, or local mode. Plugged into DRF in settings.

Each API call: read the avaibe_access cookie, check the JWT signature and expiry, then load its session, user and
company from the database (one query). A revoked session, a turned-off user or a paused company is refused at once,
even if the token itself hasn't expired. Writes also need the CSRF header (the cookie is sent automatically by the
browser, so this blocks forged cross-site requests).
"""

from dataclasses import dataclass, field

from rest_framework.authentication import BaseAuthentication, CSRFCheck
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from core.auth.cookies import ACCESS_COOKIE
from core.conf import auth_enabled, read_only_without_signin
from core.models import ROLES
from core.services import settings_store
from core.services.auth import AuthError, tokens


@dataclass
class CurrentUser:
    id: int | None
    email: str
    name: str | None
    role: str
    can_switch_accounts: bool
    company_id: int | None = None
    company_name: str | None = None
    session_id: str | None = None
    dev: bool = False  # True in local mode (sign-in off)
    _accounts: list[int] | None = field(default=None, repr=False)

    is_authenticated = True  # for DRF

    def at_least(self, role: str) -> bool:
        return ROLES.index(self.role) >= ROLES.index(role)

    @property
    def is_superadmin(self) -> bool:
        return self.role == "superadmin"

    @property
    def switcher(self) -> bool:
        return self.at_least("admin") or self.can_switch_accounts

    @classmethod
    def from_user(cls, u, session_id: str | None = None) -> "CurrentUser":
        return cls(
            id=u.id,
            email=u.email,
            name=u.name,
            role=u.role,
            can_switch_accounts=u.can_switch_accounts,
            company_id=u.company_id,
            company_name=u.company.name if u.company_id else None,
            session_id=session_id,
        )


def dev_user() -> CurrentUser:
    # A fresh object per request: the allowed-accounts cache must not outlive the request
    return CurrentUser(id=None, email="local-dev", name="Local dev (sign-in off)", role="superadmin", can_switch_accounts=True, dev=True)


def user_from_token(token: str | None) -> CurrentUser | None:
    if not token:
        return None
    try:
        user_id, sid = tokens.read_access(token)
    except AuthError:
        return None
    session = tokens.active_session(user_id, sid)
    return CurrentUser.from_user(session.user, str(session.id)) if session else None


def current_from_request(request) -> CurrentUser | None:
    """For plain Django views (not DRF)."""
    if not auth_enabled():
        return dev_user()
    return user_from_token(request.COOKIES.get(ACCESS_COOKIE))


def enforce_csrf(request) -> None:
    """The same check Django's middleware does, for DRF views (DRF turns the middleware off for its views)."""
    check = CSRFCheck(lambda req: None)
    check.process_request(request)
    reason = check.process_view(request, None, (), {})
    if reason:
        raise PermissionDenied(f"CSRF failed: {reason}")


class AppAuthentication(BaseAuthentication):
    """DRF authentication: local mode acts as super admin; otherwise the access-token cookie, with CSRF enforced."""

    def authenticate(self, request):
        if not auth_enabled():
            return (dev_user(), None)
        user = user_from_token(request.COOKIES.get(ACCESS_COOKIE))
        if user is None:
            return None  # 401: the app then tries /api/auth/refresh once
        enforce_csrf(request._request)
        settings_store.use_company(user.company_id)  # owners: set per account by check_account
        return (user, None)

    def authenticate_header(self, request):
        return "Cookie"  # makes DRF answer 401 (not 403) when nobody is signed in


SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


class IsSignedIn(BasePermission):
    message = "Please sign in"

    def has_permission(self, request, view) -> bool:
        if not isinstance(request.user, CurrentUser):
            return False
        # An open (no sign-in) hosted server is read-only: no changes without a signed-in person
        if request.user.dev and read_only_without_signin() and request.method not in SAFE_METHODS:
            self.message = "This demo is read-only: sign-in is off, so changes aren't allowed"
            return False
        return True

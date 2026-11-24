"""Who is making the request: Django session (Microsoft sign-in) or local mode. Plugged into DRF in settings."""

from dataclasses import dataclass, field

from rest_framework.authentication import BaseAuthentication, SessionAuthentication
from rest_framework.permissions import BasePermission

from core.conf import auth_enabled, read_only_without_signin
from core.models import ROLES


@dataclass
class CurrentUser:
    id: int | None
    email: str
    name: str | None
    role: str
    can_switch_accounts: bool
    dev: bool = False  # True in local mode (sign-in not configured)
    _accounts: list[int] | None = field(default=None, repr=False)

    is_authenticated = True  # for DRF

    def at_least(self, role: str) -> bool:
        return ROLES.index(self.role) >= ROLES.index(role)

    @property
    def switcher(self) -> bool:
        return self.at_least("admin") or self.can_switch_accounts

    @classmethod
    def from_user(cls, u) -> "CurrentUser":
        return cls(id=u.id, email=u.email, name=u.name, role=u.role, can_switch_accounts=u.can_switch_accounts)

def dev_user() -> CurrentUser:
    # A fresh object per request: the allowed-accounts cache must not outlive the request
    return CurrentUser(id=None, email="local-dev", name="Local dev (sign-in off)", role="superadmin", can_switch_accounts=True, dev=True)

def current_from_request(request) -> CurrentUser | None:
    """For plain Django views (not DRF)."""
    if not auth_enabled():
        return dev_user()
    u = getattr(request, "user", None)
    if u is None or not u.is_authenticated or not u.is_active:
        return None
    return CurrentUser.from_user(u)

class AppAuthentication(BaseAuthentication):
    """DRF authentication: local mode acts as admin; otherwise the Django session user, with CSRF enforced."""

    def authenticate(self, request):
        if not auth_enabled():
            return (dev_user(), None)
        u = getattr(request._request, "user", None)
        if u is None or not u.is_authenticated or not u.is_active:
            return None
        SessionAuthentication().enforce_csrf(request)  # blocks forged cross-site requests
        return (CurrentUser.from_user(u), None)

    def authenticate_header(self, request):
        return "Session"  # makes DRF answer 401 (not 403) when nobody is signed in

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

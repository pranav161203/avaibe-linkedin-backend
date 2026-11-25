"""The two sign-in cookies. Both are httpOnly (page scripts can't read them) and SameSite=Lax.

- avaibe_access: the access token, sent with every API call, lives ACCESS_TOKEN_MINUTES.
- avaibe_refresh: the refresh token, sent only to /api/auth/ (refresh and sign-out), lives until the session ends.
"""

from django.conf import settings

from core.common.timeutil import now_utc
from core.services.auth.tokens import Issued

ACCESS_COOKIE = "avaibe_access"
REFRESH_COOKIE = "avaibe_refresh"
REFRESH_PATH = "/api/auth/"


def _opts() -> dict:
    return {"httponly": True, "samesite": "Lax", "secure": settings.COOKIE_SECURE}


def set_tokens(response, issued: Issued) -> None:
    now = now_utc()
    response.set_cookie(ACCESS_COOKIE, issued.access, max_age=int((issued.access_expires - now).total_seconds()), path="/", **_opts())
    if issued.refresh:
        age = max(0, int((issued.refresh_expires - now).total_seconds()))
        response.set_cookie(REFRESH_COOKIE, issued.refresh, max_age=age, path=REFRESH_PATH, **_opts())


def clear_tokens(response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/", samesite="Lax")
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH, samesite="Lax")

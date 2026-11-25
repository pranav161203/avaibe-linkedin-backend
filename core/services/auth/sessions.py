"""A person's signed-in devices: list them and sign one (or all others) out. Each device is one auth_sessions row."""

import re

from django.core.exceptions import ValidationError

from core.common.timeutil import as_utc, now_utc
from core.models import AuthSession
from core.services.auth import AuthError, tokens

_BROWSERS = [  # order matters: Edge and Opera also say "Chrome", Chrome also says "Safari"
    ("Edge", r"Edg(e|A|iOS)?/"),
    ("Opera", r"OPR/|Opera"),
    ("Samsung Internet", r"SamsungBrowser/"),
    ("Firefox", r"Firefox/|FxiOS/"),
    ("Chrome", r"Chrome/|CriOS/"),
    ("Safari", r"Safari/"),
]
_SYSTEMS = [  # iPad and iPhone also say "Mac OS X"; Android also says "Linux"
    ("iPhone", r"iPhone"),
    ("iPad", r"iPad"),
    ("Android", r"Android"),
    ("Windows", r"Windows"),
    ("macOS", r"Mac OS X|Macintosh"),
    ("ChromeOS", r"CrOS"),
    ("Linux", r"Linux"),
]


def describe_device(user_agent: str) -> str:
    """'Chrome on Windows' from a browser's user agent; 'Unknown device' when it can't be read."""
    browser = next((name for name, pat in _BROWSERS if re.search(pat, user_agent or "")), None)
    system = next((name for name, pat in _SYSTEMS if re.search(pat, user_agent or "")), None)
    if browser and system:
        return f"{browser} on {system}"
    return browser or system or "Unknown device"


def active(user_id: int) -> list[AuthSession]:
    """The person's sessions that still work, most recently used first."""
    now = now_utc()
    return [
        s
        for s in AuthSession.objects.filter(user_id=user_id, revoked_at__isnull=True).order_by("-last_used_at")
        if as_utc(s.expires_at) > now
    ]


def sign_out_device(user_id: int, session_id: str) -> None:
    """End one of the person's own sessions. Another person's session is treated as not found."""
    try:
        exists = AuthSession.objects.filter(id=session_id, user_id=user_id, revoked_at__isnull=True).exists()
    except (ValueError, ValidationError):  # not a UUID
        exists = False
    if not exists:
        raise AuthError("not_found", "Session not found", status=404)
    tokens.revoke_session(session_id, "signed_out_remotely")


def sign_out_others(user_id: int, current_session_id: str | None) -> int:
    """End every session except the one making the request. Returns how many ended."""
    return tokens.revoke_user_sessions(user_id, "signed_out_remotely", keep=current_session_id)

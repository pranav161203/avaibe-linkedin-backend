"""Application configuration read from the environment (server/.env is loaded by config/settings.py)."""

import os
from pathlib import Path

from django.conf import settings

BASE_DIR: Path = settings.BASE_DIR

# ---- LinkedIn app ("Share on LinkedIn" + "Sign In with LinkedIn using OpenID Connect")
LINKEDIN_CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "")
LINKEDIN_CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "")
# Must match a redirect URL registered on the LinkedIn app's Auth tab exactly
LINKEDIN_REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI", "http://localhost:8000/api/linkedin/callback")
# LinkedIn versioned REST API (YYYYMM). Versions are retired after about a year; bump if LinkedIn rejects it.
LINKEDIN_API_VERSION = os.getenv("LINKEDIN_API_VERSION", "202610")
LINKEDIN_SCOPES = "openid profile email w_member_social"

# Where the browser is sent after sign-in flows
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

# Fernet key used to encrypt stored LinkedIn tokens
TOKEN_ENCRYPTION_KEY = os.getenv("TOKEN_ENCRYPTION_KEY", "")

UPLOAD_DIR = BASE_DIR / "uploads"

# Scheduled posts more than this many minutes late are marked "missed" instead of being
# published at the wrong time (which would also distort the posting-time analysis).
PUBLISH_GRACE_MINUTES = int(os.getenv("PUBLISH_GRACE_MINUTES", "15"))

# ---- Microsoft sign-in (Entra ID). Until all three are set, the app runs in local mode without sign-in.
MS_TENANT_ID = os.getenv("MS_TENANT_ID", "")
MS_CLIENT_ID = os.getenv("MS_CLIENT_ID", "")
MS_CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET", "")
# Must match a redirect URI on the Entra app registration. In dev it goes through the Vite proxy.
MS_REDIRECT_URI = os.getenv("MS_REDIRECT_URI", "http://localhost:5173/api/auth/callback")
# People who become Admin the first time they sign in (bootstraps the Team list). Comma-separated.
ADMIN_EMAILS = {e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()}

# ---- Claude (Anthropic API) for AI suggestions. The key stays server-side only.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")


def linkedin_configured() -> bool:
    return bool(LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET and TOKEN_ENCRYPTION_KEY)


def read_only_without_signin() -> bool:
    """Hosted demo with sign-in off: refuse every change (read live so tests can switch it)."""
    return os.getenv("READ_ONLY_WITHOUT_SIGNIN", "").strip().lower() in ("1", "true", "yes")


def email_configured() -> bool:
    """Invitation emails are sent when a mail server and a sender address are set (see config/settings/base.py)."""
    from django.conf import settings

    return bool(settings.EMAIL_HOST and settings.DEFAULT_FROM_EMAIL)


def microsoft_configured() -> bool:
    # Read live so tests can switch it per run
    return bool(os.getenv("MS_TENANT_ID") and os.getenv("MS_CLIENT_ID") and os.getenv("MS_CLIENT_SECRET"))


def auth_enabled() -> bool:
    """Sign-in is on when AUTH_ENABLED=true or Microsoft sign-in is configured. Off = local mode (no sign-in)."""
    flag = os.getenv("AUTH_ENABLED", "").strip().lower() in ("1", "true", "yes")
    return flag or microsoft_configured()


# ---- Sign-in tokens (see docs/auth.md)
# Access token: a signed JWT that proves who is asking. Short-lived, never stored.
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "15"))
# Refresh token: renews the access token; rotated on every use. A session ends after this many days at most.
REFRESH_TOKEN_DAYS = int(os.getenv("REFRESH_TOKEN_DAYS", "7"))
INVITATION_DAYS = int(os.getenv("INVITATION_DAYS", "7"))
# Password reset links: minutes until they expire, and how many one person can request per hour
PASSWORD_RESET_MINUTES = int(os.getenv("PASSWORD_RESET_MINUTES", "60"))
PASSWORD_RESET_PER_HOUR = int(os.getenv("PASSWORD_RESET_PER_HOUR", "3"))
# Password sign-in: after this many wrong passwords for one email in the window, wait until the window passes
LOGIN_MAX_FAILURES = int(os.getenv("LOGIN_MAX_FAILURES", "5"))
LOGIN_LOCK_MINUTES = int(os.getenv("LOGIN_LOCK_MINUTES", "15"))


def jwt_signing_key() -> str:
    """JWT_SIGNING_KEY if set; otherwise a key derived from DJANGO_SECRET_KEY (so it's never the secret itself).
    Changing it signs everyone out within ACCESS_TOKEN_MINUTES."""
    key = os.getenv("JWT_SIGNING_KEY", "")
    if key:
        return key
    import hashlib
    import hmac

    return hmac.new(settings.SECRET_KEY.encode(), b"avaibe-jwt-access-v1", hashlib.sha256).hexdigest()

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


def auth_enabled() -> bool:
    # Read live so tests can switch it per run
    return bool(os.getenv("MS_TENANT_ID") and os.getenv("MS_CLIENT_ID") and os.getenv("MS_CLIENT_SECRET"))

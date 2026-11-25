"""Forgotten passwords: email a single-use link, then set a new password from it.

- Asking for a link never reveals whether the email has an account: the reply is the same either way, and the
  email itself is sent in the background so the reply time doesn't give it away either.
- At most PASSWORD_RESET_PER_HOUR links per person per hour; a new link replaces the previous unused one.
- Setting the new password signs the person out everywhere, then signs this device in.
"""

import secrets
import threading
from datetime import timedelta

from django.db import transaction

from core.common.timeutil import as_utc, now_utc
from core.conf import FRONTEND_URL, PASSWORD_RESET_MINUTES, PASSWORD_RESET_PER_HOUR
from core.models import LoginAttempt, PasswordReset, User
from core.services.auth import AuthError, emails, tokens
from core.services.auth.passwords import set_password

INVALID = "This reset link is invalid or has expired. Request a new one."


def _in_background(fn) -> None:
    """Run the send after the reply. Tests replace this to send at once."""
    threading.Thread(target=fn, daemon=True).start()


def request(email: str) -> None:
    """Email a reset link if the address belongs to an active person. Silent in every other case."""
    tidy()
    email = (email or "").strip().lower()
    user = User.objects.select_related("company").filter(email__iexact=email, is_active=True).first()
    if user is None or (user.company_id and not user.company.is_active):
        return
    now = now_utc()
    if PasswordReset.objects.filter(user=user, created_at__gte=now - timedelta(hours=1)).count() >= PASSWORD_RESET_PER_HOUR:
        return
    # Only the newest link works. Expire (not delete) the older ones, so they still count towards the hourly limit
    PasswordReset.objects.filter(user=user, used_at__isnull=True, expires_at__gt=now).update(expires_at=now)
    raw = secrets.token_urlsafe(32)
    reset = PasswordReset.objects.create(user=user, token_hash=tokens.hash_token(raw), expires_at=now + timedelta(minutes=PASSWORD_RESET_MINUTES))
    link = f"{FRONTEND_URL}/reset-password?token={raw}"
    _in_background(lambda: emails.send_password_reset(user.email, link, reset.expires_at))


def _usable(reset: PasswordReset | None) -> PasswordReset:
    if reset is None or reset.used_at or as_utc(reset.expires_at) <= now_utc() or not reset.user.is_active:
        raise AuthError("invalid_reset", INVALID, status=410)
    return reset


def find(raw: str) -> PasswordReset:
    """The reset a link belongs to, if it can still be used."""
    return _usable(PasswordReset.objects.select_related("user").filter(token_hash=tokens.hash_token(raw or "")).first())


def confirm(raw: str, password: str, user_agent: str = "") -> tokens.Issued:
    """Set the new password, end every session, and sign this device in."""
    with transaction.atomic():
        reset = _usable(
            PasswordReset.objects.select_for_update(of=("self",)).select_related("user").filter(token_hash=tokens.hash_token(raw or "")).first()
        )
        user = reset.user
        set_password(user, password)  # raises AuthError when the password breaks the rules
        user.save(update_fields=["password", "updated_at"])
        reset.used_at = now_utc()
        reset.save(update_fields=["used_at"])
        PasswordReset.objects.filter(user=user, used_at__isnull=True).delete()
        LoginAttempt.objects.filter(email=user.email).delete()  # a locked-out person can sign in again
    tokens.revoke_user_sessions(user.id, "password_reset")
    return tokens.start_session(user, "password", user_agent)


def tidy() -> None:
    """Delete links that expired over a day ago."""
    PasswordReset.objects.filter(expires_at__lt=now_utc() - timedelta(days=1)).delete()

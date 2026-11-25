"""Sign-in state, kept apart from the users and companies tables.

- AuthSession: one signed-in device/browser. Revoking it signs that device out.
- RefreshToken: the long-lived token that renews the short-lived access token. Rotated on every use; only a
  SHA-256 hash is stored, so a database leak can't be replayed as a sign-in.
- Invitation: a one-time sign-up link for a person a super admin or admin invited (hash stored, not the link).
- LoginAttempt: failed password attempts, to slow down guessing.
- AuthFlow: an in-progress Microsoft sign-in (state, nonce, PKCE verifier), used once by the callback.

Access tokens are signed JWTs (core.services.auth.tokens) and are never stored: they expire after a few minutes,
and every request also checks that their session is still active.
"""

import uuid

from django.conf import settings
from django.db import models

from core.models.choices import ROLE_CHOICES


class AuthSession(models.Model):
    """One sign-in on one device. The access token carries its id (`sid`), so ending it takes effect at once."""

    METHODS = [("password", "Email and password"), ("microsoft", "Microsoft")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="auth_sessions")
    method = models.CharField(max_length=20, choices=METHODS)
    user_agent = models.CharField(max_length=300, blank=True, default="")  # to show "Chrome on Windows" in a list
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(auto_now_add=True)
    # Absolute end: after this the person signs in again, however active they were
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    # signed_out | signed_out_remotely | password_changed | token_reuse | user_disabled | removed
    revoked_reason = models.CharField(max_length=30, blank=True, default="")

    class Meta:
        db_table = "auth_sessions"
        indexes = [models.Index(fields=["user", "revoked_at"], name="auth_sess_user_active")]


class RefreshToken(models.Model):
    """A refresh token. Each use marks it used and issues the next one in the same session. A used token that
    comes back means it was copied, so the whole session is revoked (refresh-token reuse detection)."""

    session = models.ForeignKey(AuthSession, on_delete=models.CASCADE, related_name="refresh_tokens")
    token_hash = models.CharField(max_length=64, unique=True)  # SHA-256 hex of the random token
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "auth_refresh_tokens"


class Invitation(models.Model):
    """An invitation to join a company (or to be a super admin, with company empty) with a given role.
    Accepting it creates the user. The link holds a random token; only its hash is stored here."""

    email = models.EmailField(max_length=320)
    company = models.ForeignKey("core.Company", on_delete=models.CASCADE, null=True, blank=True, related_name="invitations")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    can_switch_accounts = models.BooleanField(default=False)
    token_hash = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_column="invited_by"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_column="accepted_user_id"
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    # Last time the link was sent by email (null: shared by hand, or email not configured)
    emailed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "auth_invitations"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["email"], name="auth_inv_email")]


class LoginAttempt(models.Model):
    """A failed password sign-in. Old rows are deleted as new ones are checked."""

    email = models.EmailField(max_length=320, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "auth_login_attempts"


class AuthFlow(models.Model):
    """In-progress Microsoft sign-in (state, nonce, PKCE verifier), consumed once by the callback."""

    state = models.CharField(max_length=128, primary_key=True)
    flow = models.JSONField()
    created_at = models.DateTimeField()

    class Meta:
        db_table = "auth_flows"

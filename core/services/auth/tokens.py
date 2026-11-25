"""Sessions, access tokens and refresh tokens.

Sign-in creates an AuthSession (one per device) and gives the browser two tokens:

- Access token: a JWT signed with HS256, valid ACCESS_TOKEN_MINUTES. Claims: sub (user id), sid (session id),
  typ, iat, exp, iss. It proves identity only: role, company and "is active" are read from the database on every
  request, so changing someone's role or disabling them works at once, not when the token expires.
- Refresh token: 48 random bytes, valid until the session ends. Only its SHA-256 hash is stored. Each use marks
  it used and returns a new one (rotation). If a used token is presented again after the grace period, someone
  has a copy, so the whole session is revoked.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt
from django.core.exceptions import ValidationError
from django.db import transaction

from core.common.timeutil import as_utc, now_utc
from core.conf import ACCESS_TOKEN_MINUTES, REFRESH_TOKEN_DAYS, jwt_signing_key
from core.models import AuthSession, RefreshToken, User
from core.services.auth import AuthError

ALGORITHM = "HS256"
ISSUER = "avaibe"
# Two tabs can refresh at the same moment with the same token. A second use this soon after the first is that race,
# not theft: it gets a new access token, and the browser already holds the new refresh token from the first reply.
REUSE_GRACE = timedelta(seconds=30)


@dataclass
class Issued:
    access: str
    access_expires: datetime
    refresh: str | None  # None when only the access token was renewed (the race case above)
    refresh_expires: datetime
    session: AuthSession


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _new_refresh(session: AuthSession) -> str:
    raw = secrets.token_urlsafe(48)
    RefreshToken.objects.create(session=session, token_hash=hash_token(raw), expires_at=session.expires_at)
    return raw


def _access(session: AuthSession) -> tuple[str, datetime]:
    now = now_utc()
    exp = now + timedelta(minutes=ACCESS_TOKEN_MINUTES)
    claims = {"sub": str(session.user_id), "sid": str(session.id), "typ": "access", "iss": ISSUER, "iat": now, "exp": exp}
    return jwt.encode(claims, jwt_signing_key(), algorithm=ALGORITHM), exp


def start_session(user: User, method: str, user_agent: str = "") -> Issued:
    """A new sign-in: a session plus its first access and refresh tokens."""
    tidy()
    session = AuthSession.objects.create(
        user=user, method=method, user_agent=user_agent[:300], expires_at=now_utc() + timedelta(days=REFRESH_TOKEN_DAYS)
    )
    access, access_exp = _access(session)
    user.last_login = now_utc()
    user.save(update_fields=["last_login"])
    return Issued(access, access_exp, _new_refresh(session), session.expires_at, session)


def read_access(token: str) -> tuple[int, str]:
    """(user id, session id) from a valid access token. Raises AuthError("invalid_token") otherwise:
    bad signature, expired, wrong type or issuer, missing claims."""
    try:
        claims = jwt.decode(
            token, jwt_signing_key(), algorithms=[ALGORITHM], issuer=ISSUER, options={"require": ["sub", "sid", "exp", "iat"]}
        )
    except jwt.PyJWTError as e:
        raise AuthError("invalid_token", "Your session has expired", status=401) from e
    if claims.get("typ") != "access":
        raise AuthError("invalid_token", "Your session has expired", status=401)
    try:
        return int(claims["sub"]), str(claims["sid"])
    except (TypeError, ValueError) as e:
        raise AuthError("invalid_token", "Your session has expired", status=401) from e


def active_session(user_id: int, session_id: str) -> AuthSession | None:
    """The session if it is still usable (not revoked or expired, user and company active), with user and company."""
    try:
        s = AuthSession.objects.select_related("user", "user__company").get(id=session_id, user_id=user_id)
    except (AuthSession.DoesNotExist, ValueError, ValidationError):  # the last two: sid isn't a UUID
        return None
    if s.revoked_at or as_utc(s.expires_at) <= now_utc():
        return None
    u = s.user
    if not u.is_active or (u.company_id and not u.company.is_active):
        return None
    return s


def refresh(raw: str) -> Issued:
    """Swap a refresh token for a new access token and a new refresh token."""
    if not raw:
        raise AuthError("no_session", "Sign-in required", status=401)
    reused = None
    with transaction.atomic():
        row = (
            RefreshToken.objects.select_for_update()
            .select_related("session", "session__user", "session__user__company")
            .filter(token_hash=hash_token(raw))
            .first()
        )
        if row is None:
            raise AuthError("no_session", "Sign-in required", status=401)
        session, now = row.session, now_utc()
        if row.used_at:
            if now - as_utc(row.used_at) <= REUSE_GRACE and not session.revoked_at:
                access, access_exp = _access(session)
                return Issued(access, access_exp, None, session.expires_at, session)
            reused = session
        elif active_session(session.user_id, str(session.id)) is None:
            raise AuthError("no_session", "Sign-in required", status=401)
        else:
            row.used_at = now
            row.save(update_fields=["used_at"])
            AuthSession.objects.filter(id=session.id).update(last_used_at=now)
            access, access_exp = _access(session)
            return Issued(access, access_exp, _new_refresh(session), session.expires_at, session)
    # Outside the transaction, so the revocation is kept although we then raise
    revoke_session(reused, "token_reuse")
    raise AuthError("token_reuse", "For your security, you have been signed out. Sign in again.", status=401)


def revoke_session(session: AuthSession | str, reason: str) -> None:
    sid = session.id if isinstance(session, AuthSession) else session
    AuthSession.objects.filter(id=sid, revoked_at__isnull=True).update(revoked_at=now_utc(), revoked_reason=reason)


def revoke_user_sessions(user_id: int, reason: str, keep: str | None = None) -> int:
    """Sign a person out everywhere (except the session `keep`). Returns how many sessions ended."""
    qs = AuthSession.objects.filter(user_id=user_id, revoked_at__isnull=True)
    if keep:
        qs = qs.exclude(id=keep)
    return qs.update(revoked_at=now_utc(), revoked_reason=reason)


def revoke_by_refresh(raw: str, reason: str = "signed_out") -> None:
    """Sign-out when only the refresh token is known (the access token may have expired)."""
    row = RefreshToken.objects.filter(token_hash=hash_token(raw)).only("session_id").first() if raw else None
    if row:
        revoke_session(str(row.session_id), reason)


def tidy() -> None:
    """Delete sessions that ended over 30 days ago (their refresh tokens go with them)."""
    cutoff = now_utc() - timedelta(days=30)
    AuthSession.objects.filter(expires_at__lt=cutoff).delete()
    AuthSession.objects.filter(revoked_at__lt=cutoff).delete()

"""Invite-only sign-up.

A super admin invites a company's first admin; admins invite their own team. The invitation link carries a random
token (shown once, to the person who invited); only its SHA-256 hash is stored. Opening the link lets the invited
person choose a name and password, which creates their user. Signing in with Microsoft with the invited email
accepts it too. A new invitation for the same email replaces any earlier pending one.
"""

import secrets
from datetime import timedelta

from django.db import IntegrityError, transaction

from core.common.timeutil import as_utc, now_utc
from core.conf import INVITATION_DAYS
from core.models import Company, Invitation, User
from core.services.auth import AuthError
from core.services.auth.passwords import set_password
from core.services.auth.tokens import hash_token


def pending(company_id: int | None):
    """Open invitations for a company (company_id None: super admin invitations), newest first."""
    return Invitation.objects.filter(
        company_id=company_id, accepted_at__isnull=True, revoked_at__isnull=True, expires_at__gt=now_utc()
    ).select_related("invited_by")


def create(email: str, company: Company | None, role: str, can_switch_accounts: bool, invited_by: int | None) -> tuple[Invitation, str]:
    """A new invitation and its one-time token (put it in the link; it can't be read back later)."""
    email = email.strip().lower()
    if (company is None) != (role == "superadmin"):
        raise AuthError("bad_role", "Owners cannot be assigned to a company, and other roles require one")
    if User.objects.filter(email__iexact=email).exists():
        raise AuthError("exists", "An account with this email already exists", status=409)
    raw = secrets.token_urlsafe(32)
    with transaction.atomic():
        pending(company.id if company else None).filter(email=email).update(revoked_at=now_utc())
        inv = Invitation.objects.create(
            email=email,
            company=company,
            role=role,
            can_switch_accounts=can_switch_accounts or role in ("admin", "superadmin"),
            token_hash=hash_token(raw),
            invited_by_id=invited_by,
            expires_at=now_utc() + timedelta(days=INVITATION_DAYS),
        )
    return inv, raw


def renew(inv: Invitation) -> str:
    """A fresh link (and expiry) for an invitation; the old link stops working."""
    if inv.accepted_at:
        raise AuthError("accepted", "This invitation has already been used")
    raw = secrets.token_urlsafe(32)
    inv.token_hash, inv.expires_at, inv.revoked_at = hash_token(raw), now_utc() + timedelta(days=INVITATION_DAYS), None
    inv.save(update_fields=["token_hash", "expires_at", "revoked_at"])
    return raw


def find(raw: str) -> Invitation:
    """The usable invitation for a link token, or AuthError."""
    inv = Invitation.objects.select_related("company").filter(token_hash=hash_token(raw or "")).first()
    if inv is None or inv.revoked_at:
        raise AuthError("invalid_invite", "This invitation link is invalid. Request a new invitation.", status=404)
    if inv.accepted_at:
        raise AuthError("used_invite", "This invitation has already been used. Sign in to continue.", status=410)
    if as_utc(inv.expires_at) <= now_utc():
        raise AuthError("expired_invite", "This invitation has expired. Request a new invitation.", status=410)
    if inv.company_id and not inv.company.is_active:
        raise AuthError("company_disabled", "Access for this company has been suspended.", status=403)
    return inv


def _create_user(inv: Invitation, name: str | None, password: str | None) -> User:
    user = User(
        email=inv.email,
        name=(name or "").strip() or None,
        role=inv.role,
        company=inv.company,
        can_switch_accounts=inv.can_switch_accounts,
        created_by_id=inv.invited_by_id,
        updated_by_id=inv.invited_by_id,
    )
    if password is None:
        user.set_unusable_password()  # Microsoft-only until they set one
    else:
        set_password(user, password)
    try:
        with transaction.atomic():
            user.save()
    except IntegrityError as e:  # someone with this email appeared meanwhile
        raise AuthError("exists", "An account with this email already exists. Sign in to continue.", status=409) from e
    inv.accepted_at, inv.accepted_user = now_utc(), user
    inv.save(update_fields=["accepted_at", "accepted_user"])
    return user


def accept(raw: str, name: str, password: str) -> User:
    """Sign-up from an invitation link: create the user with a password."""
    with transaction.atomic():
        inv = find(raw)
        Invitation.objects.select_for_update().filter(id=inv.id).first()  # one acceptance at a time
        return _create_user(inv, name, password)


def accept_for_microsoft(email: str, name: str | None) -> User | None:
    """Microsoft sign-in by someone with a pending invitation: accept it (no password). None if not invited."""
    inv = (
        Invitation.objects.select_related("company")
        .filter(email__iexact=email, accepted_at__isnull=True, revoked_at__isnull=True, expires_at__gt=now_utc())
        .order_by("-created_at")
        .first()
    )
    if inv is None or (inv.company_id and not inv.company.is_active):
        return None
    with transaction.atomic():
        return _create_user(inv, name, None)

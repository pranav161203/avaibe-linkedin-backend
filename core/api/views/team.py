"""Team management: who is in a company, their role, invitations, and who can switch accounts.

- Admins manage their own company's viewers and editors (and invite people up to editor).
- Super admins manage everyone in any company (?company_id=), and the super admins themselves (no company_id).
- Nobody changes their own role, deactivates or removes themselves.
- There is always at least one active owner.
- People join by invitation: adding someone creates a one-time sign-up link, not an account.
All of this is enforced here, on the server; the Team page only mirrors it."""

from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.api.errors import NO_CONTENT, fail
from core.api.params import int_param, parse
from core.auth.authentication import CurrentUser
from core.auth.permissions import default_account_id, require
from core.common.timeutil import as_utc, now_utc
from core.conf import FRONTEND_URL, email_configured
from core.models import Account, Company, Invitation, User
from core.schemas.auth import InviteIn
from core.schemas.team import DefaultAccountIn, MemberIn
from core.services.auth import AuthError, emails, invitations
from core.services.auth.audit import stamp
from core.services.auth.tokens import revoke_user_sessions

RANK = {r: i for i, r in enumerate(["viewer", "editor", "admin", "superadmin"])}


def _iso(dt) -> str | None:
    return as_utc(dt).isoformat() if dt else None


def _out(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "role": u.role,
        "can_switch_accounts": u.role in ("admin", "superadmin") or u.can_switch_accounts,
        "active": u.is_active,
        "has_password": u.has_usable_password(),
        "last_login_at": _iso(u.last_login),
        "created_at": _iso(u.created_at),
        "created_by": u.created_by.email if u.created_by_id else None,
    }


def invitation_out(inv: Invitation, token: str | None = None) -> dict:
    out = {
        "id": inv.id,
        "email": inv.email,
        "role": inv.role,
        "can_switch_accounts": inv.can_switch_accounts,
        "invited_by": inv.invited_by.email if inv.invited_by_id else None,
        "created_at": _iso(inv.created_at),
        "expires_at": _iso(inv.expires_at),
        "emailed_at": _iso(inv.emailed_at),
    }
    if token:  # only right after creating or renewing: the link can't be shown again later
        out["token"] = token
        out["link"] = _link(token)
    return out


def _link(token: str) -> str:
    return f"{FRONTEND_URL}/signup?token={token}"


def _send(inv: Invitation, token: str, me: CurrentUser) -> dict:
    """Email the new link (when email is set up) and say whether it went, next to the link to copy."""
    sent = emails.send_invitation(inv, _link(token), me.name or me.email or "Your administrator")
    out = invitation_out(inv, token)
    out["email_sent"] = sent
    return out


def _scope(request) -> int | None:
    """Which company's team this request is about. Admins: their own. Super admins: ?company_id=, or none for
    the super admins themselves."""
    me: CurrentUser = request.user
    if not me.is_superadmin:
        return me.company_id
    cid = int_param(request, "company_id")
    if cid is not None and not Company.objects.filter(id=cid).exists():
        fail(404, "Company not found")
    return cid


def _active_superadmins(excluding: int | None = None) -> int:
    qs = User.objects.filter(role="superadmin", is_active=True)
    if excluding is not None:
        qs = qs.exclude(id=excluding)
    return qs.count()


def _can_manage(me: CurrentUser, role: str) -> bool:
    """Admins manage viewers and editors; super admins manage everyone."""
    return me.at_least("superadmin") or RANK[role] < RANK["admin"]


def _guard(me: CurrentUser, target_role: str, new_role: str | None = None) -> None:
    if not _can_manage(me, target_role):
        fail(403, "Only an owner can change admins and owners")
    if new_role is not None and not _can_manage(me, new_role):
        fail(403, "Only an owner can give the Admin or Owner role")


def _members_qs(company_id: int | None):
    qs = User.objects.select_related("created_by")
    # No company: the super admins (platform team)
    return qs.filter(company_id=company_id) if company_id is not None else qs.filter(company__isnull=True, role="superadmin")


@api_view(["GET", "POST"])
def members(request):
    require(request.user, "admin")
    me = request.user
    company_id = _scope(request)
    if request.method == "GET":
        scoped = CurrentUser(id=None, email="", name=None, role="admin", can_switch_accounts=True, company_id=company_id)
        return Response(
            {
                "members": [_out(u) for u in _members_qs(company_id).order_by("email")],
                "invitations": [invitation_out(i) for i in invitations.pending(company_id)],
                "company": Company.objects.filter(id=company_id).values("id", "name").first() if company_id else None,
                "default_account_id": default_account_id(scoped) if company_id else None,
                "email_enabled": email_configured(),
            }
        )
    body = parse(InviteIn, request.data)
    _guard(me, body.role, body.role)
    if company_id is None and body.role != "superadmin":
        fail(400, "Select a company for this invitation")
    if company_id is not None and body.role == "superadmin":
        fail(400, "Owners are not assigned to a company. Invite them from the Owners team.")
    company = Company.objects.filter(id=company_id).first() if company_id else None
    try:
        inv, token = invitations.create(body.email, company, body.role, body.can_switch_accounts, me.id)
    except AuthError as e:
        fail(e.status, e.message)
    return Response(_send(inv, token, me), status=201)


def _target(request, user_id: int) -> User:
    me: CurrentUser = request.user
    u = User.objects.select_related("created_by").filter(id=user_id).first()
    if not u or (not me.is_superadmin and u.company_id != me.company_id):
        fail(404, "Member not found")
    return u


@api_view(["PUT", "DELETE"])
def member_detail(request, user_id: int):
    require(request.user, "admin")
    me = request.user
    u = _target(request, user_id)
    if me.id is not None and me.id == u.id:
        fail(400, "You cannot change or remove your own account")
    _guard(me, u.role)

    if request.method == "DELETE":
        if u.role == "superadmin" and u.is_active and _active_superadmins(excluding=u.id) == 0:
            fail(400, "The last owner cannot be removed")
        revoke_user_sessions(u.id, "removed")
        u.delete()
        return Response(status=NO_CONTENT)

    body = parse(MemberIn, request.data)
    _guard(me, u.role, body.role)
    if body.role != "superadmin" and u.company_id is None:
        fail(400, "Owners are not assigned to a company and cannot be given a company role")
    losing_super = u.role == "superadmin" and u.is_active and (body.role != "superadmin" or not body.active)
    if losing_super and _active_superadmins(excluding=u.id) == 0:
        fail(400, "There must always be at least one active owner")
    if User.objects.filter(email__iexact=body.email).exclude(id=u.id).exists():
        fail(409, "This email is already in use by another member")
    u.email, u.name, u.role = body.email, body.name, body.role
    u.can_switch_accounts, u.is_active = body.can_switch_accounts, body.active
    stamp(u, me.id)
    u.save()
    if not u.is_active:
        revoke_user_sessions(u.id, "user_disabled")
    return Response(_out(u))


def _invitation(request, invitation_id: int) -> Invitation:
    me: CurrentUser = request.user
    inv = Invitation.objects.select_related("invited_by").filter(id=invitation_id, accepted_at__isnull=True).first()
    if not inv or (not me.is_superadmin and inv.company_id != me.company_id):
        fail(404, "Invitation not found")
    _guard(me, inv.role)
    return inv


@api_view(["DELETE"])
def invitation_detail(request, invitation_id: int):
    require(request.user, "admin")
    inv = _invitation(request, invitation_id)
    if not inv.revoked_at:
        inv.revoked_at = now_utc()
        inv.save(update_fields=["revoked_at"])
    return Response(status=NO_CONTENT)


@api_view(["POST"])
def invitation_renew(request, invitation_id: int):
    require(request.user, "admin")
    inv = _invitation(request, invitation_id)
    try:
        token = invitations.renew(inv)
    except AuthError as e:
        fail(e.status, e.message)
    return Response(_send(inv, token, request.user))


@api_view(["PUT"])
def set_default_account(request):
    require(request.user, "admin")
    company_id = _scope(request)
    body = parse(DefaultAccountIn, request.data)
    if company_id is None:
        fail(400, "Select a company")
    if not Account.objects.filter(id=body.default_account_id, company_id=company_id).exists():
        fail(404, "Account not found")
    Company.objects.filter(id=company_id).update(default_account_id=body.default_account_id)
    return Response({"default_account_id": body.default_account_id})

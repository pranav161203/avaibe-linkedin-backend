"""Team management: who may sign in, their role, and who can switch accounts.

- Admins manage viewers and editors (and can give roles up to editor).
- Super admins manage everyone, including admins and other super admins.
- Nobody changes their own role, deactivates or removes themselves.
- There is always at least one active super admin.
All of this is enforced here, on the server; the Team page only mirrors it."""


from django.contrib.sessions.models import Session
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.api.errors import NO_CONTENT, fail
from core.api.params import parse
from core.auth.authentication import CurrentUser
from core.auth.permissions import default_account_id, require
from core.common.timeutil import as_utc
from core.models import Account, User
from core.schemas.team import DefaultAccountIn, MemberIn
from core.services import settings_store

RANK = {r: i for i, r in enumerate(["viewer", "editor", "admin", "superadmin"])}


def _out(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "role": u.role,
        "can_switch_accounts": u.role in ("admin", "superadmin") or u.can_switch_accounts,
        "active": u.is_active,
        "last_login_at": as_utc(u.last_login).isoformat() if u.last_login else None,
    }


def _active_superadmins(excluding: int | None = None) -> int:
    qs = User.objects.filter(role="superadmin", is_active=True)
    if excluding is not None:
        qs = qs.exclude(id=excluding)
    return qs.count()


def _sign_out_everywhere(user_id: int) -> None:
    for s in Session.objects.all():
        if s.get_decoded().get("_auth_user_id") == str(user_id):
            s.delete()


def _can_manage(me: CurrentUser, role: str) -> bool:
    """Admins manage viewers and editors; super admins manage everyone."""
    return me.at_least("superadmin") or RANK[role] < RANK["admin"]


def _guard(me: CurrentUser, target_role: str, new_role: str | None = None) -> None:
    if not _can_manage(me, target_role):
        fail(403, "Only a super admin can change admins and super admins")
    if new_role is not None and not _can_manage(me, new_role):
        fail(403, "Only a super admin can give the Admin or Super admin role")


@api_view(["GET", "POST"])
def members(request):
    require(request.user, "admin")
    if request.method == "GET":
        return Response({"members": [_out(u) for u in User.objects.order_by("email")], "default_account_id": default_account_id()})
    body = parse(MemberIn, request.data)
    _guard(request.user, body.role, body.role)
    if User.objects.filter(email__iexact=body.email).exists():
        fail(409, "This person is already on the team")
    u = User.objects.create_user(
        body.email, name=body.name, role=body.role, can_switch_accounts=body.can_switch_accounts, is_active=body.active
    )
    return Response(_out(u), status=201)


@api_view(["PUT", "DELETE"])
def member_detail(request, user_id: int):
    require(request.user, "admin")
    u = User.objects.filter(id=user_id).first()
    if not u:
        fail(404, "Team member not found")

    me = request.user
    if me.id is not None and me.id == u.id:
        fail(400, "You can't change or remove your own account: ask another admin")
    _guard(me, u.role)

    if request.method == "DELETE":
        if u.role == "superadmin" and u.is_active and _active_superadmins(excluding=u.id) == 0:
            fail(400, "You can't remove the last super admin")
        _sign_out_everywhere(u.id)
        u.delete()
        return Response(status=NO_CONTENT)

    body = parse(MemberIn, request.data)
    _guard(me, u.role, body.role)
    losing_super = u.role == "superadmin" and u.is_active and (body.role != "superadmin" or not body.active)
    if losing_super and _active_superadmins(excluding=u.id) == 0:
        fail(400, "There must always be at least one active super admin")
    if User.objects.filter(email__iexact=body.email).exclude(id=u.id).exists():
        fail(409, "Another team member already uses this email")
    u.email, u.name, u.role = body.email, body.name, body.role
    u.can_switch_accounts, u.is_active = body.can_switch_accounts, body.active
    u.save()
    if not u.is_active:
        _sign_out_everywhere(u.id)
    return Response(_out(u))


@api_view(["PUT"])
def set_default_account(request):
    require(request.user, "admin")
    body = parse(DefaultAccountIn, request.data)
    if not Account.objects.filter(id=body.default_account_id).exists():
        fail(404, "Account not found")
    settings_store.save("access", {"default_account_id": body.default_account_id})
    return Response({"default_account_id": body.default_account_id})

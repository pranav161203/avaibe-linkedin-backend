"""Companies (super admins only): list, create, change, pause. A company's people and invitations are managed
through the team endpoints with ?company_id=."""

from django.db.models import Count, Q
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.api.errors import fail
from core.api.params import parse
from core.auth.permissions import require_superadmin
from core.common.timeutil import as_utc, now_utc
from core.models import Company
from core.schemas.auth import CompanyIn, CompanyUpdateIn
from core.services.auth import AuthError
from core.services.auth import companies as company_service


def company_out(c: Company) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "slug": c.slug,
        "website": c.website,
        "country": c.country,
        "industry": c.industry,
        "is_active": c.is_active,
        "default_account_id": c.default_account_id,
        "users": getattr(c, "n_users", None),
        "accounts": getattr(c, "n_accounts", None),
        "pending_invitations": getattr(c, "n_invites", None),
        "created_at": as_utc(c.created_at).isoformat(),
        "created_by": c.created_by.email if c.created_by_id else None,
        "updated_at": as_utc(c.updated_at).isoformat(),
        "updated_by": c.updated_by.email if c.updated_by_id else None,
    }


def _qs():
    open_invite = Q(invitations__accepted_at__isnull=True, invitations__revoked_at__isnull=True, invitations__expires_at__gt=now_utc())
    return Company.objects.select_related("created_by", "updated_by").annotate(
        n_users=Count("users", distinct=True),
        n_accounts=Count("accounts", distinct=True),
        n_invites=Count("invitations", filter=open_invite, distinct=True),
    )


@api_view(["GET", "POST"])
def companies(request):
    require_superadmin(request.user)
    if request.method == "GET":
        return Response({"companies": [company_out(c) for c in _qs().order_by("name")]})
    body = parse(CompanyIn, request.data)
    try:
        c = company_service.create(body.model_dump(), request.user.id)
    except AuthError as e:
        fail(e.status, e.message)
    return Response(company_out(_qs().get(id=c.id)), status=201)


@api_view(["GET", "PUT"])
def company_detail(request, company_id: int):
    require_superadmin(request.user)
    c = _qs().filter(id=company_id).first()
    if not c:
        fail(404, "Company not found")
    if request.method == "PUT":
        body = parse(CompanyUpdateIn, request.data)
        try:
            company_service.update(c, body.model_dump(exclude_unset=True), request.user.id)
        except AuthError as e:
            fail(e.status, e.message)
        c = _qs().get(id=company_id)
    return Response(company_out(c))

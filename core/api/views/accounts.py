from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.api.errors import fail
from core.api.params import parse
from core.auth.permissions import allowed_account_ids, check_account, require
from core.models import Account, Company
from core.schemas.accounts import AccountIn


def account_out(a: Account) -> dict:
    return {
        "id": a.id,
        "name": a.name,
        "kind": a.kind,
        "linkedin_url": a.linkedin_url,
        "is_test": a.is_test,
        "parent_id": a.parent_id,
        "company_id": a.company_id,
    }


def _company_for_new(user, requested: int | None) -> int:
    """Company admins add to their own company; super admins say which (or the only one there is)."""
    if not user.is_superadmin:
        return user.company_id
    if requested is not None:
        if not Company.objects.filter(id=requested).exists():
            fail(404, "Company not found")
        return requested
    ids = list(Company.objects.values_list("id", flat=True)[:2])
    if len(ids) != 1:
        fail(422, "Select a company for this account")
    return ids[0]


@api_view(["GET", "POST"])
def accounts(request):
    if request.method == "GET":
        # Only the accounts this person may see (just the default account for people without the switcher)
        ids = allowed_account_ids(request.user)
        return Response([account_out(a) for a in Account.objects.filter(id__in=ids).order_by("id")])
    require(request.user, "admin")
    body = parse(AccountIn, request.data)
    data = body.model_dump(exclude={"company_id"})
    acc = Account.objects.create(**data, company_id=_company_for_new(request.user, body.company_id))
    return Response(account_out(acc), status=201)


@api_view(["PUT"])
def account_detail(request, account_id: int):
    require(request.user, "admin")
    check_account(request.user, account_id)
    acc = Account.objects.filter(id=account_id).first()
    if not acc:
        fail(404, "Account not found")
    body = parse(AccountIn, request.data)
    for k, v in body.model_dump(exclude={"company_id"}).items():
        setattr(acc, k, v)
    if body.company_id is not None and body.company_id != acc.company_id:
        if not request.user.is_superadmin:
            fail(403, "Only an owner can move an account to another company")
        acc.company_id = _company_for_new(request.user, body.company_id)
    acc.save()
    return Response(account_out(acc))

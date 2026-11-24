from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.api.errors import fail
from core.api.params import parse
from core.auth.permissions import allowed_account_ids, require
from core.models import Account
from core.schemas.accounts import AccountIn


def account_out(a: Account) -> dict:
    return {"id": a.id, "name": a.name, "kind": a.kind, "linkedin_url": a.linkedin_url, "is_test": a.is_test, "parent_id": a.parent_id}


@api_view(["GET", "POST"])
def accounts(request):
    if request.method == "GET":
        # Only the accounts this person may see (just the default account for people without the switcher)
        ids = allowed_account_ids(request.user)
        return Response([account_out(a) for a in Account.objects.filter(id__in=ids).order_by("id")])
    require(request.user, "admin")
    body = parse(AccountIn, request.data)
    return Response(account_out(Account.objects.create(**body.model_dump())), status=201)


@api_view(["PUT"])
def account_detail(request, account_id: int):
    require(request.user, "admin")
    acc = Account.objects.filter(id=account_id).first()
    if not acc:
        fail(404, "Account not found")
    for k, v in parse(AccountIn, request.data).model_dump().items():
        setattr(acc, k, v)
    acc.save()
    return Response(account_out(acc))

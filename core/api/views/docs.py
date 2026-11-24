"""Shared per-account documents for the Brand section: the LinkedIn page checklist and the competitor list."""


from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.api.errors import fail
from core.api.params import parse
from core.auth.permissions import check_account, require
from core.common.timeutil import as_utc
from core.models import Account, AccountDoc
from core.schemas.accounts import KINDS


def _out(kind: str, doc: AccountDoc | None) -> dict:
    return {
        "kind": kind,
        "data": doc.data if doc else KINDS[kind]().model_dump(mode="json"),
        "updated_by": doc.updated_by if doc else None,
        "updated_at": as_utc(doc.updated_at).isoformat() if doc else None,
    }


@api_view(["GET", "PUT"])
def account_doc(request, account_id: int, kind: str):
    user = request.user
    if kind not in KINDS:
        fail(404, "Unknown document")
    if not Account.objects.filter(id=account_id).exists():
        fail(404, "Account not found")
    check_account(user, account_id)
    if request.method == "GET":
        return Response(_out(kind, AccountDoc.objects.filter(account_id=account_id, kind=kind).first()))

    require(user, "editor")
    body = parse(KINDS[kind], request.data)
    doc, _ = AccountDoc.objects.update_or_create(
        account_id=account_id,
        kind=kind,
        defaults={"data": body.model_dump(mode="json"), "updated_by": None if user.dev else user.email},
    )
    return Response(_out(kind, doc))



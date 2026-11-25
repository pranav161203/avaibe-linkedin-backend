"""Company knowledge base.

A source applies to every account (account_ids empty) or only to the accounts listed. People see company-wide sources
plus those for accounts they may use; they can change a source only if they may use all of its accounts.

GET    /knowledge?account_id=     sources for that account (company-wide + its own), plus totals
POST   /knowledge                 add pasted text (JSON {title, content, account_ids}) or a file
                                  (multipart: file, title?, account_ids? as "1,2")
GET    /knowledge/<id>            one source in full
PUT    /knowledge/<id>            edit title, text and accounts (the chunks are rebuilt)
DELETE /knowledge/<id>
GET    /knowledge/search?q=&account_id=   the passages Claude would be given for that account
"""

from django.db.models import Count
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.api.errors import NO_CONTENT, fail
from core.api.params import int_param, parse
from core.auth.permissions import allowed_account_ids, check_account, require
from core.common.timeutil import as_utc
from core.models import Account, Company, KnowledgeSource
from core.schemas.knowledge import KnowledgeIn
from core.services import knowledge


def _out(s: KnowledgeSource, chunks: int | None = None, full: bool = False) -> dict:
    out = {
        "id": s.id,
        "title": s.title,
        "kind": s.kind,
        "file_name": s.file_name,
        "chars": s.chars,
        "chunks": chunks if chunks is not None else s.chunk_items.count(),
        "account_ids": sorted(a.id for a in s.accounts.all()),
        "created_by": s.created_by,
        "updated_by": s.updated_by,
        "created_at": as_utc(s.created_at).isoformat(),
        "updated_at": as_utc(s.updated_at).isoformat(),
    }
    if full:
        out["content"] = s.content
        out["sections"] = knowledge.section_count(s.content)
    return out


def _email(user) -> str | None:
    return None if user.dev else user.email


def _check_targets(user, account_ids: list[int]) -> list[int]:
    """Accounts a source may be set to: only ones this person may use."""
    ids = sorted(set(account_ids))
    allowed = set(allowed_account_ids(user))
    if any(i not in allowed for i in ids):
        fail(404, "Account not found")
    return ids


def _company(user, account_id: int | None) -> int | None:
    """The company a new source belongs to: that of the account being worked in (checked), else the person's."""
    if account_id is not None:
        check_account(user, account_id)
        return Account.objects.filter(id=account_id).values_list("company_id", flat=True).first()
    if user.company_id is not None:
        return user.company_id
    # A super admin without a company: fine while there is at most one company to mean
    ids = list(Company.objects.values_list("id", flat=True)[:2])
    if len(ids) > 1:
        fail(422, "Select an account")
    return ids[0] if ids else None


def _get(user, source_id: int, to_change: bool = False) -> KnowledgeSource:
    """A source this person may see (any of its accounts allowed, or company-wide); to change it, all of them."""
    s = KnowledgeSource.objects.prefetch_related("accounts").filter(id=source_id).first()
    if not s or not (user.is_superadmin or s.company_id == user.company_id):
        fail(404, "Source not found")
    ids = {a.id for a in s.accounts.all()}
    allowed = set(allowed_account_ids(user))
    if ids and not ids & allowed:
        fail(404, "Source not found")
    if to_change and not ids <= allowed:
        fail(403, "This source applies to accounts you do not have access to and cannot be changed")
    return s


@api_view(["GET", "POST"])
def sources(request):
    user = request.user
    if request.method == "GET":
        account_id = int_param(request, "account_id", required=True)
        check_account(user, account_id)
        rows = knowledge.for_account(account_id).prefetch_related("accounts").annotate(n=Count("chunk_items", distinct=True))
        items = [_out(s, s.n) for s in rows]
        return Response({"sources": items, "total_chunks": sum(i["chunks"] for i in items), "max_chars": knowledge.MAX_CHARS})

    require(user, "editor")
    upload = request.FILES.get("file")
    try:
        if upload:
            if upload.size > knowledge.MAX_BYTES:
                fail(400, "Files must be 5 MB or smaller. Split the file or paste the relevant text.")
            raw = str(request.data.get("account_ids") or "")
            try:
                ids = [int(x) for x in raw.split(",") if x.strip()]
            except ValueError:
                fail(422, "Account IDs must be comma-separated numbers")
            ids = _check_targets(user, ids)
            text = knowledge.read_file(upload.name, upload.read())
            title = (request.data.get("title") or "").strip() or upload.name.rsplit(".", 1)[0]
            company = _company(user, int_param(request, "account_id"))
            s = knowledge.add_source(title, text, _email(user), company, file_name=upload.name, account_ids=ids)
        else:
            body = parse(KnowledgeIn, request.data)
            company = _company(user, int_param(request, "account_id"))
            s = knowledge.add_source(body.title, body.content, _email(user), company, account_ids=_check_targets(user, body.account_ids))
    except knowledge.KnowledgeError as e:
        fail(400, str(e))
    return Response(_out(s, full=True), status=201)


@api_view(["GET", "PUT", "DELETE"])
def source_detail(request, source_id: int):
    user = request.user
    if request.method == "GET":
        return Response(_out(_get(user, source_id), full=True))
    require(user, "editor")
    s = _get(user, source_id, to_change=True)
    if request.method == "DELETE":
        s.delete()
        return Response(status=NO_CONTENT)
    body = parse(KnowledgeIn, request.data)
    try:
        s = knowledge.update_source(s, body.title, body.content, _email(user), account_ids=_check_targets(user, body.account_ids))
    except knowledge.KnowledgeError as e:
        fail(400, str(e))
    return Response(_out(s, full=True))


@api_view(["GET"])
def search(request):
    account_id = int_param(request, "account_id", required=True)
    check_account(request.user, account_id)
    q = (request.query_params.get("q") or "").strip()[:300]
    return Response({"query": q, "results": knowledge.search(q, limit=5, account_id=account_id) if q else []})

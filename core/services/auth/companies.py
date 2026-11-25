"""Creating and changing companies (super admins only; the views check that)."""

from django.db import transaction
from django.utils.text import slugify

from core.models import Account, Company
from core.services.auth import AuthError
from core.services.auth.audit import stamp
from core.services.auth.tokens import revoke_user_sessions

FIELDS = ("name", "website", "country", "industry")


def _unique_slug(name: str, exclude: int | None = None) -> str:
    base = slugify(name)[:50] or "company"
    slug, n = base, 2
    while Company.objects.filter(slug=slug).exclude(id=exclude).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


def create(data: dict, actor_id: int | None) -> Company:
    if Company.objects.filter(name__iexact=data["name"].strip()).exists():
        raise AuthError("exists", "A company with this name already exists", status=409)
    c = Company(**{k: data.get(k) for k in FIELDS if k in data}, slug=_unique_slug(data["name"]))
    stamp(c, actor_id, created=True)
    c.save()
    return c


def update(c: Company, data: dict, actor_id: int | None) -> Company:
    data = {k: v for k, v in data.items() if v is not None or k in ("website", "industry", "default_account_id")}
    name = (data.get("name") or c.name).strip()
    if Company.objects.filter(name__iexact=name).exclude(id=c.id).exists():
        raise AuthError("exists", "A company with this name already exists", status=409)
    for k in FIELDS:
        if k in data:
            setattr(c, k, data[k])
    if "default_account_id" in data:
        acc_id = data["default_account_id"]
        if acc_id is not None and not Account.objects.filter(id=acc_id, company=c).exists():
            raise AuthError("bad_account", "This account does not belong to the company", status=404)
        c.default_account_id = acc_id
    deactivating = "is_active" in data and c.is_active and not data["is_active"]
    if "is_active" in data:
        c.is_active = data["is_active"]
    stamp(c, actor_id)
    with transaction.atomic():
        c.save()
        if deactivating:
            for uid in c.users.values_list("id", flat=True):
                revoke_user_sessions(uid, "user_disabled")
    return c

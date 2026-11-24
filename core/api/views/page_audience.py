"""Page-level follower / visitor demographics, recorded weekly from LinkedIn page analytics."""

from collections import defaultdict
from datetime import date

from django.db import transaction
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.api.errors import NO_CONTENT, fail
from core.api.params import parse
from core.auth.permissions import check_account, require
from core.models import PAGE_DAILY_FIELDS, Account, PageAudience, PageDaily
from core.schemas.accounts import PageAudienceIn
from core.serializers import page_audience_shares


def _check(user, account_id: int) -> None:
    if not Account.objects.filter(id=account_id).exists():
        fail(404, "Account not found")
    check_account(user, account_id)


@api_view(["GET"])
def page_daily(request, account_id: int):
    """Daily page activity (impressions, page views, new followers...) imported from LinkedIn exports,
    oldest first. Dates are UTC days, as LinkedIn reports them."""
    _check(request.user, account_id)
    rows = PageDaily.objects.filter(account_id=account_id).order_by("date")
    return Response([{"date": r.date.isoformat(), **{f: getattr(r, f) for f in PAGE_DAILY_FIELDS}} for r in rows])


@api_view(["GET", "PUT", "DELETE"])
def page_audience(request, account_id: int):
    user = request.user
    _check(user, account_id)

    if request.method == "GET":
        # One entry per (date, followers|visitors), oldest first, with computed shares
        groups: dict[tuple[date, str], list[PageAudience]] = defaultdict(list)
        for r in PageAudience.objects.filter(account_id=account_id).order_by("as_of", "id"):
            groups[(r.as_of, r.audience)].append(r)
        out = []
        for (as_of, audience), g in sorted(groups.items()):
            out.append(
                {
                    "as_of": as_of.isoformat(),
                    "audience": audience,
                    "total": g[0].total,
                    "rows": [
                        {"dimension": r.dimension, "value": r.value, "count": r.count, "pct": r.pct}
                        for r in sorted(g, key=lambda r: (r.dimension, -(r.count or 0), -(r.pct or 0)))
                    ],
                    "shares": page_audience_shares(g),
                }
            )
        return Response(out)

    require(user, "editor")
    if request.method == "DELETE":
        try:
            as_of = date.fromisoformat(request.query_params.get("as_of", ""))
        except ValueError:
            fail(422, "as_of must be a date (YYYY-MM-DD)")
        PageAudience.objects.filter(account_id=account_id, as_of=as_of, audience=request.query_params.get("audience", "")).delete()
        return Response(status=NO_CONTENT)

    # PUT: replace the snapshot for (as_of, audience) with the rows given
    body = parse(PageAudienceIn, request.data)
    seen: set[tuple[str, str]] = set()
    for r in body.rows:
        if r.count is None and r.pct is None:
            fail(400, f"{r.dimension} = {r.value}: give a count or a percentage")
        if r.count is not None and body.total is not None and r.count > body.total:
            fail(400, f"{r.dimension} = {r.value}: count is larger than the total")
        key = (r.dimension, r.value.strip().lower())
        if key in seen:
            fail(400, f"Duplicate entry: {r.dimension} = {r.value}")
        seen.add(key)
    with transaction.atomic():
        PageAudience.objects.filter(account_id=account_id, as_of=body.as_of, audience=body.audience).delete()
        PageAudience.objects.bulk_create(
            [
                PageAudience(
                    account_id=account_id,
                    as_of=body.as_of,
                    audience=body.audience,
                    total=body.total,
                    dimension=r.dimension,
                    value=r.value.strip(),
                    count=r.count,
                    pct=r.pct,
                )
                for r in body.rows
            ]
        )
    return Response({"saved": len(body.rows)})

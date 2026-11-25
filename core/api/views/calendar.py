"""Content calendar: posts (ours and the linked founders'), planned posts, holidays, periods and events
for one month-sized window, plus the posting-time model's advice for each date."""

from datetime import date
from typing import Any

from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.api.errors import fail
from core.api.params import int_param
from core.auth.permissions import allowed_account_ids, check_account
from core.common.timeutil import as_utc, slot_label, to_uae
from core.models import Account, PlannedPost
from core.services import calendar_data
from core.services.analytics import performance as a
from core.services.calendar import posts_for, related, timing_advice, title

MAX_DAYS = 62


@api_view(["GET"])
def calendar(request):
    account_id = int_param(request, "account_id", required=True)
    check_account(request.user, account_id)
    try:
        start = date.fromisoformat(request.query_params["from"])
        end = date.fromisoformat(request.query_params["to"])
    except (KeyError, ValueError):
        fail(422, "Start and end dates are required, in YYYY-MM-DD format")
    if start > end or (end - start).days > MAX_DAYS:
        fail(422, f"The start date must precede the end date by no more than {MAX_DAYS} days")

    account = Account.objects.get(id=account_id)
    allowed = set(allowed_account_ids(request.user))
    accounts = related(account, allowed)

    posts: list[dict[str, Any]] = []
    for acc in accounts:
        posts += posts_for(acc, start, end)
    posts.sort(key=lambda p: (p["date"], p["time"] or ""))

    planned = []
    for p in PlannedPost.objects.filter(account_id=account_id, scheduled_at__isnull=False).exclude(status="published"):
        local = to_uae(as_utc(p.scheduled_at))
        if start <= local.date() <= end:
            planned.append(
                {
                    "id": p.id,
                    "ref": p.ref,
                    "date": local.date().isoformat(),
                    "time": local.strftime("%H:%M"),
                    "slot": slot_label(local),
                    "format": p.format,
                    "status": p.status,
                    "title": title(p.caption),
                }
            )
    planned.sort(key=lambda p: (p["date"], p["time"]))

    first, last = calendar_data.covered_years()
    return Response(
        {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "accounts": [{"id": x.id, "name": x.name, "kind": x.kind} for x in accounts],
            "posts": posts,
            "planned": planned,
            "items": calendar_data.items_between(start, end),
            "timing": timing_advice(a.load_posts(account_id), start, end),
            "dates_cover": [first, last],
        }
    )


MAX_ITEM_DAYS = 400


@api_view(["GET"])
def calendar_items(request):
    """Only the holidays, periods and events between two dates (no posts or advice), for chart markers."""
    try:
        start = date.fromisoformat(request.query_params["from"])
        end = date.fromisoformat(request.query_params["to"])
    except (KeyError, ValueError):
        fail(422, "Start and end dates are required, in YYYY-MM-DD format")
    if start > end or (end - start).days > MAX_ITEM_DAYS:
        fail(422, f"The start date must precede the end date by no more than {MAX_ITEM_DAYS} days")
    return Response({"from": start.isoformat(), "to": end.isoformat(), "items": calendar_data.items_between(start, end)})

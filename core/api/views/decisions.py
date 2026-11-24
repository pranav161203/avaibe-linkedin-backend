"""The team's shared decisions on suggestions and Claude ideas: Do it / Later / Dismiss / Done."""

from datetime import timedelta

from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.api.params import int_param, parse
from core.auth.permissions import check_account, require
from core.common.timeutil import as_utc, now_utc
from core.models import SuggestionDecision
from core.schemas.analytics import DecisionIn

LATER_DAYS = 7  # "Later" hides an item for a week, then it comes back


def _out(d: SuggestionDecision) -> dict:
    return {
        "key": d.key,
        "status": d.status,
        "until": as_utc(d.until).isoformat() if d.until else None,
        "decided_by": d.decided_by,
        "updated_at": as_utc(d.updated_at).isoformat(),
    }


@api_view(["GET", "PUT"])
def decisions(request):
    user = request.user
    if request.method == "GET":
        account_id = int_param(request, "account_id", required=True)
        check_account(user, account_id)
        # A "Later" whose week is up counts as no decision again
        rows = [d for d in SuggestionDecision.objects.filter(account_id=account_id)
                if not (d.status == "later" and d.until and as_utc(d.until) <= now_utc())]
        return Response([_out(d) for d in rows])

    require(user, "editor")
    body = parse(DecisionIn, request.data)
    check_account(user, body.account_id)
    if body.status is None:
        SuggestionDecision.objects.filter(account_id=body.account_id, key=body.key).delete()
        return Response({"key": body.key, "status": None})
    d, _ = SuggestionDecision.objects.update_or_create(
        account_id=body.account_id,
        key=body.key,
        defaults={
            "status": body.status,
            "until": now_utc() + timedelta(days=LATER_DAYS) if body.status == "later" else None,
            "decided_by": None if user.dev else user.email,
        },
    )
    return Response(_out(d))

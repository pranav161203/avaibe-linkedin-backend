from datetime import date, timedelta

from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.api.errors import fail
from core.api.params import choice_param, int_param, parse
from core.auth.permissions import check_account
from core.common.timeutil import now_utc, to_uae
from core.models import CHECKPOINT_HOURS, FORMATS
from core.schemas.analytics import SimilarIn
from core.services import settings_store
from core.services.analytics import performance as a
from core.services.analytics import segments, similar, timing
from core.services.analytics import suggestions as sugg

CHECKPOINT_Q = list(CHECKPOINT_HOURS) + ["latest"]


def _metric(request) -> str:
    metric = request.query_params.get("metric", "impressions")
    if metric not in a.ALL_METRICS:
        fail(400, f"Unknown metric: {metric}")
    return metric


def _posts(request):
    """Every analytics endpoint goes through here: checks the person may see this account, then loads its posts."""
    account_id = int_param(request, "account_id", required=True)
    check_account(request.user, account_id)
    posts = a.load_posts(account_id)
    # Optional time range (the Data page's "Time range"): the last N days, or custom dates from/to (UAE dates, inclusive)
    days = int_param(request, "days")
    if days is not None:
        if not 1 <= days <= 3650:
            fail(422, "Days must be between 1 and 3650")
        since = now_utc() - timedelta(days=days)
        posts = [p for p in posts if p.published_at >= since]
    try:
        start = date.fromisoformat(request.query_params["from"]) if request.query_params.get("from") else None
        end = date.fromisoformat(request.query_params["to"]) if request.query_params.get("to") else None
    except ValueError:
        fail(422, "Start and end must be dates in YYYY-MM-DD format")
    if start and end and start > end:
        fail(422, "The start date must be on or before the end date")
    if start:
        posts = [p for p in posts if to_uae(p.published_at).date() >= start]
    if end:
        posts = [p for p in posts if to_uae(p.published_at).date() <= end]
    return posts


def _cp(request) -> str:
    return choice_param(request, "checkpoint", CHECKPOINT_Q, "24h")


@api_view(["GET"])
def meta(request):
    return Response(
        {
            "segments": segments.describe(),
            "segment_keywords": settings_store.get("segments"),
            "formats": FORMATS,
            "metrics": sorted(a.ALL_METRICS),
            "format_time_metric": a.FORMAT_TIME_METRIC,
            "min_history": a.min_history(),
            "min_posts_per_slot": a.min_slot_posts(),
            "group_keys": sorted(a.GROUP_KEYS),
        }
    )


@api_view(["GET"])
def overview(request):
    return Response(a.overview(_posts(request), _cp(request)))


@api_view(["GET"])
def rankings(request):
    limit = int_param(request, "limit", 10)
    if not 1 <= limit <= 50:
        fail(422, "Limit must be between 1 and 50")
    return Response(a.rankings(_posts(request), _cp(request), _metric(request), limit))


@api_view(["GET"])
def formats(request):
    return Response(a.format_comparison(_posts(request), _cp(request)))


@api_view(["GET"])
def heatmap(request):
    fmt = request.query_params.get("format") or None
    if fmt and fmt not in FORMATS:
        fail(400, f"Unknown format: {fmt}")
    return Response(a.heatmap(_posts(request), _cp(request), _metric(request), fmt))


@api_view(["GET"])
def timing_model(request):
    """Posting-time model v2: timing effects after removing content and page growth, with a backtest."""
    metric = request.query_params.get("metric", "impressions")
    if metric not in timing.TIMING_METRICS:
        fail(400, f"Metric must be one of: {', '.join(timing.TIMING_METRICS)}")
    account_id = int_param(request, "account_id", required=True)
    check_account(request.user, account_id)
    # Always the full history: the model needs every past post, not just the chosen time range
    return Response(timing.build(a.load_posts(account_id), metric))


@api_view(["GET"])
def best_slots(request):
    return Response(a.best_slots(_posts(request), _cp(request)))


@api_view(["GET"])
def groups(request):
    by = request.query_params.get("by", "topic")
    if by not in a.GROUP_KEYS:
        fail(400, f"Grouping must be one of: {', '.join(sorted(a.GROUP_KEYS))}")
    return Response(a.groups(_posts(request), _cp(request), by))


@api_view(["GET"])
def consistency(request):
    return Response(a.consistency(_posts(request), _cp(request)))


@api_view(["GET"])
def suggestions(request):
    """Explained next steps: what / when / who / why / boost / risk / confidence / how to measure."""
    return Response(sugg.build(_posts(request)))


@api_view(["POST"])
def similar_posts(request):
    """Past posts on the same topic as each idea, and how they did (read-only; POST only because of the body size)."""
    body = parse(SimilarIn, request.data)
    check_account(request.user, body.account_id)
    return Response(similar.find_similar(body.account_id, [q.model_dump() for q in body.queries]))


@api_view(["GET"])
def due_snapshots(request):
    return Response(a.due_snapshots(_posts(request)))

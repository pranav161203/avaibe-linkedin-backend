from django.db import IntegrityError, transaction
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.api.errors import NO_CONTENT, fail
from core.api.params import choice_param, int_param, parse
from core.auth.permissions import allowed_account_ids, check_account, require
from core.common.timeutil import now_utc
from core.models import CHECKPOINT_HOURS, FORMATS, Account, Post, PostAudience, Snapshot
from core.schemas.posts import PostAudienceIn, PostIn, SnapshotIn
from core.serializers import post_out, snapshot_out
from core.services.analytics import performance as analytics

CHECKPOINT_Q = list(CHECKPOINT_HOURS) + ["latest"]


def _get_post(post_id: int, user) -> Post:
    p = analytics.posts_queryset().filter(id=post_id).first()
    if not p or p.account_id not in allowed_account_ids(user):
        fail(404, "Post not found")
    return p


def _checkpoint(cp: str) -> str:
    if cp not in CHECKPOINT_HOURS:
        fail(422, f"checkpoint must be one of {list(CHECKPOINT_HOURS)}")
    return cp


def _save_post(fn):
    try:
        with transaction.atomic():
            return fn()
    except IntegrityError:
        fail(409, "A post with this URL already exists")


@api_view(["GET", "POST"])
def posts(request):
    user = request.user
    if request.method == "POST":
        require(user, "editor")
        body = parse(PostIn, request.data)
        if not Account.objects.filter(id=body.account_id).exists():
            fail(404, "Account not found")
        check_account(user, body.account_id)
        data = body.model_dump()
        data["time_known"] = True if data["time_known"] is None else data["time_known"]
        p = _save_post(lambda: Post.objects.create(**data))
        return Response(post_out(_get_post(p.id, user)), status=201)

    # GET: one account, or every account this person may see. Classification always uses
    # each post's OWN account as the baseline.
    metric = request.query_params.get("metric", "impressions")
    if metric not in analytics.ALL_METRICS:
        fail(400, f"Unknown metric '{metric}'")
    checkpoint = choice_param(request, "checkpoint", CHECKPOINT_Q, "24h")
    fmt = request.query_params.get("format") or None
    account_id = int_param(request, "account_id")
    if account_id is not None:
        check_account(user, account_id)
        ids = [account_id]
    else:
        ids = allowed_account_ids(user)
    out = []
    for aid in ids:
        items = analytics.load_posts(aid)
        labels = analytics.classifications(items, checkpoint, metric)
        for p in items:
            if fmt and p.format != fmt:
                continue
            d = post_out(p)
            d["classification"] = labels.get(p.id)
            out.append(d)
    out.sort(key=lambda d: d["published_at"], reverse=True)
    return Response(out)


@api_view(["GET", "PUT", "DELETE"])
def post_detail(request, post_id: int):
    user = request.user
    if request.method == "GET":
        return Response(post_out(_get_post(post_id, user)))
    require(user, "editor")
    p = _get_post(post_id, user)
    if request.method == "DELETE":
        p.delete()
        return Response(status=NO_CONTENT)
    body = parse(PostIn, request.data)
    check_account(user, body.account_id)  # can't move a post into an account you can't see

    def apply():
        data = body.model_dump()
        if data["time_known"] is None:
            del data["time_known"]  # the edit form doesn't send it: keep what the import recorded
        for k, v in data.items():
            setattr(p, k, v)
        p.topic_suggested = False  # someone saved the post, so the topic is now theirs
        p.save()

    _save_post(apply)
    return Response(post_out(_get_post(post_id, user)))


@api_view(["PUT", "DELETE"])
def snapshot(request, post_id: int, checkpoint: str):
    user = request.user
    require(user, "editor")
    cp = _checkpoint(checkpoint)
    p = _get_post(post_id, user)
    existing = Snapshot.objects.filter(post=p, checkpoint=cp).first()
    if request.method == "DELETE":
        if not existing:
            fail(404, "Snapshot not found")
        existing.delete()
        return Response(status=NO_CONTENT)
    data = parse(SnapshotIn, request.data).model_dump()
    data["captured_at"] = data["captured_at"] or now_utc()
    if existing is None:
        existing = Snapshot.objects.create(post=p, checkpoint=cp, **data)
    else:
        for k, v in data.items():
            setattr(existing, k, v)
        existing.save()
    return Response(snapshot_out(existing))


@api_view(["PUT"])
def audience(request, post_id: int):
    """Replace the post's audience breakdown with the rows given (empty list clears it)."""
    user = request.user
    require(user, "editor")
    p = _get_post(post_id, user)
    body = parse(PostAudienceIn, request.data)
    seen: set[tuple[str, str]] = set()
    for r in body.rows:
        key = (r.dimension, r.value.lower())
        if key in seen:
            fail(400, f"Duplicate entry: {r.dimension} = {r.value}")
        seen.add(key)
    for dim in {r.dimension for r in body.rows}:
        total = sum(r.pct for r in body.rows if r.dimension == dim)
        if total > 100.5:
            fail(400, f"{dim} percentages add up to {total:.1f}%, more than 100%")
    captured = body.captured_at or now_utc()
    with transaction.atomic():
        PostAudience.objects.filter(post=p).delete()
        PostAudience.objects.bulk_create(
            [PostAudience(post=p, dimension=r.dimension, value=r.value, pct=r.pct, captured_at=captured) for r in body.rows]
        )
    return Response(post_out(_get_post(post_id, user)))


@api_view(["GET"])
def classification(request, post_id: int):
    p = _get_post(post_id, request.user)
    checkpoint = choice_param(request, "checkpoint", CHECKPOINT_Q, "24h")
    metric = request.query_params.get("metric", "impressions")
    if metric not in analytics.ALL_METRICS:
        fail(400, f"Unknown metric '{metric}'")
    labels = analytics.classifications(analytics.load_posts(p.account_id), checkpoint, metric)
    return Response(labels.get(post_id) or {"label": analytics.INSUFFICIENT, "baseline": "no snapshot at checkpoint"})


# Formats are validated by the PostIn schema; kept here for reference by the admin
__all__ = ["posts", "post_detail", "snapshot", "audience", "classification", "FORMATS"]

"""Publishing queue: draft -> approved -> published (or failed / missed)."""

import re
import uuid
from typing import Any

from django.http import FileResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.api.errors import NO_CONTENT, fail
from core.api.params import int_param, parse
from core.auth.permissions import allowed_account_ids, check_account, require
from core.common.timeutil import as_utc, now_utc, slot_label, to_uae
from core.conf import UPLOAD_DIR
from core.models import (
    AUTO_PUBLISH_FORMATS,
    PLANNED_FORMATS,
    Account,
    LinkedInConnection,
    PlannedPost,
    Post,
)
from core.schemas.common import normalise_hashtags
from core.schemas.planner import MarkPostedIn, PlannedPostIn
from core.services import publishing as publisher

EDITABLE = {"draft", "approved", "failed", "missed"}  # saving an approved post sends it back for approval
IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
# Files kept for review before posting by hand: format -> (allowed types, max size, label)
MEDIA_TYPES = {
    "carousel": ({"application/pdf": ".pdf"}, 100 * 1024 * 1024, "a PDF up to 100 MB"),
    "video": ({"video/mp4": ".mp4", "video/quicktime": ".mov"}, 200 * 1024 * 1024, "an MP4 or MOV video up to 200 MB"),
}


def _fields(body: PlannedPostIn) -> dict[str, Any]:
    data = body.model_dump(exclude={"details"})
    data["details"] = body.stored_details()
    return data


def _out(p: PlannedPost) -> dict[str, Any]:
    sched = as_utc(p.scheduled_at) if p.scheduled_at else None
    return {
        "id": p.id,
        "ref": p.ref,
        "account_id": p.account_id,
        "format": p.format,
        # Carousel, video, article and poll posts are posted by hand, then marked as posted
        "manual": p.format not in AUTO_PUBLISH_FORMATS,
        # Posted by hand: a hand-posted format, or an account the app can't post to (no LinkedIn connection,
        # e.g. the company page until LinkedIn grants page posting). At its time the team is reminded instead.
        "by_hand": p.format not in AUTO_PUBLISH_FORMATS or not LinkedInConnection.objects.filter(account_id=p.account_id).exists(),
        "details": p.details or {},
        "has_media": bool(p.media_file),
        "media_name": p.media_name,
        "caption": p.caption,
        "has_image": bool(p.image_file),
        "image_alt": p.image_alt,
        "visibility": p.visibility,
        "scheduled_at": sched.isoformat() if sched else None,
        "scheduled_at_uae": to_uae(sched).strftime("%Y-%m-%d %H:%M") if sched else None,
        "scheduled_day_uae": to_uae(sched).strftime("%A") if sched else None,
        "scheduled_slot_uae": slot_label(to_uae(sched)) if sched else None,
        "status": p.status,
        "goal": p.goal,
        "topic": p.topic,
        "industry": p.industry,
        "cta": p.cta,
        "keywords": p.keywords or [],
        "approved_at": as_utc(p.approved_at).isoformat() if p.approved_at else None,
        "published_at": as_utc(p.published_at).isoformat() if p.published_at else None,
        "linkedin_urn": p.linkedin_urn,
        "post_id": p.post_id,
        "error": p.error,
        # LinkedIn busy: when the next automatic try (approved) or a manual retry (failed) makes sense
        "retry_at": as_utc(p.retry_at).isoformat() if p.retry_at and as_utc(p.retry_at) > now_utc() else None,
        "attempts": p.attempts,
    }


def _get(planned_id: int, user) -> PlannedPost:
    p = PlannedPost.objects.filter(id=planned_id).first()
    if not p or p.account_id not in allowed_account_ids(user):
        fail(404, "Planned post not found")
    return p


def _reset_retry(p: PlannedPost) -> None:
    """A human acted: start the busy back-off afresh, but keep a waiting time that hasn't passed yet."""
    p.attempts = 0
    if p.retry_at and as_utc(p.retry_at) <= now_utc():
        p.retry_at = None


def _wait_text(p: PlannedPost) -> str:
    mins = max(1, -(-int((as_utc(p.retry_at) - now_utc()).total_seconds()) // 60))  # round up
    return f"about {mins} minute{'s' if mins != 1 else ''} (after {to_uae(p.retry_at).strftime('%H:%M')} UAE time)"


def _clear_approval(p: PlannedPost) -> None:
    p.status = "draft"  # any change needs fresh approval
    p.approved_at = None
    _reset_retry(p)


@api_view(["GET", "POST"])
def planned(request):
    user = request.user
    if request.method == "POST":
        require(user, "editor")
        body = parse(PlannedPostIn, request.data)
        if not Account.objects.filter(id=body.account_id).exists():
            fail(404, "Account not found")
        check_account(user, body.account_id)
        return Response(_out(PlannedPost.objects.create(**_fields(body), status="draft")), status=201)

    account_id = int_param(request, "account_id", required=True)
    check_account(user, account_id)
    rows = list(PlannedPost.objects.filter(account_id=account_id))

    # Upcoming first (by schedule), then unscheduled drafts, then history newest first
    def key(p: PlannedPost):
        active = p.status in {"draft", "approved", "publishing", "failed", "missed"}
        when = as_utc(p.scheduled_at or p.published_at or p.created_at)
        return (0 if active else 1, when.timestamp() if active else -when.timestamp())

    return Response([_out(p) for p in sorted(rows, key=key)])


@api_view(["PUT", "DELETE"])
def planned_detail(request, planned_id: int):
    user = request.user
    require(user, "editor")
    p = _get(planned_id, user)
    if request.method == "DELETE":
        if p.status == "publishing":
            fail(409, "This post is being published right now")
        for name in (p.image_file, p.media_file):
            if name:
                (UPLOAD_DIR / name).unlink(missing_ok=True)
        p.delete()
        return Response(status=NO_CONTENT)

    body = parse(PlannedPostIn, request.data)
    check_account(user, body.account_id)
    if p.status not in EDITABLE:
        fail(409, f"A post that is '{p.status}' can't be edited.")
    for k, v in _fields(body).items():
        setattr(p, k, v)
    # Files that don't belong to the new format are removed, so they can't be posted by mistake
    if p.format != "image" and p.image_file:
        (UPLOAD_DIR / p.image_file).unlink(missing_ok=True)
        p.image_file = None
    if p.format not in MEDIA_TYPES and p.media_file:
        (UPLOAD_DIR / p.media_file).unlink(missing_ok=True)
        p.media_file = p.media_name = None
    _clear_approval(p)
    p.error = None
    p.save()
    return Response(_out(p))


@api_view(["GET", "POST", "DELETE"])
def planned_image(request, planned_id: int):
    user = request.user
    p = _get(planned_id, user)
    if request.method == "GET":
        if not p.image_file or not (UPLOAD_DIR / p.image_file).exists():
            fail(404, "No image")
        return FileResponse(open(UPLOAD_DIR / p.image_file, "rb"))

    require(user, "editor")
    if p.status not in EDITABLE:
        fail(409, "Un-approve the post before changing its image")
    if request.method == "DELETE":
        if p.image_file:
            (UPLOAD_DIR / p.image_file).unlink(missing_ok=True)
        p.image_file = None
        _clear_approval(p)
        p.save()
        return Response(_out(p))

    if p.format != "image":
        fail(400, "Only image posts take an image")
    upload = request.FILES.get("file")
    if upload is None:
        fail(422, "Attach an image")
    ext = IMAGE_TYPES.get(upload.content_type or "")
    if not ext:
        fail(400, "Use a JPG, PNG or GIF image")
    if upload.size > MAX_IMAGE_BYTES:
        fail(400, "Image is larger than 10 MB")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    if p.image_file:
        (UPLOAD_DIR / p.image_file).unlink(missing_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    with open(UPLOAD_DIR / name, "wb") as f:
        for chunk in upload.chunks():
            f.write(chunk)
    p.image_file = name
    _clear_approval(p)
    p.save()
    return Response(_out(p))


@api_view(["GET", "POST", "DELETE"])
def planned_media(request, planned_id: int):
    """The carousel PDF or video, kept so the team can review it before someone posts it by hand."""
    user = request.user
    p = _get(planned_id, user)
    if request.method == "GET":
        if not p.media_file or not (UPLOAD_DIR / p.media_file).exists():
            fail(404, "No file")
        return FileResponse(open(UPLOAD_DIR / p.media_file, "rb"), filename=p.media_name or p.media_file)

    require(user, "editor")
    if p.status not in EDITABLE:
        fail(409, "Un-approve the post before changing its file")
    if request.method == "DELETE":
        if p.media_file:
            (UPLOAD_DIR / p.media_file).unlink(missing_ok=True)
        p.media_file = p.media_name = None
        _clear_approval(p)
        p.save()
        return Response(_out(p))

    rule = MEDIA_TYPES.get(p.format)
    if rule is None:
        fail(400, "Only carousel and video posts take a file")
    types, max_bytes, label = rule
    upload = request.FILES.get("file")
    if upload is None:
        fail(422, "Attach a file")
    ext = types.get(upload.content_type or "")
    if not ext:
        fail(400, f"Use {label}")
    if upload.size > max_bytes:
        fail(400, f"The file is too large: use {label}")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    if p.media_file:
        (UPLOAD_DIR / p.media_file).unlink(missing_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    with open(UPLOAD_DIR / name, "wb") as f:
        for chunk in upload.chunks():
            f.write(chunk)
    p.media_file, p.media_name = name, (upload.name or name)[:300]
    _clear_approval(p)
    p.save()
    return Response(_out(p))


@api_view(["POST"])
def mark_posted(request, planned_id: int):
    """After an approved post was put on LinkedIn by hand: record it, and start tracking it with the right format."""
    require(request.user, "editor")
    p = _get(planned_id, request.user)
    if p.status != "approved":
        fail(409, "Publish it first (preview → Publish copies the text), then mark it as posted")
    body = parse(MarkPostedIn, request.data)
    m = re.search(r"activity[:-](\d{10,})", body.post_url)
    if "linkedin.com" not in body.post_url or not m:
        fail(400, "Paste the LinkedIn link of the post (open the post on LinkedIn and copy its address)")
    activity = m.group(1)
    url = f"https://www.linkedin.com/feed/update/urn:li:activity:{activity}"
    published = now_utc()
    # The same post may already be tracked (e.g. from a LinkedIn export): link it instead of adding it twice
    post = Post.objects.filter(post_url=url).first() or Post.objects.filter(account_id=p.account_id, linkedin_post_id=activity).first()
    if post is None:
        post = Post.objects.create(
            ref=p.ref,  # same ID as the draft
            account_id=p.account_id,
            post_url=url,
            linkedin_post_id=activity,
            author=p.account.name,
            published_at=published,
            format=PLANNED_FORMATS[p.format],
            goal=p.goal,
            topic=p.topic,
            industry=p.industry,
            keywords=p.keywords or [],
            cta=p.cta,
            hashtags=normalise_hashtags(re.findall(r"#(\w+)", p.caption)),
            caption=p.caption,
            notes="Posted by hand from the app's publishing queue",
        )
    elif post.account_id != p.account_id:
        fail(409, "That LinkedIn post is already tracked under another account")
    elif post.ref != p.ref:
        # Already tracked (e.g. from a LinkedIn export): it takes the draft's ID, so the post keeps one ID
        post.ref = p.ref
        post.save(update_fields=["ref"])
    p.status = "published"
    p.published_at = post.published_at or published
    p.linkedin_urn = f"urn:li:activity:{activity}"
    p.post = post
    p.error = None
    p.retry_at = None
    p.save()
    return Response(_out(p))


@api_view(["POST"])
def approve(request, planned_id: int):
    require(request.user, "editor")
    p = _get(planned_id, request.user)
    if p.status not in EDITABLE:
        fail(409, f"A post that is '{p.status}' can't be published")
    # "approved" = scheduled: the app publishes it at its time. Publishing straight away ("now") doesn't need a future time.
    if p.scheduled_at and as_utc(p.scheduled_at) <= now_utc() and not request.data.get("now"):
        fail(400, "The scheduled time has already passed. Pick a new time, or use Publish now.")
    if request.data.get("now"):
        p.scheduled_at = now_utc()  # going out now, not at the planned time
    p.status = "approved"
    p.approved_at = now_utc()
    p.error = None
    _reset_retry(p)
    p.save()
    return Response(_out(p))


@api_view(["POST"])
def unapprove(request, planned_id: int):
    require(request.user, "editor")
    p = _get(planned_id, request.user)
    if p.status != "approved":
        fail(409, f"A post that is '{p.status}' isn't scheduled")
    _clear_approval(p)
    p.save()
    return Response(_out(p))


@api_view(["POST"])
def publish_now(request, planned_id: int):
    """Publishes immediately. The post must already be approved."""
    require(request.user, "editor")
    p = _get(planned_id, request.user)
    if p.format not in AUTO_PUBLISH_FORMATS:
        fail(409, "The app can't publish this format yet. Post it on LinkedIn by hand, then use Mark as posted.")
    if p.retry_at and as_utc(p.retry_at) > now_utc():
        # Not an error: LinkedIn asked us to wait. Hammering it would only extend the wait.
        fail(409, f"LinkedIn is busy right now. Please try again in {_wait_text(p)}.")
    try:
        p = publisher.publish(planned_id)
    except ValueError as e:
        fail(409, str(e))
    return Response(_out(p))

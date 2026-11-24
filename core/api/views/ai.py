"""Claude endpoints: generate and read strategy ideas, turn a post idea into a draft."""

import json

from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.api.errors import fail
from core.api.params import int_param, parse
from core.auth.permissions import check_account, require
from core.common.timeutil import as_utc
from core.integrations import claude
from core.models import Account, AIRun, PlannedPost
from core.schemas.ai import ComparePostsIn, GenerateIn, PostAssistIn, PostChatIn
from core.services.ai import chat as ai_chat
from core.services.ai import compare as ai_compare
from core.services.ai import ideas as ai_ideas
from core.services.ai import post_assist as ai_assist


def _run_out(r: AIRun) -> dict:
    return {
        "id": r.id,
        "account_id": r.account_id,
        "focus": r.focus,
        "status": r.status,
        "model": r.model,
        "input_tokens": r.input_tokens,
        "output_tokens": r.output_tokens,
        "cost_usd": float(r.cost_usd),
        "result": r.result,
        "error": r.error,
        "created_by": r.created_by,
        "created_at": as_utc(r.created_at).isoformat(),
    }


@api_view(["GET", "POST"])
def ideas(request):
    user = request.user
    if request.method == "GET":
        account_id = int_param(request, "account_id", required=True)
        check_account(user, account_id)
        latest = AIRun.objects.filter(account_id=account_id, kind="ideas", status="ok").first()
        return Response({
            "configured": claude.configured(),
            "latest": _run_out(latest) if latest else None,
            "runs_today": ai_ideas.runs_today(Account(id=account_id)),
            "running": ai_ideas.running(Account(id=account_id)) is not None,  # someone else is generating right now
            "daily_limit": ai_ideas.DAILY_RUN_LIMIT,
        })

    require(user, "editor")  # generating costs money: editors and above
    body = parse(GenerateIn, request.data)
    account = Account.objects.filter(id=body.account_id).first()
    if not account:
        fail(404, "Account not found")
    check_account(user, account.id)
    focus = (body.focus or "").strip() or None
    try:
        run = ai_ideas.generate_ideas(account, focus, None if user.dev else user.email)
    except claude.AIError as e:
        fail(400, str(e))
    return Response(_run_out(run), status=201)


@api_view(["POST"])
def idea_to_draft(request, run_id: int, index: int):
    """Create a Publishing draft from a post idea's caption (it still needs approval)."""
    user = request.user
    require(user, "editor")
    run = AIRun.objects.filter(id=run_id, status="ok").first()
    if not run:
        fail(404, "Ideas not found")
    check_account(user, run.account_id)
    items = (run.result or {}).get("ideas", [])
    if not 0 <= index < len(items):
        fail(404, "Idea not found")
    idea = items[index]
    caption = (idea.get("draft_caption") or "").strip()
    if not caption:
        fail(400, "This idea has no draft caption")
    goal = {"leads": "sales", "sales": "sales", "brand": "brand"}.get(idea.get("type") or "", "engagement")  # Leads isn't a post goal: it counts as Sales
    p = PlannedPost.objects.create(
        account_id=run.account_id,
        caption=caption[:3000],
        topic=(idea.get("title") or "")[:200] or None,
        goal=goal,
        status="draft",
    )
    return Response({"planned_id": p.id}, status=201)


@api_view(["GET", "POST"])
def post_assist(request):
    """GET: is Claude connected, and how many analyses are left today. POST: analyse a draft (only on click)."""
    user = request.user
    if request.method == "GET":
        account_id = int_param(request, "account_id", required=True)
        check_account(user, account_id)
        return Response({
            "configured": claude.configured(),
            "runs_today": ai_assist.post_assist_runs_today(Account(id=account_id)),
            "daily_limit": ai_assist.POST_ASSIST_DAILY_LIMIT,
        })
    require(user, "editor")  # costs money: editors and above
    body = parse(PostAssistIn, _form_data(request, ("focus", "details")))
    account = Account.objects.filter(id=body.account_id).first()
    if not account:
        fail(404, "Account not found")
    check_account(user, account.id)
    draft = body.model_dump(include={"format", "caption", "topic", "industry", "cta", "goal", "scheduled_at", "details", "media_attached"})
    try:
        attachment = _attachment(request)
        run = ai_assist.post_assist(account, draft, (body.instructions or "").strip() or None, None if user.dev else user.email, attachment, list(dict.fromkeys(body.focus)))
    except claude.AIError as e:
        fail(400, str(e))
    return Response(_run_out(run), status=201)


@api_view(["GET", "POST"])
def post_chat(request):
    """GET: is Claude connected, messages left today. POST: one chat turn (only when someone clicks Start or sends)."""
    user = request.user
    if request.method == "GET":
        account_id = int_param(request, "account_id", required=True)
        check_account(user, account_id)
        return Response({
            "configured": claude.configured(),
            "messages_today": ai_chat.post_chat_messages_today(Account(id=account_id)),
            "daily_limit": ai_chat.POST_CHAT_DAILY_LIMIT,
            "session_limit": ai_chat.POST_CHAT_MAX_MESSAGES,
        })
    require(user, "editor")  # costs money: editors and above
    body = parse(PostChatIn, _form_data(request, json_fields=("messages",)))
    account = Account.objects.filter(id=body.account_id).first()
    if not account:
        fail(404, "Account not found")
    check_account(user, account.id)
    draft = body.model_dump(include={"format", "caption", "topic", "industry", "cta", "goal"})
    history = [m.model_dump() for m in body.messages]
    try:
        attachment = _attachment(request)
        run = ai_chat.post_chat(account, draft, history, None if user.dev else user.email, attachment, body.web_search)
    except claude.AIError as e:
        fail(400, str(e))
    return Response(_run_out(run), status=201)


def _form_data(request, json_fields: tuple[str, ...] = ()) -> dict:
    """JSON body as is; a multipart body (sent when a file is attached) as plain fields, with JSON-encoded lists decoded."""
    if not request.content_type.startswith("multipart/"):
        return request.data
    data = {k: request.data.get(k) for k in request.data if k != "attachment"}
    for k in json_fields:
        if data.get(k):
            try:
                data[k] = json.loads(data[k])
            except ValueError:
                fail(422, f"{k} must be JSON")
    return {k: v for k, v in data.items() if v not in (None, "")}


def _attachment(request) -> dict | None:
    """The post's image or carousel PDF, if the page sent one (raises AIError for unreadable files)."""
    upload = request.FILES.get("attachment")
    return ai_assist.read_attachment(upload) if upload else None


@api_view(["POST"])
def compare_posts(request):
    """Compare posts → Ask AI why (only on click)."""
    from statistics import median

    from core.common.timeutil import slot_label, to_uae
    from core.models import Post, Snapshot

    user = request.user
    require(user, "editor")
    body = parse(ComparePostsIn, request.data)
    account = Account.objects.filter(id=body.account_id).first()
    if not account:
        fail(404, "Account not found")
    check_account(user, account.id)
    posts = list(Post.objects.filter(id__in=body.post_ids, account=account))
    if len(posts) != len(set(body.post_ids)):
        fail(404, "Some of these posts weren't found in this account")
    snaps = {s.post_id: s for s in Snapshot.objects.filter(post__in=posts, checkpoint=body.checkpoint)}
    peers = [s.impressions for s in Snapshot.objects.filter(post__account=account, checkpoint=body.checkpoint, impressions__isnull=False)]
    typical = median(peers) if len(peers) >= 5 else None
    data = []
    for p in posts:
        s = snaps.get(p.id)
        local = to_uae(as_utc(p.published_at))
        data.append({
            "id": p.ref or f"Post {p.id}",
            "posted_uae": local.strftime("%A %Y-%m-%d %H:%M") if p.time_known else local.strftime("%A %Y-%m-%d (time unknown)"),
            "slot_uae": slot_label(local) if p.time_known else None,
            "format": p.format,
            "topic": p.topic,
            "goal": p.goal,
            "hashtags": p.hashtags,
            "targeted": p.targeted,
            "numbers": {k: getattr(s, k) for k in ("impressions", "members_reached", "clicks", "reactions", "comments", "reposts", "followers_gained", "video_views")} if s else None,
            "caption": (p.caption or "")[:3000],
        })
    try:
        run = ai_compare.compare_posts(account, data, body.checkpoint, typical, None if user.dev else user.email)
    except claude.AIError as e:
        fail(400, str(e))
    return Response(_run_out(run), status=201)

"""Publishes approved planned posts to LinkedIn and records them as tracked posts.

Safety rules:
- Only status 'approved' is ever published (marketing team keeps final approval).
- A post is claimed atomically (approved -> publishing) so it can never be sent twice,
  even if "Publish now" and the scheduler fire at the same moment.
- A scheduled post found more than PUBLISH_GRACE_MINUTES late (e.g. the scheduler was off)
  is marked 'missed', not published at the wrong time.
- If LinkedIn might have accepted the post before an error, the error says so, so nobody
  re-publishes blindly and creates a duplicate.

LinkedIn busy (many people using it: HTTP 429 / 503, or LinkedIn unreachable):
- Nothing was posted, so the post goes back to 'approved' with a waiting time (retry_at).
  The scheduler tries again automatically after the wait, backing off 2, 5, 10, 20, 30 minutes
  (or longer if LinkedIn's Retry-After says so). After MAX_BUSY_ATTEMPTS it stops and asks
  the team to try again later; nothing is ever posted twice.
- If LinkedIn was overloaded in a way where the post MAY have gone through (timeout, 500/502/504
  after sending), it is not retried automatically: the team is told to check the profile after a
  short wait, then retry only if the post isn't there.
"""

import logging
import re
from datetime import datetime, timedelta

import httpx
from django.db.models import Q

from core.common.crypto import TokenKeyError, decrypt
from core.common.timeutil import as_utc, now_utc
from core.conf import PUBLISH_GRACE_MINUTES, UPLOAD_DIR
from core.integrations.linkedin import member_client as li
from core.models import AUTO_PUBLISH_FORMATS, LinkedInConnection, PlannedPost, Post
from core.schemas.common import normalise_hashtags

log = logging.getLogger("publisher")

BACKOFF_MINUTES = [2, 5, 10, 20, 30]  # waits between automatic tries while LinkedIn is busy
MAX_BUSY_ATTEMPTS = len(BACKOFF_MINUTES) + 1  # tries in total before handing back to the team (~67 min)
GIVE_UP_WAIT_MINUTES = 30  # suggested wait after the automatic tries run out
CHECK_WAIT_MINUTES = 5  # wait before checking the profile when the outcome is uncertain
MAX_WAIT = timedelta(hours=6)


def _claim(planned_id: int) -> bool:
    return PlannedPost.objects.filter(id=planned_id, status="approved").update(status="publishing", error=None) == 1


def _fail(p: PlannedPost, msg: str) -> PlannedPost:
    p.status = "failed"
    p.error = msg
    p.retry_at = None
    p.attempts = 0
    p.save(update_fields=["status", "error", "retry_at", "attempts", "updated_at"])
    return p


def wait_for(attempts: int, retry_after: int | None) -> timedelta:
    """Wait before the next try: our back-off, or longer if LinkedIn asked for it (1 min to 6 h)."""
    base = timedelta(minutes=BACKOFF_MINUTES[min(attempts - 1, len(BACKOFF_MINUTES) - 1)])
    asked = timedelta(seconds=retry_after or 0)
    return min(max(base, asked, timedelta(minutes=1)), MAX_WAIT)


def next_limit_reset(now) -> datetime:
    """LinkedIn's daily API limits reset at midnight UTC (04:00 UAE). A few minutes' margin."""
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight + timedelta(minutes=5)


def _busy(p: PlannedPost, reason: str, retry_after: int | None = None, throttled: bool = False) -> PlannedPost:
    """LinkedIn is busy and nothing was posted: wait and try again automatically.
    throttled: LinkedIn answered 429 (rate limit) rather than being down."""
    p.attempts += 1
    now = now_utc()
    if p.attempts >= MAX_BUSY_ATTEMPTS:
        p.status = "failed"
        wait = max(timedelta(minutes=GIVE_UP_WAIT_MINUTES), min(timedelta(seconds=retry_after or 0), timedelta(days=1)))
        if throttled and not retry_after:
            # An hour of 429s almost always means a DAILY limit: retrying before the reset is pointless
            p.retry_at = max(now + wait, next_limit_reset(now))
            p.error = (
                f"LinkedIn kept limiting requests through {MAX_BUSY_ATTEMPTS} tries, which usually means its daily limit was reached. "
                "Nothing was posted. LinkedIn's daily limits reset at midnight UTC (04:00 UAE), so the app paused until then. "
                "After the waiting time, approve it again, then Publish now or pick a new time."
            )
        else:
            p.retry_at = now + wait
            p.error = (
                f"{reason} Nothing was posted. LinkedIn stayed busy through {MAX_BUSY_ATTEMPTS} tries, so the app paused. "
                "Please try again after the waiting time: approve it again, then Publish now or pick a new time."
            )
    else:
        p.status = "approved"  # still approved: the scheduler picks it up after the wait
        p.retry_at = now + wait_for(p.attempts, retry_after)
        p.error = f"{reason} Nothing was posted. The app will try again automatically after the waiting time."
    p.save(update_fields=["status", "error", "retry_at", "attempts", "updated_at"])
    log.info("LinkedIn busy for planned post %s (try %s); next at %s", p.id, p.attempts, p.retry_at)
    return p


def _uncertain(p: PlannedPost, reason: str) -> PlannedPost:
    """LinkedIn may have accepted the post: never retry blindly (a duplicate post looks bad)."""
    p.status = "failed"
    p.retry_at = now_utc() + timedelta(minutes=CHECK_WAIT_MINUTES)
    p.attempts = 0
    p.error = (
        f"{reason} The post may or may not be live. After the waiting time, check the LinkedIn profile: "
        "if the post is there, delete this entry; if not, approve it again and publish."
    )
    p.save(update_fields=["status", "error", "retry_at", "attempts", "updated_at"])
    return p


BUSY_MSG = "LinkedIn is busy right now (a lot of people are using it)."
UNREACHABLE_MSG = "LinkedIn couldn't be reached just now."


def publish(planned_id: int) -> PlannedPost:
    """Publish one approved planned post. Returns the updated row (published or failed).
    Raises ValueError if the post isn't in 'approved' state."""
    if not _claim(planned_id):
        p = PlannedPost.objects.filter(id=planned_id).first()
        raise ValueError(f"Post is '{p.status if p else 'missing'}', only approved posts can be published")
    p = PlannedPost.objects.get(id=planned_id)
    if p.format not in AUTO_PUBLISH_FORMATS:
        return _fail(p, "The app can't publish this format yet. Post it on LinkedIn by hand, then use Mark as posted.")

    conn = LinkedInConnection.objects.filter(account_id=p.account_id).first()
    if conn is None:
        return _fail(p, "No LinkedIn profile is connected to this account. Connect one on the LinkedIn page.")
    if as_utc(conn.expires_at) <= now_utc():
        return _fail(p, "The LinkedIn connection has expired. Reconnect on the LinkedIn page, then retry.")
    try:
        token = decrypt(conn.access_token_enc)
    except TokenKeyError as e:
        return _fail(p, str(e))

    # Image upload happens first; nothing is public until create_post succeeds
    image_urn = None
    try:
        if p.format == "image" and p.image_file:
            image_urn = li.upload_image(token, conn.member_urn, (UPLOAD_DIR / p.image_file).read_bytes())
    except li.LinkedInBusy as e:
        return _busy(p, BUSY_MSG, e.retry_after, e.status == 429)  # an uploaded image is never public on its own
    except httpx.HTTPError:
        return _busy(p, UNREACHABLE_MSG)
    except (li.LinkedInError, OSError) as e:
        return _fail(p, f"Image upload failed, nothing was posted. {e}")

    try:
        urn = li.create_post(token, conn.member_urn, p.caption, p.visibility, image_urn, p.image_alt)
    except li.LinkedInBusy as e:
        if e.not_processed:  # 429 / 503: LinkedIn did not handle the request
            return _busy(p, BUSY_MSG, e.retry_after, e.status == 429)
        return _uncertain(p, f"LinkedIn was overloaded while posting (HTTP {e.status}).")
    except li.LinkedInError as e:
        return _fail(p, f"LinkedIn rejected the post, nothing was posted. {e.message} (HTTP {e.status})")
    except (httpx.ConnectError, httpx.ConnectTimeout):
        # The request never reached LinkedIn, so nothing can have been posted
        return _busy(p, UNREACHABLE_MSG)
    except httpx.HTTPError:
        # Timeout / dropped connection after sending: the post may or may not exist
        return _uncertain(p, "LinkedIn was too slow to confirm the post.")

    published = now_utc()
    post = Post.objects.create(
        ref=p.ref,  # same ID as the draft
        account_id=p.account_id,
        post_url=li.post_url(urn),
        linkedin_post_id=urn,
        author=conn.name,
        published_at=published,
        format="image" if p.format == "image" and p.image_file else "text",
        goal=p.goal,
        topic=p.topic,
        industry=p.industry,
        keywords=p.keywords or [],
        cta=p.cta,
        hashtags=normalise_hashtags(re.findall(r"#(\w+)", p.caption)),
        caption=p.caption,
        notes="Published from the app",
    )
    p.status = "published"
    p.published_at = published
    p.linkedin_urn = urn
    p.post = post
    p.error = None
    p.retry_at = None
    p.attempts = 0
    p.save()
    return p


def run_due() -> None:
    now = now_utc()
    not_waiting = Q(retry_at__isnull=True) | Q(retry_at__lte=now)
    # Due by schedule, or a busy retry whose waiting time is over (including busy "Publish now" posts)
    # Hand-posted formats (carousel, video, article, poll) are never picked up: their date is for planning only.
    # Nor are accounts the app can't post to (no LinkedIn connection): the team is reminded to post those by hand.
    due = PlannedPost.objects.filter(
        Q(status="approved") & Q(format__in=AUTO_PUBLISH_FORMATS) & Q(account__linkedin_connection__isnull=False) & not_waiting
        & (Q(scheduled_at__lte=now) | Q(attempts__gt=0))
    )
    for p in due:
        if p.attempts == 0 and now - as_utc(p.scheduled_at) > timedelta(minutes=PUBLISH_GRACE_MINUTES):
            p.status = "missed"
            p.error = (
                f"Not published: the scheduler wasn't running at the scheduled time and it is now more than "
                f"{PUBLISH_GRACE_MINUTES} minutes late. Reschedule it."
            )
            p.save(update_fields=["status", "error", "updated_at"])
            continue
        try:
            publish(p.id)
        except ValueError:
            pass  # claimed by "Publish now" in the meantime

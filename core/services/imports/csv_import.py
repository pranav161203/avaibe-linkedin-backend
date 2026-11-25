"""CSV import of posts and snapshots (the app's own template). LinkedIn's export files are in linkedin_export.py."""

from datetime import datetime

from core.common.timeutil import now_utc
from core.models import (
    CHECKPOINT_HOURS,
    Post,
    Snapshot,
)
from core.schemas.posts import METRIC_FIELDS, PostIn, SnapshotIn

POST_COLUMNS = ["post_url", "published_at_uae", "format", "topic", "industry", "keywords", "cta", "hashtags", "author", "caption"]

SNAPSHOT_COLUMNS = ["checkpoint", "captured_at_uae"] + METRIC_FIELDS

TEMPLATE_COLUMNS = POST_COLUMNS + SNAPSHOT_COLUMNS

def _split(v: str, on_spaces: bool = False) -> list[str]:
    """Split on ';' or ','. Hashtags may also be space-separated; keywords may not
    (a keyword such as 'inventory management' contains a space)."""
    v = v.replace(",", ";")
    if on_spaces:
        v = v.replace(" ", ";")
    return [x.strip() for x in v.split(";") if x.strip()]

def _int(v: str | None) -> int | None:
    v = (v or "").strip().replace(",", "")
    return int(float(v)) if v else None

def _dt(v: str) -> datetime:
    v = v.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            pass
    raise ValueError(f"Unrecognised date '{v}'. Use YYYY-MM-DD HH:MM (UAE time).")

def import_row(row: dict, account_id: int) -> tuple[str, bool]:
    """Returns ('created'|'updated', snapshot_saved). Raises ValueError/ValidationError/KeyError on bad rows."""
    post_in = PostIn(
        account_id=account_id,
        post_url=row.get("post_url") or None,
        published_at=_dt(row["published_at_uae"]),
        format=row["format"].strip().lower(),
        topic=row.get("topic"),
        industry=row.get("industry"),
        keywords=_split(row.get("keywords", "")),
        cta=row.get("cta"),
        hashtags=_split(row.get("hashtags", ""), on_spaces=True),
        author=row.get("author"),
        caption=row.get("caption") or None,
    )
    post = Post.objects.filter(post_url=post_in.post_url).first() if post_in.post_url else None
    if post and post.account_id != account_id:
        raise ValueError("This post URL belongs to a different account")
    data = post_in.model_dump()
    data["time_known"] = True  # the CSV template always carries a time
    if post is None:
        post = Post.objects.create(**data)
        outcome = "created"
    else:
        for k, v in data.items():
            setattr(post, k, v)
        post.save()
        outcome = "updated"

    cp = row.get("checkpoint", "").strip()
    if not cp:
        return outcome, False
    if cp not in CHECKPOINT_HOURS:
        raise ValueError(f"checkpoint must be one of {list(CHECKPOINT_HOURS)}")
    snap_in = SnapshotIn(
        captured_at=_dt(row["captured_at_uae"]) if row.get("captured_at_uae") else None,
        **{f: _int(row.get(f)) for f in METRIC_FIELDS},
    )
    data = snap_in.model_dump()
    data["captured_at"] = data["captured_at"] or now_utc()
    Snapshot.objects.update_or_create(post=post, checkpoint=cp, defaults=data)
    return outcome, True

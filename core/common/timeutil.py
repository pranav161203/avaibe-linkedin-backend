"""Time-zone helpers. Everything is stored in UTC; UAE time is the reporting
time zone and India time is kept as a secondary reference."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

UAE = ZoneInfo("Asia/Dubai")
IST = ZoneInfo("Asia/Kolkata")

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# (start hour, end hour, label) in UAE time, as defined in the assignment brief
SLOTS = [
    (8, 10, "8-10 AM"),
    (10, 12, "10 AM-12 PM"),
    (12, 14, "12-2 PM"),
    (14, 16, "2-4 PM"),
    (16, 18, "4-6 PM"),
    (18, 20, "6-8 PM"),
]
OUTSIDE_SLOT = "Outside 8 AM-8 PM"
SLOT_LABELS = [s[2] for s in SLOTS] + [OUTSIDE_SLOT]


def as_utc(dt: datetime | None) -> datetime | None:
    """Normalise a datetime to aware UTC. Naive values are assumed to be UTC
    (this is what the database returns on back ends without tz support)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def from_uae_local(dt: datetime) -> datetime:
    """Interpret a naive datetime as UAE wall-clock time and convert to UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UAE)
    return dt.astimezone(timezone.utc)


def to_uae(dt: datetime) -> datetime:
    return as_utc(dt).astimezone(UAE)


def to_ist(dt: datetime) -> datetime:
    return as_utc(dt).astimezone(IST)


def slot_label(uae_dt: datetime) -> str:
    for start, end, label in SLOTS:
        if start <= uae_dt.hour < end:
            return label
    return OUTSIDE_SLOT


def now_utc() -> datetime:
    return datetime.now(timezone.utc)

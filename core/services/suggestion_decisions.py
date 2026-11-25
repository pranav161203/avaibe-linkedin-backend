"""Keeping the team's suggestion decisions (Done / Later / Dismiss) from piling up.

- Later: hides a suggestion for a week; afterwards the row is removed and the suggestion shows again.
- Done: kept DONE_DAYS. After that the row goes, so if the problem still exists the suggestion comes back
  (e.g. "Post on the page this week" weeks later). If it was really fixed, the rule no longer fires anyway.
- Dismissed: kept DISMISSED_DAYS, then the suggestion may be offered again.
- Claude ideas and brand trends: only the latest run is shown, so decisions on older runs are removed.
"""

import re
from datetime import timedelta

from django.db.models import Q

from core.common.timeutil import now_utc
from core.models import AIRun, SuggestionDecision

DONE_DAYS = 90
DISMISSED_DAYS = 180
_RUN_KEY = re.compile(r"^(ai|trend):(\d+):\d+$")
_RUN_KIND = {"ai": "ideas", "trend": "trends"}


def tidy(account_id: int) -> int:
    """Remove decisions that no longer do anything for this account. Returns how many rows were removed."""
    now = now_utc()
    qs = SuggestionDecision.objects.filter(account_id=account_id)
    stale = Q(status="later", until__lte=now) | Q(status="done", updated_at__lt=now - timedelta(days=DONE_DAYS))
    stale |= Q(status="dismissed", updated_at__lt=now - timedelta(days=DISMISSED_DAYS))
    removed, _ = qs.filter(stale).delete()

    latest = {
        prefix: AIRun.objects.filter(account_id=account_id, kind=kind, status="ok").values_list("id", flat=True).first()
        for prefix, kind in _RUN_KIND.items()
    }
    old_runs = []
    for d in qs.filter(Q(key__startswith="ai:") | Q(key__startswith="trend:")).only("id", "key"):
        m = _RUN_KEY.match(d.key)
        if m and int(m.group(2)) != latest[m.group(1)]:
            old_runs.append(d.id)
    if old_runs:
        removed += SuggestionDecision.objects.filter(id__in=old_runs).delete()[0]
    return removed

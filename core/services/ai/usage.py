"""This month's Claude usage and cost, for the Settings page."""

from decimal import Decimal

from core.common.timeutil import now_utc, to_uae
from core.models import AIRun
from core.services.ai.ideas import DAILY_RUN_LIMIT


def usage_summary() -> dict:
    """This month's Claude usage across all accounts."""
    start = to_uae(now_utc()).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    qs = AIRun.objects.filter(created_at__gte=start, status__in=["ok", "error"])
    ok = qs.filter(status="ok")
    total = sum((r.cost_usd for r in ok), Decimal(0))
    return {
        "month_start_uae": start.strftime("%Y-%m-%d"),
        "runs": qs.count(),
        "failed_runs": qs.filter(status="error").count(),
        "input_tokens": sum(r.input_tokens for r in ok),
        "output_tokens": sum(r.output_tokens for r in ok),
        "estimated_cost_usd": float(round(total, 4)),
        "daily_limit_per_account": DAILY_RUN_LIMIT,
    }

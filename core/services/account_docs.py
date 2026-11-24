"""Reading the account documents other features need (e.g. competitor names for the AI)."""

from core.models import AccountDoc


def competitor_names(account_id: int) -> list[str]:
    """For Claude's context: the competitor names the team keeps on the Competitors page."""
    doc = AccountDoc.objects.filter(account_id=account_id, kind="competitors").first()
    return [c.get("name") for c in (doc.data.get("competitors", []) if doc else []) if c.get("name")]

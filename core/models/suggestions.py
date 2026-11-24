"""What the team decided about each suggestion (done, later, dismissed)."""

from django.db import models

from core.models.accounts import Account


class SuggestionDecision(models.Model):
    """The team's decision on one suggestion or Claude idea, shared by everyone on the account.

    key: "rule:<suggestion id>" for data-driven suggestions, "ai:<run id>:<index>" for Claude ideas.
    status: doing (Do it) | later (snoozed until `until`) | dismissed | done.
    """

    STATUSES = ("doing", "later", "dismissed", "done")

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="suggestion_decisions")
    key = models.CharField(max_length=120)
    status = models.CharField(max_length=20)
    until = models.DateTimeField(null=True, blank=True)
    decided_by = models.CharField(max_length=320, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "suggestion_decisions"
        constraints = [models.UniqueConstraint(fields=["account", "key"], name="uniq_decision_account_key")]

    def __str__(self) -> str:
        return f"{self.account_id} · {self.key} · {self.status}"

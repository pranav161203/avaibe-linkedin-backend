"""Claude (AI) runs: every request with its tokens and cost."""

from django.db import models

from core.models.accounts import Account


class AIRun(models.Model):
    """One Claude request (e.g. 'strategy ideas'), kept so results can be re-read without paying again,
    and so usage and cost are visible."""

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="ai_runs")
    kind = models.CharField(max_length=30, default="ideas")
    focus = models.CharField(max_length=300, null=True, blank=True)
    status = models.CharField(max_length=20, default="ok")  # ok | error
    model = models.CharField(max_length=60)
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    result = models.JSONField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)
    created_by = models.CharField(max_length=320, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "ai_runs"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.kind} · {self.account_id} · {self.created_at:%Y-%m-%d %H:%M}"

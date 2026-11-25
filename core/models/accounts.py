"""LinkedIn accounts (company page, founder profiles) and their page-level data."""

from django.db import models


class Account(models.Model):
    """A LinkedIn asset: a company page, a founder profile or a personal profile."""

    KIND_CHOICES = [("company", "Company page"), ("founder", "Founder profile"), ("personal", "Personal profile")]

    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    linkedin_url = models.CharField(max_length=500, null=True, blank=True)
    # The API's id for this asset: urn:li:organization:123 (company page) or urn:li:person:AbC (profile)
    linkedin_urn = models.CharField(max_length=100, null=True, blank=True)
    # For founder / personal profiles: the company page they belong to (shown together on the Dashboard)
    parent = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="profiles")
    # The company that owns it: only that company's people see it (super admins see every company's).
    # Empty only for rows made before companies existed and not yet assigned; only super admins see those.
    company = models.ForeignKey(
        "core.Company", on_delete=models.PROTECT, null=True, blank=True, related_name="accounts", db_column="company_id"
    )
    is_test = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts"
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.name}{' (test)' if self.is_test else ''}"




class PageAudience(models.Model):
    """Page-level follower or visitor demographics on a given date."""

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="page_audience_items")
    as_of = models.DateField(db_index=True)
    audience = models.CharField(max_length=20)  # followers | visitors
    total = models.IntegerField(null=True, blank=True)
    dimension = models.CharField(max_length=30)
    value = models.CharField(max_length=200)
    count = models.IntegerField(null=True, blank=True)
    pct = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "page_audience"
        constraints = [
            models.UniqueConstraint(fields=["account", "as_of", "audience", "dimension", "value"], name="uniq_page_audience")
        ]


class PageDaily(models.Model):
    """One day of page-level activity, from LinkedIn page analytics exports (dates are UTC, as LinkedIn
    reports them). Every metric is nullable: a file that doesn't cover a metric leaves it untouched."""

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="page_daily_items")
    date = models.DateField()
    # Content: all posts combined, counted on the day members saw them (not the day they were posted)
    impressions = models.IntegerField(null=True, blank=True)
    unique_impressions = models.IntegerField(null=True, blank=True)
    clicks = models.IntegerField(null=True, blank=True)
    reactions = models.IntegerField(null=True, blank=True)
    comments = models.IntegerField(null=True, blank=True)
    reposts = models.IntegerField(null=True, blank=True)
    # Visitors
    page_views = models.IntegerField(null=True, blank=True)
    unique_visitors = models.IntegerField(null=True, blank=True)
    # Followers
    new_followers = models.IntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "page_daily"
        constraints = [models.UniqueConstraint(fields=["account", "date"], name="uniq_page_daily")]
        ordering = ["date"]


PAGE_DAILY_FIELDS = [
    "impressions",
    "unique_impressions",
    "clicks",
    "reactions",
    "comments",
    "reposts",
    "page_views",
    "unique_visitors",
    "new_followers",
]




class AccountDoc(models.Model):
    """A small shared document per account, e.g. the brand page checklist or the competitor list.
    One row per (account, kind); the JSON is validated per kind in views/docs.py."""

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="docs")
    kind = models.CharField(max_length=40)
    data = models.JSONField(default=dict, blank=True)
    updated_by = models.CharField(max_length=320, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "account_docs"
        constraints = [models.UniqueConstraint(fields=["account", "kind"], name="uniq_doc_account_kind")]

    def __str__(self) -> str:
        return f"{self.account_id} · {self.kind}"

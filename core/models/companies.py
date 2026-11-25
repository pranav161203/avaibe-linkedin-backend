"""Companies (tenants): each one owns its LinkedIn accounts, knowledge base and team."""

from django.db import models

from core.models.base import Audited


class Company(Audited):
    """A customer organisation. Its people (users.company_id) only ever see its own accounts and data.
    Created by a super admin, who then invites the company's first admin."""

    name = models.CharField(max_length=200)
    # Short unique handle (lowercase, dashes), e.g. "avaibe"; stable even if the display name changes
    slug = models.SlugField(max_length=60, unique=True)
    website = models.URLField(max_length=300, null=True, blank=True)
    country = models.CharField(max_length=2, default="AE")  # ISO 3166-1 alpha-2
    industry = models.CharField(max_length=120, null=True, blank=True)
    # Inactive: nobody in the company can sign in (their sessions end on the next request); data is kept
    is_active = models.BooleanField(default=True)
    # The account people without "can switch accounts" are limited to
    default_account = models.ForeignKey(
        "core.Account", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_column="default_account_id"
    )

    class Meta:
        db_table = "companies"
        ordering = ["name"]
        verbose_name_plural = "companies"

    def __str__(self) -> str:
        return self.name


class CompanySetting(Audited):
    """One editable Settings section for one company: audience definitions ("segments"), performance rules
    ("performance") or the brand kit ("brand"). Stored as JSON and validated in core.services.settings_store.
    A section with no row uses the defaults."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="settings", db_column="company_id")
    section = models.CharField(max_length=30)
    value = models.JSONField()

    class Meta:
        db_table = "company_settings"
        constraints = [models.UniqueConstraint(fields=["company", "section"], name="company_setting_unique_section")]

    def __str__(self) -> str:
        return f"{self.company_id}:{self.section}"

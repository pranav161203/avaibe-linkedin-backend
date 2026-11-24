"""Leads (enquiries) and where they came from."""

from django.db import models

from core.models.accounts import Account
from core.models.posts import Post


class Lead(models.Model):
    """An enquiry or business conversation, recorded by the team (LinkedIn's API doesn't provide these).
    Business facts only: no personal names or contact details are stored."""

    SOURCES = [
        ("company_post", "Company page post"),
        ("founder_post", "Founder's post"),
        ("company_page", "Company page (visit / message)"),
        ("founder_profile", "Founder's profile / message"),
        ("website", "Website"),
        ("referral", "Referral"),
        ("event", "Event"),
        ("other", "Other"),
    ]
    STAGES = [("new", "New"), ("talking", "In talks"), ("proposal", "Proposal sent"), ("won", "Won"), ("lost", "Lost")]

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="leads")
    received_on = models.DateField()
    source = models.CharField(max_length=30, choices=SOURCES)
    # The post or profile it came from, when known
    post = models.ForeignKey(Post, on_delete=models.SET_NULL, null=True, blank=True, related_name="leads")
    via_account = models.ForeignKey(Account, on_delete=models.SET_NULL, null=True, blank=True, related_name="leads_via")
    company = models.CharField(max_length=200)
    industry = models.CharField(max_length=120, null=True, blank=True)
    in_uae = models.BooleanField(null=True, blank=True)
    role = models.CharField(max_length=120, null=True, blank=True)  # e.g. "Principal", "CTO" (no names)
    decision_maker = models.BooleanField(null=True, blank=True)
    service = models.CharField(max_length=120, null=True, blank=True)
    stage = models.CharField(max_length=20, choices=STAGES, default="new", db_index=True)
    value_aed = models.DecimalField(max_digits=12, decimal_places=0, null=True, blank=True)
    closed_on = models.DateField(null=True, blank=True)  # set when won or lost
    notes = models.TextField(null=True, blank=True)
    # Attribution: what they say ("Saw a founder's post on LMS") and the tracked link, when it came via the website
    how_heard = models.CharField(max_length=300, null=True, blank=True)
    utm_source = models.CharField(max_length=100, null=True, blank=True)
    utm_medium = models.CharField(max_length=100, null=True, blank=True)
    utm_campaign = models.CharField(max_length=100, null=True, blank=True)
    # When the team first replied (slow replies lose leads)
    replied_at = models.DateTimeField(null=True, blank=True)
    # Qualified = UAE-based decision-maker by default; set it to override
    qualified = models.BooleanField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "leads"
        ordering = ["-received_on", "-id"]

    def __str__(self) -> str:
        return f"{self.company} ({self.stage})"

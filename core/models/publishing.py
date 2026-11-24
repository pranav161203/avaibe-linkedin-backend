"""LinkedIn connections, OAuth state, and the publishing queue (planned posts)."""

from django.db import models

from core.models.accounts import Account
from core.models.choices import PLANNED_STATUSES
from core.models.posts import Post, next_post_ref


class LinkedInConnection(models.Model):
    """A LinkedIn member who authorised the app to post on their behalf (w_member_social)."""

    account = models.OneToOneField(Account, on_delete=models.CASCADE, related_name="linkedin_connection")
    member_urn = models.CharField(max_length=100)  # urn:li:person:<sub>
    name = models.CharField(max_length=200, null=True, blank=True)
    email = models.CharField(max_length=200, null=True, blank=True)
    picture_url = models.CharField(max_length=1000, null=True, blank=True)
    access_token_enc = models.TextField()  # Fernet-encrypted
    scopes = models.CharField(max_length=300, null=True, blank=True)
    expires_at = models.DateTimeField()
    connected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "linkedin_connections"


class OAuthState(models.Model):
    """One-time value tying a LinkedIn login callback to the request that started it (CSRF protection)."""

    state = models.CharField(max_length=64, primary_key=True)
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    created_at = models.DateTimeField()

    class Meta:
        db_table = "oauth_states"


class PlannedPost(models.Model):
    """A post waiting to be published. Only 'approved' posts are ever published."""

    STATUS_CHOICES = [(s, s) for s in PLANNED_STATUSES]

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="planned_items")
    # Readable ID (P-0042), kept when the post is published and tracked in Data
    ref = models.CharField(max_length=20, unique=True, null=True, blank=True)
    # text | image | carousel | video | article | poll. Only text and image can be published by the app today;
    # the others are drafted and approved here, posted by hand, then marked as posted.
    format = models.CharField(max_length=20, default="text", db_index=True)
    caption = models.TextField()
    image_file = models.CharField(max_length=300, null=True, blank=True)  # file name inside UPLOAD_DIR
    # Carousel PDF or video file for review before posting by hand (file name inside UPLOAD_DIR)
    media_file = models.CharField(max_length=300, null=True, blank=True)
    media_name = models.CharField(max_length=300, null=True, blank=True)  # original file name, for display
    # Format-specific fields, e.g. poll question/options, article title/link, carousel document title
    details = models.JSONField(default=dict, blank=True)
    image_alt = models.CharField(max_length=300, null=True, blank=True)
    visibility = models.CharField(max_length=20, default="PUBLIC")  # PUBLIC | CONNECTIONS
    scheduled_at = models.DateTimeField(null=True, blank=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft", db_index=True)
    # What the post aims for: required on Create post (older drafts may be empty until edited)
    goal = models.CharField(max_length=20, choices=[("brand", "Brand awareness"), ("sales", "Sales"), ("engagement", "Engagement")], null=True, blank=True)
    topic = models.CharField(max_length=200, null=True, blank=True)
    industry = models.CharField(max_length=200, null=True, blank=True)
    cta = models.CharField(max_length=300, null=True, blank=True)
    keywords = models.JSONField(default=list, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    linkedin_urn = models.CharField(max_length=200, null=True, blank=True)
    post = models.ForeignKey(Post, on_delete=models.SET_NULL, null=True, blank=True, related_name="planned_items")
    error = models.TextField(null=True, blank=True)
    # LinkedIn busy: when the next automatic try (approved) or a manual retry (failed) is sensible
    retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)  # busy retries so far
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "planned_posts"

    def __str__(self) -> str:
        return f"{self.status}: {self.caption[:40]}"

    def save(self, *args, **kwargs):
        if not self.ref:
            self.ref = next_post_ref()
        super().save(*args, **kwargs)

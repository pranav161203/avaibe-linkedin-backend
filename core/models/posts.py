"""Tracked posts, their performance snapshots and audience, and the shared post ID counter."""

from django.db import models

from core.models.accounts import Account
from core.models.choices import CHECKPOINT_CHOICES, FORMAT_CHOICES


class Post(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="post_items")
    # Readable ID (P-0042): the same one the post had as a draft, if it was planned in the app
    ref = models.CharField(max_length=20, unique=True, null=True, blank=True)
    post_url = models.CharField(max_length=500, unique=True, null=True, blank=True)
    linkedin_post_id = models.CharField(max_length=100, null=True, blank=True)
    author = models.CharField(max_length=200, null=True, blank=True)
    published_at = models.DateTimeField(db_index=True)
    # False when only the date is known (LinkedIn exports give no time of day). Such posts count for
    # day-of-week analysis but are kept out of the posting-time heatmap.
    time_known = models.BooleanField(default=True)
    # Audience: True = targeted to a subset (location, seniority…), False = all followers, None = unknown (manual/export)
    targeted = models.BooleanField(null=True, blank=True)
    format = models.CharField(max_length=20, choices=FORMAT_CHOICES, db_index=True)
    # What the post aims for (chosen on Create post); empty for posts from before, imports and hand-added posts
    goal = models.CharField(max_length=20, choices=[("brand", "Brand awareness"), ("sales", "Sales"), ("engagement", "Engagement")], null=True, blank=True, db_index=True)
    topic = models.CharField(max_length=200, null=True, blank=True)
    # True when the topic was guessed from the caption on import and nobody has confirmed it yet
    topic_suggested = models.BooleanField(default=False)
    industry = models.CharField(max_length=200, null=True, blank=True)
    keywords = models.JSONField(default=list, blank=True)
    cta = models.CharField(max_length=300, null=True, blank=True)
    hashtags = models.JSONField(default=list, blank=True)
    caption = models.TextField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posts"
        indexes = [models.Index(fields=["account", "published_at"])]

    def __str__(self) -> str:
        return f"{self.topic or 'Post'} · {self.published_at:%Y-%m-%d}"

    def save(self, *args, **kwargs):
        if not self.ref:
            self.ref = next_post_ref()
        super().save(*args, **kwargs)

class Snapshot(models.Model):
    """Performance of one post at one checkpoint. Metrics are nullable: "not recorded" is not zero."""

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="snapshot_items")
    checkpoint = models.CharField(max_length=4, choices=CHECKPOINT_CHOICES)
    captured_at = models.DateTimeField()

    impressions = models.IntegerField(null=True, blank=True)
    members_reached = models.IntegerField(null=True, blank=True)
    clicks = models.IntegerField(null=True, blank=True)
    reactions = models.IntegerField(null=True, blank=True)
    comments = models.IntegerField(null=True, blank=True)
    reposts = models.IntegerField(null=True, blank=True)
    video_views = models.IntegerField(null=True, blank=True)
    poll_votes = models.IntegerField(null=True, blank=True)
    newsletter_views = models.IntegerField(null=True, blank=True)
    newsletter_subscribers = models.IntegerField(null=True, blank=True)
    followers_gained = models.IntegerField(null=True, blank=True)
    # From LinkedIn's member (founder) post analytics; not available for company page posts
    saves = models.IntegerField(null=True, blank=True)
    sends = models.IntegerField(null=True, blank=True)
    profile_views = models.IntegerField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "snapshots"
        constraints = [models.UniqueConstraint(fields=["post", "checkpoint"], name="uniq_snapshot_post_checkpoint")]

    def __str__(self) -> str:
        return f"{self.post_id} @ {self.checkpoint}"


class PostAudience(models.Model):
    """One line of a post's audience breakdown, e.g. location = "Dubai, United Arab Emirates", 18 (%)."""

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="audience_items")
    dimension = models.CharField(max_length=30)
    value = models.CharField(max_length=200)
    pct = models.FloatField()  # 0-100, as shown by LinkedIn
    captured_at = models.DateTimeField()

    class Meta:
        db_table = "post_audience"
        constraints = [models.UniqueConstraint(fields=["post", "dimension", "value"], name="uniq_post_audience")]




# ---- Post IDs: one readable ID per post (P-0042), from the first draft to its numbers in Data.
# Planned posts and tracked posts draw from one counter, so an ID never means two posts.
# A post published from a draft carries the draft's ID; a post that only came from a LinkedIn import gets its own.

REF_PREFIX = "P-"


class Counter(models.Model):
    name = models.CharField(max_length=50, unique=True)
    value = models.PositiveIntegerField(default=0)


def next_post_ref() -> str:
    from django.db import transaction

    with transaction.atomic():
        c, _ = Counter.objects.select_for_update().get_or_create(name="post_ref")
        c.value += 1
        c.save(update_fields=["value"])
        return f"{REF_PREFIX}{c.value:04d}"


def assign_missing_refs() -> int:
    """Give an ID to every post that has none (rows added in bulk, e.g. by import_legacy). Oldest first."""
    from core.models.publishing import (
        PlannedPost,  # here, not at the top: publishing imports this module
    )

    n = 0
    for p in PlannedPost.objects.filter(ref__isnull=True).order_by("created_at", "id"):
        p.ref = next_post_ref()
        p.save(update_fields=["ref"])
        if p.post_id and not Post.objects.filter(ref=p.ref).exists():
            Post.objects.filter(id=p.post_id, ref__isnull=True).update(ref=p.ref)
        n += 1
    for post in Post.objects.filter(ref__isnull=True).order_by("published_at", "id"):
        planned = PlannedPost.objects.filter(post_id=post.id).exclude(ref__isnull=True).first()
        post.ref = planned.ref if planned and not Post.objects.filter(ref=planned.ref).exists() else next_post_ref()
        post.save(update_fields=["ref"])
        n += 1
    return n

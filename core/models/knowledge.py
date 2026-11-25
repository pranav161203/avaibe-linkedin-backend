"""Company knowledge base: what Claude should know about AVAIBE (services, projects, clients, policies).

A source applies to every account (no accounts set: company-wide facts) or only to the accounts set on it (e.g. a
second company page). Each source is split into chunks so a Claude feature can pull only the few passages that matter
for a task, not every document.
"""

from django.db import models

from core.models.accounts import Account


class KnowledgeSource(models.Model):
    """One piece of knowledge: pasted text or an uploaded file. `content` is the full extracted text."""

    KINDS = ("text", "file")

    title = models.CharField(max_length=200)
    kind = models.CharField(max_length=10, default="text")
    file_name = models.CharField(max_length=300, null=True, blank=True)  # original name, for display only
    content = models.TextField()
    chars = models.PositiveIntegerField(default=0)
    # The company it belongs to; "every account" below means every account of this company, never another's
    company = models.ForeignKey(
        "core.Company", on_delete=models.CASCADE, null=True, blank=True, related_name="knowledge_sources", db_column="company_id"
    )
    # Empty = applies to every account of the company. Otherwise only Claude work for these accounts uses it.
    accounts = models.ManyToManyField(Account, blank=True, related_name="knowledge_sources")
    created_by = models.CharField(max_length=320, null=True, blank=True)
    updated_by = models.CharField(max_length=320, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "knowledge_sources"
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.title


class KnowledgeChunk(models.Model):
    """A passage of a source (about a paragraph or a short section), the unit that search returns."""

    source = models.ForeignKey(KnowledgeSource, on_delete=models.CASCADE, related_name="chunk_items")
    index = models.PositiveIntegerField()
    heading = models.CharField(max_length=200, blank=True, default="")  # the section it belongs to, if any
    text = models.TextField()

    class Meta:
        db_table = "knowledge_chunks"
        ordering = ["source_id", "index"]
        constraints = [models.UniqueConstraint(fields=["source", "index"], name="uniq_chunk_source_index")]

    def __str__(self) -> str:
        return f"{self.source_id}#{self.index}"

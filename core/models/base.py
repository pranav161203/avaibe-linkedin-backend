"""Shared model building blocks."""

from django.conf import settings
from django.db import models


class Audited(models.Model):
    """Who created and last changed a row, and when.

    created_by / updated_by point at users.id (a real foreign key, not a copied email), so renaming someone or
    changing their email never breaks the history. They are SET_NULL: removing a user keeps the rows they touched.
    NULL means "the system" (a migration, a command, or the very first super admin, who nobody created).
    Services set them from the signed-in user; see core.services.auth.audit.stamp().
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_column="created_by"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_column="updated_by"
    )

    class Meta:
        abstract = True

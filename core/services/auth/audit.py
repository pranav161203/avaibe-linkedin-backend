"""Filling the audit columns (created_by / updated_by) from whoever is acting."""

from django.db import models


def stamp(obj: models.Model, actor_id: int | None, created: bool = False) -> None:
    """Set updated_by (and created_by for a new row) to the acting user's id. None = the system / local mode.
    created_at / updated_at are filled by the database fields themselves."""
    if created:
        obj.created_by_id = actor_id
    obj.updated_by_id = actor_id

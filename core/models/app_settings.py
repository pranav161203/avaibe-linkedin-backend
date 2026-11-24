"""Settings edited on the Settings page (read through core.services.settings_store)."""

from django.db import models


class AppSetting(models.Model):
    """Editable settings section (e.g. 'segments', 'performance', 'access') stored as JSON."""

    key = models.CharField(max_length=50, primary_key=True)
    value = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "app_settings"

    def __str__(self) -> str:
        return self.key

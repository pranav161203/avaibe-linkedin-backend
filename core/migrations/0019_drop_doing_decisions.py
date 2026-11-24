"""Suggestions no longer have an "In progress" (Do it) state: those decisions are removed,
so the suggestions show as open again. Done, Later and Dismiss stay."""

from django.db import migrations


def drop_doing(apps, schema_editor):
    apps.get_model("core", "SuggestionDecision").objects.filter(status="doing").delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0018_merge_approver_into_editor")]
    operations = [migrations.RunPython(drop_doing, migrations.RunPython.noop)]

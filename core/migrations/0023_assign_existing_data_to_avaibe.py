"""Existing data belonged to one organisation (AVAIBE) before companies existed. Put it in an "AVAIBE" company,
then require a company for everyone except super admins."""

from django.db import migrations, models


def assign(apps, schema_editor):
    Company = apps.get_model("core", "Company")
    Account = apps.get_model("core", "Account")
    User = apps.get_model("core", "User")
    KnowledgeSource = apps.get_model("core", "KnowledgeSource")
    AppSetting = apps.get_model("core", "AppSetting")

    needs_company = (
        Account.objects.exists() or KnowledgeSource.objects.exists() or User.objects.exclude(role="superadmin").exists()
    )
    if not needs_company:
        return  # a fresh database: the first super admin creates companies from the app
    company, _ = Company.objects.get_or_create(slug="avaibe", defaults={"name": "AVAIBE", "country": "AE"})
    Account.objects.filter(company__isnull=True).update(company=company)
    KnowledgeSource.objects.filter(company__isnull=True).update(company=company)
    User.objects.exclude(role="superadmin").filter(company__isnull=True).update(company=company)

    # The default account used to be an app-wide setting; it now belongs to the company
    row = AppSetting.objects.filter(key="access").first()
    default_id = (row.value or {}).get("default_account_id") if row else None
    if default_id and Account.objects.filter(id=default_id).exists():
        company.default_account_id = default_id
        company.save(update_fields=["default_account"])


class Migration(migrations.Migration):
    dependencies = [("core", "0022_companies_and_auth_tokens")]

    operations = [
        migrations.RunPython(assign, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(("role", "superadmin"), ("company__isnull", False), _connector="OR"),
                name="user_company_unless_superadmin",
            ),
        ),
    ]

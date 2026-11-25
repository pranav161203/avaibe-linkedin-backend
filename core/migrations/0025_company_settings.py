"""Settings move from one app-wide table (app_settings) to one row per company and section (company_settings).
Existing values go to the AVAIBE company. The brand kit's old built-in defaults described AVAIBE, so AVAIBE keeps
them as its own values; new companies start from generic defaults."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


# The brand defaults before settings were per company (they described AVAIBE)
AVAIBE_BRAND = {
    "company_summary": "AVAIBE is a UAE-based software company building custom software, ERP and education technology (LMS and school systems).",
    "website": "https://avaibe.com",
    "services": [],
    "target_segments": [
        "UAE decision-makers: CEOs, founders, school principals, directors, business owners",
        "Technology professionals: CTOs, IT managers, developers, consultants",
        "Potential partners: consultants, technology partners, agencies",
    ],
    "differentiators": [],
    "proof_points": [
        "Client logos shown publicly on avaibe.com: Next Generation School, CyberDisti, Alrajhi Education Management, Marathon Education UK, Costain Process Engineering & Technical LLC, American Islamic School (name clients in posts only with their permission)",
    ],
    "voice": "Professional, practical and UAE-aware. Plain English, specific examples, no hype or buzzwords.",
    "avoid": [
        "Claims that can't be verified",
        "Naming clients or results without written permission",
        "Spammy or mass outreach, engagement bait",
    ],
    "competitors": [],
    "languages": ["English"],
}
SECTIONS = ("segments", "performance", "brand")


def copy_to_avaibe(apps, schema_editor):
    Company = apps.get_model("core", "Company")
    AppSetting = apps.get_model("core", "AppSetting")
    CompanySetting = apps.get_model("core", "CompanySetting")
    company = Company.objects.filter(slug="avaibe").first()
    if company is None:
        return  # fresh database: no AVAIBE data to keep
    old = {r.key: r.value or {} for r in AppSetting.objects.filter(key__in=SECTIONS)}
    old["brand"] = {**AVAIBE_BRAND, **old.get("brand", {})}
    for section, value in old.items():
        CompanySetting.objects.update_or_create(company=company, section=section, defaults={"value": value})


def copy_back(apps, schema_editor):
    Company = apps.get_model("core", "Company")
    AppSetting = apps.get_model("core", "AppSetting")
    CompanySetting = apps.get_model("core", "CompanySetting")
    company = Company.objects.filter(slug="avaibe").first()
    if company is None:
        return
    for row in CompanySetting.objects.filter(company=company):
        AppSetting.objects.update_or_create(key=row.section, defaults={"value": row.value})


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0024_role_label_owner'),
    ]

    operations = [
        migrations.CreateModel(
            name='CompanySetting',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('section', models.CharField(max_length=30)),
                ('value', models.JSONField()),
                ('company', models.ForeignKey(db_column='company_id', on_delete=django.db.models.deletion.CASCADE, related_name='settings', to='core.company')),
                ('created_by', models.ForeignKey(blank=True, db_column='created_by', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('updated_by', models.ForeignKey(blank=True, db_column='updated_by', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'company_settings',
            },
        ),
        migrations.AddConstraint(
            model_name='companysetting',
            constraint=models.UniqueConstraint(fields=('company', 'section'), name='company_setting_unique_section'),
        ),
        migrations.RunPython(copy_to_avaibe, copy_back),
        migrations.DeleteModel(
            name='AppSetting',
        ),
    ]

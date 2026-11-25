"""One-off: copy data from the previous (FastAPI) PostgreSQL database into this Django database.

    python manage.py import_legacy            # refuses if this database already has data
    python manage.py import_legacy --replace  # wipe this database's app data first, then import

Reads LEGACY_DATABASE_URL (server/.env). The old database is only read, never changed.
IDs are kept so links between records stay valid. Uploaded images are copied from backend/uploads.
"""

import os
import shutil

import psycopg
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connection, transaction
from psycopg.rows import dict_row

from core.conf import BASE_DIR, UPLOAD_DIR
from core.models import (
    Account,
    Company,
    CompanySetting,
    LinkedInConnection,
    PageAudience,
    PlannedPost,
    Post,
    PostAudience,
    Snapshot,
    User,
)
from core.services import settings_store

METRICS = [
    "impressions", "members_reached", "clicks", "reactions", "comments", "reposts", "video_views",
    "poll_votes", "newsletter_views", "newsletter_subscribers", "followers_gained",
]


class Command(BaseCommand):
    help = "Copy data from the previous FastAPI database (LEGACY_DATABASE_URL) into this one."

    def add_arguments(self, parser):
        parser.add_argument("--replace", action="store_true", help="Delete this database's app data before importing")

    def handle(self, *args, replace: bool, **opts):
        url = os.getenv("LEGACY_DATABASE_URL", "").replace("postgresql+psycopg://", "postgresql://")
        if not url:
            raise CommandError("LEGACY_DATABASE_URL is not set in server/.env")

        has_data = Post.objects.exists() or PlannedPost.objects.exists() or User.objects.exists()
        if has_data and not replace:
            raise CommandError("This database already has data. Re-run with --replace to overwrite it.")

        with psycopg.connect(url, row_factory=dict_row) as old:
            def rows(table: str) -> list[dict]:
                exists = old.execute("SELECT to_regclass(%s) AS t", (f"public.{table}",)).fetchone()["t"]
                return old.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() if exists else []

            data = {t: rows(t) for t in [
                "accounts", "posts", "snapshots", "post_audience", "page_audience",
                "linkedin_connections", "planned_posts", "app_settings", "users",
            ]}

        with transaction.atomic():
            # Clear app data (including the starter account a fresh migrate creates)
            for model in (PlannedPost, LinkedInConnection, PageAudience, PostAudience, Snapshot, Post, Account, CompanySetting, User):
                model.objects.all().delete()
            # The previous app served one organisation: everything goes into the AVAIBE company
            company, _ = Company.objects.get_or_create(slug="avaibe", defaults={"name": "AVAIBE", "country": "AE"})

            Account.objects.bulk_create([
                Account(id=r["id"], name=r["name"], kind=r["kind"], linkedin_url=r["linkedin_url"], is_test=r["is_test"], company=company)
                for r in data["accounts"]
            ])
            Post.objects.bulk_create([
                Post(
                    id=r["id"], account_id=r["account_id"], post_url=r["post_url"], linkedin_post_id=r["linkedin_post_id"],
                    author=r["author"], published_at=r["published_at"], format=r["format"], topic=r["topic"],
                    industry=r["industry"], keywords=r["keywords"] or [], cta=r["cta"], hashtags=r["hashtags"] or [],
                    caption=r["caption"], notes=r["notes"],
                )
                for r in data["posts"]
            ])
            Snapshot.objects.bulk_create([
                Snapshot(id=r["id"], post_id=r["post_id"], checkpoint=r["checkpoint"], captured_at=r["captured_at"],
                         notes=r["notes"], **{m: r.get(m) for m in METRICS})
                for r in data["snapshots"]
            ])
            PostAudience.objects.bulk_create([
                PostAudience(id=r["id"], post_id=r["post_id"], dimension=r["dimension"], value=r["value"], pct=r["pct"], captured_at=r["captured_at"])
                for r in data["post_audience"]
            ])
            PageAudience.objects.bulk_create([
                PageAudience(id=r["id"], account_id=r["account_id"], as_of=r["as_of"], audience=r["audience"], total=r["total"],
                             dimension=r["dimension"], value=r["value"], count=r["count"], pct=r["pct"])
                for r in data["page_audience"]
            ])
            LinkedInConnection.objects.bulk_create([
                LinkedInConnection(id=r["id"], account_id=r["account_id"], member_urn=r["member_urn"], name=r["name"],
                                   email=r["email"], picture_url=r["picture_url"], access_token_enc=r["access_token_enc"],
                                   scopes=r["scopes"], expires_at=r["expires_at"])
                for r in data["linkedin_connections"]
            ])
            PlannedPost.objects.bulk_create([
                PlannedPost(
                    id=r["id"], account_id=r["account_id"], caption=r["caption"], image_file=r["image_file"],
                    image_alt=r["image_alt"], visibility=r["visibility"], scheduled_at=r["scheduled_at"], status=r["status"],
                    topic=r["topic"], industry=r["industry"], cta=r["cta"], keywords=r["keywords"] or [],
                    approved_at=r["approved_at"], published_at=r["published_at"], linkedin_urn=r["linkedin_urn"],
                    post_id=r["post_id"], error=r["error"],
                )
                for r in data["planned_posts"]
            ])
            CompanySetting.objects.bulk_create([
                CompanySetting(company=company, section=r["key"], value=r["value"])
                for r in data["app_settings"]
                if r["key"] in settings_store.VALIDATORS
            ])
            for r in data["users"]:
                u = User(id=r["id"], email=r["email"].lower(), name=r["name"], role=r["role"],
                         company=None if r["role"] == "superadmin" else company,
                         can_switch_accounts=r["can_switch_accounts"], is_active=r["active"], last_login=r["last_login_at"])
                u.set_unusable_password()  # Microsoft sign-in only
                u.save()

            # Keep the original timestamps (auto_now fields were set to "now" on insert)
            for model, table, cols in [
                (Account, "accounts", ["created_at"]),
                (Post, "posts", ["created_at", "updated_at"]),
                (PlannedPost, "planned_posts", ["created_at", "updated_at"]),
                (LinkedInConnection, "linkedin_connections", ["connected_at"]),
                (User, "users", ["created_at"]),
            ]:
                for r in data[table]:
                    vals = {c: r[c] for c in cols if r.get(c) is not None}
                    if vals:
                        model.objects.filter(id=r["id"]).update(**vals)

            # Next new record continues after the imported IDs
            with connection.cursor() as cur:
                for stmt in connection.ops.sequence_reset_sql(no_style(), [Account, Post, Snapshot, PostAudience, PageAudience,
                                                                            LinkedInConnection, PlannedPost, User]):
                    cur.execute(stmt)

            # Bulk-created rows skip save(): give every post its readable ID (P-0042)
            from core.models import assign_missing_refs

            assign_missing_refs()

        settings_store.invalidate()

        # Uploaded images for the publishing queue
        old_uploads = BASE_DIR.parent / "backend" / "uploads"
        copied = 0
        if old_uploads.exists():
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            for f in old_uploads.iterdir():
                if f.is_file() and not (UPLOAD_DIR / f.name).exists():
                    shutil.copy2(f, UPLOAD_DIR / f.name)
                    copied += 1

        summary = {t: len(v) for t, v in data.items()}
        self.stdout.write(self.style.SUCCESS(f"Imported: {summary}; images copied: {copied}"))

"""CSV import. One row = one post + one snapshot. Rows for the same post_url update that post and
add/replace the snapshot for the given checkpoint. Each row is saved on its own, so one bad row
doesn't block the rest."""

import csv
import io
from datetime import date

from django.db import transaction
from django.http import HttpResponse
from pydantic import ValidationError
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.api.errors import fail
from core.api.params import int_param
from core.auth.permissions import check_account, require
from core.common.timeutil import as_utc, to_uae
from core.models import (
    Account,
    AccountDoc,
    PageAudience,
    Snapshot,
)
from core.services.imports import linkedin_export
from core.services.imports.csv_import import TEMPLATE_COLUMNS, import_row

# Column headings that only appear in LinkedIn's page-analytics exports (content, followers, visitors)
LINKEDIN_EXPORT_HEADINGS = (
    "Post title", "Post link", "Impressions (total)", "Total followers", "Total page views (total)",
    "Total unique visitors (total)", "Total views", "Job function", "Company size",
)


@api_view(["GET"])
def template(request):
    example = {
        "post_url": "https://www.linkedin.com/feed/update/urn:li:activity:0000000000000000000/",
        "published_at_uae": "2026-11-10 10:30",
        "format": "carousel",
        "topic": "ERP challenges",
        "industry": "Trading",
        "keywords": "erp;inventory",
        "cta": "Comment ERP for the checklist",
        "hashtags": "#erp #uae",
        "author": "AVAIBE",
        "caption": "",
        "checkpoint": "24h",
        "captured_at_uae": "2026-11-11 10:30",
    }
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=TEMPLATE_COLUMNS)
    w.writeheader()
    w.writerow({c: example.get(c, "") for c in TEMPLATE_COLUMNS})
    resp = HttpResponse(buf.getvalue(), content_type="text/csv")
    resp["Content-Disposition"] = "attachment; filename=linkedin_posts_template.csv"
    return resp


@api_view(["POST"])
def import_linkedin_export(request):
    """One or more files exported from LinkedIn page analytics (content, followers, visitors).
    Optional exported_on (YYYY-MM-DD); otherwise read from LinkedIn's file name, else today."""
    user = request.user
    require(user, "editor")
    account_id = int_param(request, "account_id", required=True)
    account = Account.objects.filter(id=account_id).first()
    if account is None:
        fail(404, "Account not found")
    check_account(user, account_id)
    uploads = request.FILES.getlist("files")
    if not uploads:
        fail(422, "Attach at least one export file")
    # Every export this importer reads comes from a company page; into a profile only when someone confirms it
    if account.kind != "company" and str(request.data.get("confirm_profile", "")).lower() not in {"1", "true", "yes"}:
        fail(
            409,
            f"{account.name} is a {account.kind} profile, but LinkedIn page exports come from a company page. "
            "Switch to the company page, or confirm to import into this profile anyway.",
        )
    exported_on = None
    if request.data.get("exported_on"):
        try:
            exported_on = date.fromisoformat(str(request.data["exported_on"]))
        except ValueError:
            fail(422, "Export date must be in YYYY-MM-DD format")
    results = []
    for f in uploads:
        if f.size > 20 * 1024 * 1024:
            results.append({"file": f.name, "kind": None, "errors": ["File is larger than 20 MB"]})
            continue
        try:
            results.append(linkedin_export.import_file(account, f.name, f.read(), exported_on))
        except linkedin_export.ExportError as e:
            results.append({"file": f.name, "kind": None, "errors": [str(e)]})
    return Response({"account": account.name, "account_kind": account.kind, "files": results})


@api_view(["POST"])
def import_csv(request):
    user = request.user
    require(user, "editor")
    account_id = int_param(request, "account_id", required=True)
    if not Account.objects.filter(id=account_id).exists():
        fail(404, "Account not found")
    check_account(user, account_id)
    upload = request.FILES.get("file")
    if upload is None:
        fail(422, "Attach a CSV file")
    raw = upload.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    reader = csv.DictReader(io.StringIO(text))
    headers = set(reader.fieldnames or [])
    if not {"published_at_uae", "format"} <= headers:
        # A LinkedIn export re-saved as CSV loses its sheet names: point to the original Excel file instead
        top = " ".join(text.splitlines()[:5])
        if any(m in top for m in LINKEDIN_EXPORT_HEADINGS):
            fail(
                400,
                "This looks like a LinkedIn analytics export saved as CSV. Upload the original Excel file (.xls) "
                "under “LinkedIn page export” above instead: it has the sheets the app needs to tell posts, "
                "followers and visitors apart.",
            )
    missing = {"published_at_uae", "format"} - headers
    if missing:
        fail(400, f"Missing required columns: {', '.join(sorted(missing))}")

    created = updated = snapshots = 0
    errors: list[dict] = []
    for i, row in enumerate(reader, start=2):  # row 1 is the header
        row = {k: (v or "") for k, v in row.items() if k}
        try:
            with transaction.atomic():  # a failing row leaves nothing half-saved
                outcome, snap_saved = import_row(row, account_id)
        except (ValueError, ValidationError, KeyError) as e:
            errors.append({"row": i, "error": str(e)})
            continue
        created += outcome == "created"
        updated += outcome == "updated"
        snapshots += snap_saved
    return Response({"posts_created": created, "posts_updated": updated, "snapshots_saved": snapshots, "errors": errors})


@api_view(["GET"])
def last_imports(request, account_id: int):
    """When each LinkedIn export type (content, followers, visitors) was last imported for this account."""
    check_account(request.user, account_id)
    doc = AccountDoc.objects.filter(account_id=account_id, kind=linkedin_export.LAST_IMPORTS).first()
    out = dict(doc.data) if doc else {}
    # Imports from before this was recorded: work out the export date from the data itself (import time unknown)
    if "content" not in out:
        snap = (
            Snapshot.objects.filter(post__account_id=account_id, notes__startswith=linkedin_export.EXPORT_NOTE)
            .order_by("-captured_at")
            .first()
        )
        if snap:
            out["content"] = {"at": None, "exported_on": to_uae(as_utc(snap.captured_at)).date().isoformat(), "file": None}
    for kind in ("followers", "visitors"):
        if kind not in out:
            latest = PageAudience.objects.filter(account_id=account_id, audience=kind).order_by("-as_of").first()
            if latest:
                out[kind] = {"at": None, "exported_on": latest.as_of.isoformat(), "file": None}
    return Response(out)

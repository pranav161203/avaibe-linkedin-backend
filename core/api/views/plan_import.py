"""Plan posts in bulk from an Excel file (or the same columns saved as CSV).

GET  /planner/import/template  -> the Excel template (Posts sheet with dropdowns, a How to fill sheet, an Example sheet)
POST /planner/import           -> checks every row and reports back; with confirm=1 it also saves the rows that are
                                  ready as unpublished posts (drafts). Rows with problems and posts already planned are
                                  skipped, never half-saved.
"""


from django.http import HttpResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.api.errors import fail
from core.api.params import int_param
from core.auth.permissions import check_account, require
from core.models import Account
from core.services.imports import plan_excel


@api_view(["GET"])
def template(request):
    resp = HttpResponse(plan_excel.build_template(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = "attachment; filename=avaibe_post_plan_template.xlsx"
    return resp


@api_view(["POST"])
def import_plan(request):
    user = request.user
    require(user, "editor")
    account_id = int_param(request, "account_id", required=True)
    if not Account.objects.filter(id=account_id).exists():
        fail(404, "Account not found")
    check_account(user, account_id)
    upload = request.FILES.get("file")
    if not upload:
        fail(400, "Choose a file to import")
    if upload.size > plan_excel.MAX_BYTES:
        fail(400, "The file is over 5 MB. Split it into smaller files.")
    confirm = str(request.query_params.get("confirm", "")).lower() in {"1", "true", "yes"}

    try:
        results, ready = plan_excel.review_rows(upload, account_id)
    except plan_excel.PlanFileError as e:
        fail(400, str(e))
    if not results:
        fail(400, "No posts found. Fill the Posts sheet from row 2 down, one post per row.")

    created = plan_excel.save_drafts(ready) if confirm else []
    return Response(
        {
            "rows": results,
            "ready": len(ready),
            "errors": sum(r["status"] == "error" for r in results),
            "duplicates": sum(r["status"] == "duplicate" for r in results),
            "created": len(created),
            "refs": [p.ref for p in created],
        }
    )

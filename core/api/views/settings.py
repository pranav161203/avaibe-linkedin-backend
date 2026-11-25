from pydantic import ValidationError
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.api.errors import fail
from core.api.params import int_param
from core.auth.permissions import is_owner, require
from core.conf import ANTHROPIC_API_KEY, CLAUDE_MODEL
from core.models import Company
from core.services import settings_store
from core.services.ai import usage as ai_usage

EDITABLE_SECTIONS = {"segments", "performance", "brand"}


def _section(section: str) -> str:
    if section not in EDITABLE_SECTIONS:
        fail(422, f"Section must be one of: {', '.join(sorted(EDITABLE_SECTIONS))}")
    return section


def _company_id(request) -> int:
    """Whose settings: your own company, or for an owner the ?company_id= they are managing."""
    user = request.user
    if not is_owner(user):
        if not user.company_id:
            fail(403, "Your account is not assigned to a company")
        return user.company_id
    company_id = int_param(request, "company_id")
    if company_id is None:
        ids = list(Company.objects.values_list("id", flat=True)[:2])
        if len(ids) != 1:
            fail(400, "Select a company")
        return ids[0]
    if not Company.objects.filter(id=company_id).exists():
        fail(404, "Company not found")
    return company_id


@api_view(["GET"])
def get_settings(request):
    company_id = _company_id(request)
    return Response({"company_id": company_id, "current": settings_store.all_settings(company_id), "defaults": settings_store.DEFAULTS})


@api_view(["PUT"])
def save_section(request, section: str):
    require(request.user, "admin")
    _section(section)
    try:
        return Response(settings_store.save(section, request.data, _company_id(request), request.user.id))
    except ValidationError as e:
        err = e.errors()[0]  # first readable message
        where = ".".join(str(x) for x in err.get("loc", ()) if x != "__root__")
        msg = err.get("msg", "Invalid value").removeprefix("Value error, ")
        fail(400, f"{where}: {msg}" if where else msg)
    except TypeError:
        fail(422, "Expected a JSON object")


@api_view(["POST"])
def reset_section(request, section: str):
    require(request.user, "admin")
    return Response(settings_store.reset(_section(section), _company_id(request)))


@api_view(["GET"])
def claude_status(request):
    """Whether the AI connection is configured. Never returns the key itself.
    The key hint and usage (platform-wide, with cost) are for owners only."""
    owner = is_owner(request.user)
    return Response(
        {
            "configured": bool(ANTHROPIC_API_KEY),
            "model": CLAUDE_MODEL,
            "daily_limit_per_account": ai_usage.DAILY_RUN_LIMIT,
            "key_hint": f"…{ANTHROPIC_API_KEY[-4:]}" if owner and len(ANTHROPIC_API_KEY) >= 8 else None,
            "usage": ai_usage.usage_summary() if owner else None,
        }
    )

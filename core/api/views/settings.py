from pydantic import ValidationError
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.api.errors import fail
from core.auth.permissions import is_owner, require
from core.conf import ANTHROPIC_API_KEY, CLAUDE_MODEL
from core.services import settings_store
from core.services.ai import usage as ai_usage

EDITABLE_SECTIONS = {"segments", "performance", "brand"}


def _section(section: str) -> str:
    if section not in EDITABLE_SECTIONS:
        fail(422, f"Section must be one of: {', '.join(sorted(EDITABLE_SECTIONS))}")
    return section


@api_view(["GET"])
def get_settings(request):
    return Response({"current": settings_store.all_settings(), "defaults": settings_store.DEFAULTS})


@api_view(["PUT"])
def save_section(request, section: str):
    require(request.user, "admin")
    _section(section)
    try:
        return Response(settings_store.save(section, request.data))
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
    return Response(settings_store.reset(_section(section)))


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

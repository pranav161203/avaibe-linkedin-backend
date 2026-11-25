from datetime import timedelta
from urllib.parse import urlencode

import httpx
from django.http import HttpResponseRedirect
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.api.errors import NO_CONTENT, fail
from core.api.params import int_param
from core.auth.permissions import allowed_account_ids, check_account, for_viewer, is_owner, require
from core.common.crypto import TokenKeyError, encrypt
from core.common.timeutil import as_utc, now_utc
from core.conf import (
    FRONTEND_URL,
    LINKEDIN_CLIENT_ID,
    LINKEDIN_CLIENT_SECRET,
    TOKEN_ENCRYPTION_KEY,
    linkedin_configured,
)
from core.integrations.linkedin import member_client as li
from core.models import Account, LinkedInConnection, OAuthState

STATE_TTL = timedelta(minutes=10)


def _back(**params: str) -> HttpResponseRedirect:
    return HttpResponseRedirect(f"{FRONTEND_URL}/linkedin?{urlencode(params)}")


@api_view(["GET"])
def config_status(request):
    missing = [
        name
        for name, value in [
            ("LINKEDIN_CLIENT_ID", LINKEDIN_CLIENT_ID),
            ("LINKEDIN_CLIENT_SECRET", LINKEDIN_CLIENT_SECRET),
            ("TOKEN_ENCRYPTION_KEY", TOKEN_ENCRYPTION_KEY),
        ]
        if not value
    ]
    # Setting names are setup detail: owners only
    return Response({"configured": not missing, "missing": missing if is_owner(request.user) else []})


@api_view(["GET"])
def connections(request):
    now = now_utc()
    allowed = set(allowed_account_ids(request.user))
    return Response(
        [
            {
                "account_id": c.account_id,
                "name": c.name,
                "email": c.email,
                "picture_url": c.picture_url,
                "expires_at": as_utc(c.expires_at).isoformat(),
                "expired": as_utc(c.expires_at) <= now,
                "days_left": max(0, (as_utc(c.expires_at) - now).days),
                "connected_at": as_utc(c.connected_at).isoformat() if c.connected_at else None,
            }
            for c in LinkedInConnection.objects.all()
            if c.account_id in allowed
        ]
    )


@api_view(["GET"])
def auth_url(request):
    user = request.user
    require(user, "editor")
    if not linkedin_configured():
        fail(
            400,
            for_viewer(
                user,
                "LinkedIn integration is not configured. Contact the platform owner.",
                "LinkedIn integration is not configured. Set the client ID, client secret and encryption key on the server.",
            ),
        )
    account_id = int_param(request, "account_id", required=True)
    acc = Account.objects.filter(id=account_id).first()
    if not acc:
        fail(404, "Account not found")
    check_account(user, account_id)
    if acc.kind == "company":
        fail(
            400,
            "Only personal profiles can be connected. Company pages require LinkedIn Community Management API access.",
        )
    OAuthState.objects.filter(created_at__lt=now_utc() - STATE_TTL).delete()
    state = li.new_state()
    OAuthState.objects.create(state=state, account=acc, created_at=now_utc())
    return Response({"url": li.authorization_url(state)})


def callback(request):
    """LinkedIn redirects the browser here. Protected by the one-time state value (no app session needed)."""
    q = request.GET
    state = q.get("state", "")
    st = OAuthState.objects.filter(state=state).first() if state else None
    if st is None or as_utc(st.created_at) < now_utc() - STATE_TTL:
        return _back(linkedin="error", message="The connection request expired or was invalid. Try connecting again.")
    account_id = st.account_id
    st.delete()  # one-time use

    error = q.get("error")
    if error:
        msg = "The LinkedIn connection was cancelled." if error == "user_cancelled_authorize" else (q.get("error_description") or error)
        return _back(linkedin="error", message=msg)
    code = q.get("code")
    if not code:
        return _back(linkedin="error", message="LinkedIn did not return an authorisation code.")

    try:
        tok = li.exchange_code(code)
        info = li.userinfo(tok["access_token"])
        token_enc = encrypt(tok["access_token"])
    except li.LinkedInBusy as e:
        # Busy, not refused: the sign-in code is single-use, so the person simply connects again after a wait
        mins = max(2, -(-(e.retry_after or 0) // 60))
        return _back(linkedin="busy", wait=str(mins))
    except li.LinkedInError as e:
        return _back(linkedin="error", message=f"LinkedIn declined the connection: {e.message}")
    except httpx.HTTPError:
        return _back(linkedin="busy", wait="2")
    except TokenKeyError as e:
        msg = for_viewer(request.user, "The connection could not be saved due to a configuration issue. Contact the platform owner.", str(e))
        return _back(linkedin="error", message=msg)

    scope = tok.get("scope") or ""
    if scope and "w_member_social" not in scope:
        return _back(linkedin="error", message="Posting permission was not granted, so posts cannot be published.")

    conn, _ = LinkedInConnection.objects.get_or_create(
        account_id=account_id,
        defaults={"member_urn": "", "access_token_enc": "", "expires_at": now_utc()},
    )
    conn.member_urn = f"urn:li:person:{info['sub']}"
    conn.name = info.get("name")
    conn.email = info.get("email")
    conn.picture_url = info.get("picture")
    conn.access_token_enc = token_enc
    conn.scopes = scope or None
    conn.expires_at = tok["expires_at"]
    conn.connected_at = now_utc()
    conn.save()
    return _back(linkedin="connected", name=conn.name or "")


@api_view(["DELETE"])
def disconnect(request, account_id: int):
    """Removes the stored token. To fully revoke, also remove the app under
    LinkedIn Settings → Data privacy → Permitted services."""
    require(request.user, "editor")
    check_account(request.user, account_id)
    LinkedInConnection.objects.filter(account_id=account_id).delete()
    return Response(status=NO_CONTENT)

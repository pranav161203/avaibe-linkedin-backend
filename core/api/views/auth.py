"""Sign-in endpoints (/api/auth/...). The rules live in core/services/auth; these views only turn results into
cookies and responses. See docs/auth.md.

  GET  me                 who is signed in (also sets the CSRF cookie the app echoes back on writes)
  POST login              email + password -> access and refresh cookies
  POST refresh            refresh cookie -> new access and refresh cookies (rotation)
  POST logout             ends this device's session, clears the cookies
  GET  invitation?token=  what an invitation link is for (email, company, role) before signing up
  POST signup             accept an invitation: name + password -> signed in
  POST password           change your own password (signs out your other devices)
  GET  microsoft          start Microsoft sign-in;  GET callback: Microsoft sends the browser back here
"""

import logging
import os
from datetime import timedelta
from urllib.parse import urlencode

from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.http import HttpResponseRedirect
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.api.errors import fail
from core.api.params import parse
from core.auth.authentication import current_from_request, enforce_csrf, user_from_token
from core.auth.cookies import ACCESS_COOKIE, REFRESH_COOKIE, clear_tokens, set_tokens
from core.auth.microsoft import SCOPES, msal_app
from core.auth.permissions import allowed_account_ids, default_account_id
from core.common.timeutil import as_utc, now_utc
from core.conf import ADMIN_EMAILS, FRONTEND_URL, MS_REDIRECT_URI, auth_enabled, email_configured, microsoft_configured
from core.models import AuthFlow, User
from core.schemas.auth import LoginIn, PasswordChangeIn, PasswordResetIn, PasswordResetRequestIn, SignupIn
from core.services.auth import AuthError, invitations, resets, sessions, signin, tokens

log = logging.getLogger("auth")

FLOW_TTL = timedelta(minutes=10)


def _ua(request) -> str:
    return request.META.get("HTTP_USER_AGENT", "")[:300]


def _auth_fail(e: AuthError):
    fail(e.status, e.message)


def _public(methods):
    """A DRF view anyone may call (sign-in itself). Writes still need the CSRF header (blocks login CSRF)."""

    def wrap(fn):
        def inner(request, *a, **kw):
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                enforce_csrf(request._request)
            return fn(request, *a, **kw)

        inner.__name__, inner.__doc__ = fn.__name__, fn.__doc__
        return api_view(methods)(authentication_classes([])(permission_classes([AllowAny])(inner)))

    return wrap


# ------------------------------------------------------------------ who is signed in


@ensure_csrf_cookie  # gives the React app the csrftoken cookie it echoes back on writes
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def me(request):
    methods = {"password": True, "microsoft": microsoft_configured(), "password_reset": email_configured()}
    user = current_from_request(request._request)
    if user is None:
        return Response({"enabled": True, "methods": methods, "user": None})
    has_password = False
    if user.id is not None:
        has_password = User.objects.filter(id=user.id).only("password").first().has_usable_password()
    return Response(
        {
            "enabled": auth_enabled(),
            "methods": methods,
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "role": user.role,
                "can_switch_accounts": user.switcher,
                "dev": user.dev,
                "has_password": has_password,
                "company": {"id": user.company_id, "name": user.company_name} if user.company_id else None,
            },
            "allowed_account_ids": allowed_account_ids(user),
            "default_account_id": default_account_id(user),
        }
    )


# ------------------------------------------------------------------ password sign-in and tokens


@_public(["POST"])
def login(request):
    body = parse(LoginIn, request.data)
    try:
        issued = signin.sign_in(body.email, body.password, _ua(request))
    except AuthError as e:
        _auth_fail(e)
    resp = Response({"signed_in": True})
    set_tokens(resp, issued)
    return resp


@_public(["POST"])
def refresh(request):
    try:
        issued = tokens.refresh(request.COOKIES.get(REFRESH_COOKIE, ""))
    except AuthError as e:
        resp = Response({"detail": e.message, "code": e.code}, status=e.status)
        clear_tokens(resp)
        return resp
    resp = Response({"refreshed": True})
    set_tokens(resp, issued)
    return resp


@_public(["POST"])
def logout(request):
    user = user_from_token(request.COOKIES.get(ACCESS_COOKIE))
    if user and user.session_id:
        tokens.revoke_session(user.session_id, "signed_out")
    else:
        tokens.revoke_by_refresh(request.COOKIES.get(REFRESH_COOKIE, ""))
    django_logout(request._request)  # the /admin session, if any
    resp = Response({"signed_out": True})
    clear_tokens(resp)
    return resp


@api_view(["POST"])
def change_password(request):
    me = request.user
    if me.dev:
        fail(400, "Passwords cannot be changed while sign-in is disabled")
    body = parse(PasswordChangeIn, request.data)
    user = User.objects.get(id=me.id)
    try:
        signin.change_password(user, body.current, body.new, keep_session=me.session_id)
    except AuthError as e:
        _auth_fail(e)
    return Response({"changed": True})


# ------------------------------------------------------------------ signed-in devices


def _signed_in(request):
    me = request.user
    if me.dev:
        fail(400, "Sessions are not available while sign-in is disabled")
    return me


@api_view(["GET"])
def session_list(request):
    me = _signed_in(request)
    return Response(
        [
            {
                "id": str(s.id),
                "device": sessions.describe_device(s.user_agent),
                "method": s.method,
                "created_at": as_utc(s.created_at).isoformat(),
                "last_used_at": as_utc(s.last_used_at).isoformat(),
                "expires_at": as_utc(s.expires_at).isoformat(),
                "current": str(s.id) == str(me.session_id),
            }
            for s in sessions.active(me.id)
        ]
    )


@api_view(["DELETE"])
def session_detail(request, session_id: str):
    """Sign one device out. Signing out this device is the regular sign-out (it also clears the cookies)."""
    me = _signed_in(request)
    if session_id == str(me.session_id):
        fail(400, "Use Sign out to end the current session")
    try:
        sessions.sign_out_device(me.id, session_id)
    except AuthError as e:
        _auth_fail(e)
    return Response(status=204)


@api_view(["POST"])
def sessions_sign_out_others(request):
    me = _signed_in(request)
    return Response({"signed_out": sessions.sign_out_others(me.id, me.session_id)})


# ------------------------------------------------------------------ invitations (sign-up)


@_public(["GET"])
def invitation(request):
    try:
        inv = invitations.find(request.query_params.get("token", ""))
    except AuthError as e:
        _auth_fail(e)
    return Response({"email": inv.email, "role": inv.role, "company": inv.company.name if inv.company_id else None})


@_public(["POST"])
def signup(request):
    body = parse(SignupIn, request.data)
    try:
        user = invitations.accept(body.token, body.name, body.password)
    except AuthError as e:
        _auth_fail(e)
    resp = Response({"signed_in": True}, status=201)
    set_tokens(resp, tokens.start_session(user, "password", _ua(request)))
    return resp


# ------------------------------------------------------------------ forgotten password


@_public(["POST"])
def password_reset_request(request):
    """Always the same reply, whether or not the email has an account."""
    if not email_configured():
        fail(400, "Password reset by email is not available. Contact your administrator.")
    body = parse(PasswordResetRequestIn, request.data)
    resets.request(body.email)
    return Response({"requested": True})


@_public(["GET"])
def password_reset_check(request):
    try:
        reset = resets.find(request.query_params.get("token", ""))
    except AuthError as e:
        _auth_fail(e)
    return Response({"email": reset.user.email})


@_public(["POST"])
def password_reset(request):
    body = parse(PasswordResetIn, request.data)
    try:
        issued = resets.confirm(body.token, body.password, _ua(request))
    except AuthError as e:
        _auth_fail(e)
    resp = Response({"signed_in": True})
    set_tokens(resp, issued)
    return resp


# ------------------------------------------------------------------ Microsoft sign-in


def _to_signin(**params: str) -> HttpResponseRedirect:
    return HttpResponseRedirect(f"{FRONTEND_URL}/signin?{urlencode(params)}")


def _safe_next(value: str | None) -> str:
    """Only allow returning to the Django admin after sign-in; everything else goes to the app."""
    if value and value.startswith("/admin") and "//" not in value:
        return value
    return ""


def microsoft_login(request):
    if not microsoft_configured():
        return _to_signin(error="microsoft_off")
    AuthFlow.objects.filter(created_at__lt=now_utc() - FLOW_TTL).delete()
    flow = msal_app().initiate_auth_code_flow(SCOPES, redirect_uri=MS_REDIRECT_URI)
    flow["_next"] = _safe_next(request.GET.get("next"))
    AuthFlow.objects.create(state=flow["state"], flow=flow, created_at=now_utc())
    return HttpResponseRedirect(flow["auth_uri"])


def _microsoft_user(claims: dict) -> tuple[User | None, str | None]:
    """The user for a verified Microsoft identity, or (None, error code)."""
    email = (claims.get("email") or claims.get("preferred_username") or "").strip().lower()
    if not email:
        return None, "no_email"
    user = User.objects.select_related("company").filter(email__iexact=email).first()
    if user is None and email in ADMIN_EMAILS:
        user = User.objects.create_user(email, name=claims.get("name"), role="superadmin", can_switch_accounts=True)
    if user is None:
        user = invitations.accept_for_microsoft(email, claims.get("name"))
    if user is None:
        return None, "not_invited"
    if not user.is_active:
        return None, "disabled"
    if user.company_id and not user.company.is_active:
        return None, "company_disabled"
    if claims.get("name") and user.name != claims["name"]:
        user.name = claims["name"]
        user.save(update_fields=["name", "updated_at"])
    return user, None


def callback(request):
    if not microsoft_configured():
        return _to_signin(error="microsoft_off")
    params = request.GET.dict()
    if params.get("error"):
        return _to_signin(error="microsoft", message=params.get("error_description", params["error"])[:300])

    row = AuthFlow.objects.filter(state=params.get("state", "")).first()
    if row is None or as_utc(row.created_at) < now_utc() - FLOW_TTL:
        return _to_signin(error="expired")
    flow = row.flow
    row.delete()  # single use
    next_url = flow.pop("_next", "")

    try:
        result = msal_app().acquire_token_by_auth_code_flow(flow, params)
    except ValueError:  # state/nonce mismatch: MSAL rejects tampered or replayed callbacks
        return _to_signin(error="invalid")
    if "error" in result:
        log.warning("Microsoft sign-in failed: %s", result.get("error"))
        return _to_signin(error="microsoft", message=str(result.get("error_description", result["error"]))[:300])

    claims = result.get("id_token_claims") or {}
    if claims.get("tid") != os.getenv("MS_TENANT_ID"):
        return _to_signin(error="tenant")
    user, error = _microsoft_user(claims)
    if user is None:
        return _to_signin(error=error)

    resp = HttpResponseRedirect(next_url or FRONTEND_URL)
    set_tokens(resp, tokens.start_session(user, "microsoft", _ua(request)))
    if next_url:  # the Django admin screens use their own session
        django_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return resp

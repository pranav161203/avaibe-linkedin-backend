"""Email + password sign-in, with a pause after repeated wrong passwords."""

from datetime import timedelta

from django.contrib.auth.hashers import make_password

from core.common.timeutil import now_utc
from core.conf import LOGIN_LOCK_MINUTES, LOGIN_MAX_FAILURES
from core.models import LoginAttempt, User
from core.services.auth import AuthError, tokens

# The same message for "no such email" and "wrong password", so the form can't be used to find out who has an account
WRONG = "That email and password don't match"
# Hashing a dummy password when the email is unknown keeps the reply time the same either way
_DUMMY_HASH = None


def _dummy_check(password: str) -> None:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = make_password("not-a-real-password")
    User(password=_DUMMY_HASH).check_password(password)


def _locked(email: str) -> bool:
    since = now_utc() - timedelta(minutes=LOGIN_LOCK_MINUTES)
    LoginAttempt.objects.filter(created_at__lt=since).delete()
    return LoginAttempt.objects.filter(email=email, created_at__gte=since).count() >= LOGIN_MAX_FAILURES


def sign_in(email: str, password: str, user_agent: str = "") -> tokens.Issued:
    email = (email or "").strip().lower()
    if _locked(email):
        raise AuthError("locked", f"Too many failed attempts. Try again in {LOGIN_LOCK_MINUTES} minutes.", status=429)
    user = User.objects.select_related("company").filter(email__iexact=email).first()
    # check_password also upgrades an older hash (e.g. PBKDF2) to Argon2id after a correct password
    ok = user.check_password(password) if user and user.has_usable_password() else (_dummy_check(password) or False)
    if not ok:
        LoginAttempt.objects.create(email=email)
        raise AuthError("wrong_password", WRONG, status=401)
    if not user.is_active:
        raise AuthError("disabled", "This account has been deactivated. Contact your administrator.", status=403)
    if user.company_id and not user.company.is_active:
        raise AuthError("company_disabled", "Your company's access has been suspended. Contact your administrator.", status=403)
    LoginAttempt.objects.filter(email=email).delete()
    return tokens.start_session(user, "password", user_agent)


def change_password(user: User, current: str, new: str, keep_session: str | None) -> None:
    """Change your own password; signs out every other device."""
    from core.services.auth.passwords import set_password

    if user.has_usable_password() and not user.check_password(current):
        raise AuthError("wrong_password", "Current password is incorrect", status=400)
    set_password(user, new)
    user.save(update_fields=["password", "updated_at"])
    tokens.revoke_user_sessions(user.id, "password_changed", keep=keep_session)

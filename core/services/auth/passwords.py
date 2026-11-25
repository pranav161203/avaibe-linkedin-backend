"""Password rules and storage.

Passwords are never encrypted (encryption can be reversed by whoever holds the key). They are hashed one way with
Argon2id and a random salt per password, through Django's hasher (settings.PASSWORD_HASHERS). Checking a password
hashes what was typed and compares in constant time. The plain password is never logged or stored.
"""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from core.models import User
from core.services.auth import AuthError

MAX_LENGTH = 128  # Argon2 accepts longer, but a cap stops someone sending megabytes to hash


def check_rules(password: str, user: User | None = None) -> None:
    """Raise AuthError("weak_password") with every rule it breaks (length, too common, all numbers, like the email)."""
    if len(password) > MAX_LENGTH:
        raise AuthError("weak_password", f"Password must be {MAX_LENGTH} characters or fewer")
    try:
        validate_password(password, user=user)
    except ValidationError as e:
        raise AuthError("weak_password", " ".join(e.messages)) from e


def set_password(user: User, password: str) -> None:
    """Validate and store a new password (as a hash). Does not save other fields."""
    check_rules(password, user)
    user.set_password(password)

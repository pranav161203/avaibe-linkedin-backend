"""Encrypts LinkedIn access tokens at rest so a database dump doesn't expose them."""

from cryptography.fernet import Fernet, InvalidToken

from core.conf import TOKEN_ENCRYPTION_KEY


class TokenKeyError(RuntimeError):
    pass


def _fernet() -> Fernet:
    if not TOKEN_ENCRYPTION_KEY:
        raise TokenKeyError("TOKEN_ENCRYPTION_KEY is not set in backend/.env")
    try:
        return Fernet(TOKEN_ENCRYPTION_KEY.encode())
    except ValueError as e:
        raise TokenKeyError("TOKEN_ENCRYPTION_KEY is not a valid Fernet key") from e


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as e:
        raise TokenKeyError("Stored token can't be decrypted (was TOKEN_ENCRYPTION_KEY changed?)") from e

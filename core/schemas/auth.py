"""Request bodies for sign-in, sign-up, passwords, invitations and companies."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Role = Literal["viewer", "editor", "admin", "superadmin"]


def _clean_email(v: str) -> str:
    v = v.strip().lower()
    if "@" not in v or v.startswith("@") or v.endswith("@") or " " in v:
        raise ValueError("Enter a valid email address")
    return v


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return v.strip().lower()


class SignupIn(BaseModel):
    """Accepting an invitation: the link's token, your name and a password."""

    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=10, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=256)


class PasswordResetRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _clean_email(v)


class PasswordResetIn(BaseModel):
    """Choosing a new password from a reset link."""

    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current: str = Field(default="", max_length=256)  # empty when the account has no password yet (Microsoft only)
    new: str = Field(min_length=1, max_length=256)


class InviteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    role: Role = "viewer"
    can_switch_accounts: bool = False

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _clean_email(v)


class CompanyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=200)
    website: str | None = Field(default=None, max_length=300, pattern=r"^https?://\S+$")
    country: str = Field(default="AE", pattern=r"^[A-Z]{2}$")
    industry: str | None = Field(default=None, max_length=120)


class CompanyUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=2, max_length=200)
    website: str | None = Field(default=None, max_length=300, pattern=r"^https?://\S+$")
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    industry: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None
    default_account_id: int | None = None

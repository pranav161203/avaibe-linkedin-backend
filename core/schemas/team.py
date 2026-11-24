"""Request bodies for the Team page."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Role = Literal["viewer", "editor", "admin", "superadmin"]

class MemberIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    name: str | None = Field(default=None, max_length=200)
    role: Role = "viewer"
    can_switch_accounts: bool = False
    active: bool = True

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or v.startswith("@") or v.endswith("@") or " " in v:
            raise ValueError("Enter a valid work email address")
        return v

class DefaultAccountIn(BaseModel):
    default_account_id: int

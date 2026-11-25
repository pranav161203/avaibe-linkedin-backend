"""People who use the app. Sign-in state (sessions, tokens, invitations) lives in auth_tokens.py, not here."""

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models

from core.models.base import Audited
from core.models.choices import ROLE_CHOICES


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email: str, password: str | None = None, **extra):
        if not email:
            raise ValueError("An email is required")
        user = self.model(email=email.strip().lower(), **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()  # Microsoft sign-in only
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str | None = None, **extra):
        """A platform super admin (no company). Used by `manage.py createsuperuser` for the very first one."""
        extra.setdefault("role", "superadmin")
        extra.setdefault("can_switch_accounts", True)
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, Audited):
    """A person who can sign in (invite-only), with email + password and/or Microsoft.

    - password: Django's hasher field. Argon2id one-way hash with a per-user random salt (see PASSWORD_HASHERS);
      never encrypted and never readable back. Unusable ("!...") for people who only use Microsoft.
    - company: the company they belong to. Empty only for super admins, who run the platform across companies.
    - created_by / updated_by / created_at / updated_at: from Audited (created_by is who invited them).
    """

    email = models.EmailField(max_length=320, unique=True)
    name = models.CharField(max_length=200, null=True, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="viewer")
    # People without this (and not admins) only see the default account and get no switcher
    can_switch_accounts = models.BooleanField(default=False)
    company = models.ForeignKey(
        "core.Company", on_delete=models.PROTECT, null=True, blank=True, related_name="users", db_column="company_id"
    )
    is_active = models.BooleanField(default=True)

    objects = UserManager()
    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        db_table = "users"
        ordering = ["email"]
        constraints = [
            # Everyone except a super admin belongs to a company
            models.CheckConstraint(
                condition=models.Q(role="superadmin") | models.Q(company__isnull=False), name="user_company_unless_superadmin"
            )
        ]

    def __str__(self) -> str:
        return self.name or self.email

    # The raw database screens (/admin) can change anything, roles included, so only super admins get in
    @property
    def is_staff(self) -> bool:
        return self.is_active and self.role == "superadmin"

    @property
    def is_superuser(self) -> bool:
        return self.is_staff

    def has_perm(self, perm, obj=None) -> bool:
        return self.is_staff

    def has_perms(self, perm_list, obj=None) -> bool:
        return self.is_staff

    def has_module_perms(self, app_label) -> bool:
        return self.is_staff


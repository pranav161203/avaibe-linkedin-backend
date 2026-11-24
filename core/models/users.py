"""People who use the app, and in-progress Microsoft sign-ins."""

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models

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
        """For local admin access while Microsoft sign-in isn't configured."""
        extra.setdefault("role", "admin")
        extra.setdefault("can_switch_accounts", True)
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser):
    """A team member (invite-only). In production, identity comes from Microsoft sign-in."""

    email = models.EmailField(max_length=320, unique=True)
    name = models.CharField(max_length=200, null=True, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="viewer")
    # People without this (and not admins) only see the default account and get no switcher
    can_switch_accounts = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()
    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        db_table = "users"
        ordering = ["email"]

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


class AuthFlow(models.Model):
    """In-progress Microsoft sign-in (state, nonce, PKCE verifier), consumed once by the callback."""

    state = models.CharField(max_length=128, primary_key=True)
    flow = models.JSONField()
    created_at = models.DateTimeField()

    class Meta:
        db_table = "auth_flows"

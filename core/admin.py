"""Django admin: browse and fix data without building screens. Access is limited to super admins."""

from django.contrib import admin

from core.models import (
    Account,
    AIRun,
    AuthSession,
    Company,
    CompanySetting,
    Invitation,
    LinkedInConnection,
    PageAudience,
    PlannedPost,
    Post,
    PostAudience,
    Snapshot,
    User,
)


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "kind", "is_test", "linkedin_url", "created_at")
    list_filter = ("company", "kind", "is_test")
    search_fields = ("name", "linkedin_url")


class SnapshotInline(admin.TabularInline):
    model = Snapshot
    extra = 0
    fields = ("checkpoint", "captured_at", "impressions", "reactions", "comments", "reposts", "clicks", "followers_gained")


class AudienceInline(admin.TabularInline):
    model = PostAudience
    extra = 0
    fields = ("dimension", "value", "pct", "captured_at")


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("topic", "account", "format", "published_at", "author")
    list_filter = ("account", "format")
    search_fields = ("topic", "caption", "post_url", "author")
    date_hierarchy = "published_at"
    inlines = [SnapshotInline, AudienceInline]


@admin.register(PageAudience)
class PageAudienceAdmin(admin.ModelAdmin):
    list_display = ("account", "as_of", "audience", "dimension", "value", "count", "pct")
    list_filter = ("account", "audience", "dimension")
    date_hierarchy = "as_of"


@admin.register(PlannedPost)
class PlannedPostAdmin(admin.ModelAdmin):
    list_display = ("account", "status", "scheduled_at", "topic", "published_at")
    list_filter = ("status", "account")
    search_fields = ("caption", "topic")


@admin.register(LinkedInConnection)
class LinkedInConnectionAdmin(admin.ModelAdmin):
    list_display = ("account", "name", "expires_at", "connected_at")
    # Never show or edit the (encrypted) token here
    exclude = ("access_token_enc",)
    readonly_fields = ("member_urn", "scopes", "expires_at", "connected_at")


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "name", "company", "role", "can_switch_accounts", "is_active", "last_login")
    list_filter = ("role", "is_active", "can_switch_accounts", "company")
    search_fields = ("email", "name")
    exclude = ("password",)  # hashes only; passwords are set by the person, never here
    readonly_fields = ("last_login", "created_at", "created_by", "updated_at", "updated_by")


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "country", "is_active", "created_at", "created_by")
    list_filter = ("is_active", "country")
    search_fields = ("name", "slug")
    readonly_fields = ("created_at", "created_by", "updated_at", "updated_by")


class ReadOnlyAdmin(admin.ModelAdmin):
    """Sign-in records: look, don't edit (token hashes are useless to copy, but editing them makes no sense)."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(AuthSession)
class AuthSessionAdmin(ReadOnlyAdmin):
    list_display = ("user", "method", "created_at", "last_used_at", "expires_at", "revoked_at", "revoked_reason")
    list_filter = ("method", "revoked_reason")
    search_fields = ("user__email",)


@admin.register(Invitation)
class InvitationAdmin(ReadOnlyAdmin):
    list_display = ("email", "company", "role", "invited_by", "created_at", "expires_at", "accepted_at", "revoked_at")
    list_filter = ("role", "company")
    search_fields = ("email",)
    exclude = ("token_hash",)


@admin.register(AIRun)
class AIRunAdmin(admin.ModelAdmin):
    list_display = ("created_at", "account", "kind", "status", "model", "input_tokens", "output_tokens", "cost_usd", "created_by")
    list_filter = ("status", "kind", "model", "account")
    readonly_fields = [f.name for f in AIRun._meta.fields]


@admin.register(CompanySetting)
class CompanySettingAdmin(admin.ModelAdmin):
    list_display = ("company", "section", "updated_at", "updated_by")
    list_filter = ("company", "section")

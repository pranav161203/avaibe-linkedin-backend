"""Database models, one module per area. Everything is re-exported here, so code (and the migrations)
import from core.models as before: `from core.models import Post`.

Related lists used by the analytics code (post.snapshots, post.audience) are loaded with
Prefetch(..., to_attr=...) in core.services.analytics.performance.posts_queryset(), so the analysis code can
treat them as plain lists. The reverse managers themselves are named *_items.

Adding a model: put it in the module for its area (or a new one), add it to the imports below, then run
makemigrations. The app label stays "core", so table names don't change when a model moves between modules.
"""

from core.models.accounts import (
    PAGE_DAILY_FIELDS,
    Account,
    AccountDoc,
    PageAudience,
    PageDaily,
)
from core.models.ai import AIRun
from core.models.app_settings import AppSetting
from core.models.choices import (
    AUTO_PUBLISH_FORMATS,
    CHECKPOINT_CHOICES,
    CHECKPOINT_HOURS,
    FORMAT_CHOICES,
    FORMATS,
    PLANNED_FORMATS,
    PLANNED_STATUSES,
    ROLE_CHOICES,
    ROLE_LABELS,
    ROLES,
)
from core.models.leads import Lead
from core.models.posts import (
    REF_PREFIX,
    Counter,
    Post,
    PostAudience,
    Snapshot,
    assign_missing_refs,
    next_post_ref,
)
from core.models.publishing import LinkedInConnection, OAuthState, PlannedPost
from core.models.suggestions import SuggestionDecision
from core.models.users import AuthFlow, User, UserManager

__all__ = [
    "AUTO_PUBLISH_FORMATS", "CHECKPOINT_CHOICES", "CHECKPOINT_HOURS", "FORMAT_CHOICES", "FORMATS", "PAGE_DAILY_FIELDS",
    "PLANNED_FORMATS", "PLANNED_STATUSES", "REF_PREFIX", "ROLE_CHOICES", "ROLE_LABELS", "ROLES",
    "AIRun", "Account", "AccountDoc", "AppSetting", "AuthFlow", "Counter", "Lead", "LinkedInConnection", "OAuthState",
    "PageAudience", "PageDaily", "PlannedPost", "Post", "PostAudience", "Snapshot", "SuggestionDecision", "User",
    "UserManager", "assign_missing_refs", "next_post_ref",
]

"""URLs for tests: the app's API plus the mock LinkedIn API (normally only mounted when MOCK_LINKEDIN=1)."""

from django.urls import include, path

urlpatterns = [
    path("api/", include("core.api.urls")),
    path("mock-linkedin/", include("dev_tools.mock_linkedin.urls")),
]

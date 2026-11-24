import os

from django.conf import settings
from django.contrib import admin
from django.http import HttpResponseRedirect
from django.urls import include, path

from core.conf import auth_enabled


def admin_login(request, extra_context=None):
    """With Microsoft sign-in on, the admin uses it too (admins only). In local mode, Django's normal login."""
    if auth_enabled():
        nxt = request.GET.get("next", "/admin/")
        return HttpResponseRedirect(f"/api/auth/login?next={nxt}")
    return admin.site.__class__.login(admin.site, request, extra_context)


admin.site.login = admin_login
admin.site.site_header = "avaibe · LinkedIn Intelligence admin"
admin.site.site_title = "avaibe admin"
admin.site.index_title = "Data and team"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("core.api.urls")),
]

# Local stand-in for LinkedIn's API with dummy data (dev_tools/mock_linkedin). Only when MOCK_LINKEDIN=1, never in production.
if os.environ.get("MOCK_LINKEDIN") == "1":
    urlpatterns.append(path("mock-linkedin/", include("dev_tools.mock_linkedin.urls")))

if settings.DEBUG:
    # Nothing else to serve: the React app runs separately (Vite in development)
    pass

"""Per-request state that must never carry over to the next request served by the same thread."""

from core.services import settings_store


class SettingsCompanyMiddleware:
    """Clears the company whose settings apply (core.services.settings_store) before and after each request.
    Authentication sets it from the signed-in person; check_account narrows it to the account's company."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        settings_store.use_company(None)
        try:
            return self.get_response(request)
        finally:
            settings_store.use_company(None)

"""Health check for the host (Render's healthCheckPath, Docker HEALTHCHECK, uptime monitors).

No sign-in needed and no data returned. 200 {"status": "ok"} when the app can reach its database,
503 otherwise, so the host restarts or stops routing to a broken instance.
"""

import logging

from django.db import connection
from django.http import JsonResponse

log = logging.getLogger(__name__)


def health(request):
    try:
        connection.ensure_connection()
    except Exception:
        log.exception("Health check: database unreachable")
        return JsonResponse({"status": "error", "database": "unreachable"}, status=503)
    return JsonResponse({"status": "ok"})

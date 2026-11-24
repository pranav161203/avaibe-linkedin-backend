"""Request ID and access log.

Every request gets an ID: the caller's X-Request-ID when it sends a sensible one (a proxy, or the React app),
otherwise a new one. It is returned in the X-Request-ID response header and added to every log line written
while the request runs (see LOGGING in config/settings/base.py), so one request's lines can be found together.
One INFO line per API call is written to the "core.request" logger: method, path, status and duration.
"""

import logging
import re
import time
import uuid
from contextvars import ContextVar

request_id: ContextVar[str] = ContextVar("request_id", default="-")
log = logging.getLogger("core.request")
VALID_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")  # never trust a header blindly: it ends up in logs


class RequestIDLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        return True


class RequestIDMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.headers.get("X-Request-ID", "")
        rid = incoming if VALID_ID.match(incoming) else uuid.uuid4().hex[:16]
        token = request_id.set(rid)
        request.request_id = rid
        start = time.perf_counter()
        try:
            response = self.get_response(request)
            response["X-Request-ID"] = rid
            if request.path.startswith("/api/"):
                ms = round((time.perf_counter() - start) * 1000)
                log.info("%s %s %s %dms", request.method, request.path, response.status_code, ms)
            return response
        finally:
            request_id.reset(token)

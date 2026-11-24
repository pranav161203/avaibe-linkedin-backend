"""Small helpers shared by the API views: errors, request validation, response shape.

Errors keep the shape the React app expects: {"detail": "..."} with an HTTP status.
Request bodies are validated with the Pydantic schemas in core/schemas.py (422 on invalid input).
"""


from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler as drf_exception_handler


class ApiError(APIException):
    def __init__(self, status_code: int, detail):
        self.status_code = status_code
        super().__init__(detail)
        # APIException wraps strings/lists; keep plain structures for the client
        self.detail = detail


def fail(status_code: int, detail) -> None:
    raise ApiError(status_code, detail)


def exception_handler(exc, context):
    resp = drf_exception_handler(exc, context)
    if resp is not None and isinstance(exc, ApiError):
        resp.data = {"detail": exc.detail}
    elif resp is not None and isinstance(resp.data, dict) and "detail" in resp.data:
        resp.data = {"detail": str(resp.data["detail"])}
    return resp


NO_CONTENT = status.HTTP_204_NO_CONTENT

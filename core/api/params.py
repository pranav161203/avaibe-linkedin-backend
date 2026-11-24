"""Reading request input: JSON bodies validated with core/schemas (422 with field errors) and query parameters."""

from typing import TypeVar

from pydantic import BaseModel, ValidationError

from core.api.errors import fail

M = TypeVar("M", bound=BaseModel)

def parse(schema: type[M], data) -> M:
    """Validate a request body with a Pydantic schema; 422 with field errors if invalid."""
    if not isinstance(data, dict):
        fail(422, "Expected a JSON object")
    try:
        return schema.model_validate(data)
    except ValidationError as e:
        fail(422, [{"loc": list(err.get("loc", ())), "msg": err.get("msg", "Invalid value")} for err in e.errors()])

def int_param(request, name: str, default: int | None = None, required: bool = False) -> int | None:
    raw = request.query_params.get(name)
    if raw in (None, ""):
        if required:
            fail(422, f"Missing query parameter '{name}'")
        return default
    try:
        return int(raw)
    except ValueError:
        fail(422, f"'{name}' must be a number")

def choice_param(request, name: str, options: set[str] | list[str], default: str) -> str:
    v = request.query_params.get(name, default)
    if v not in options:
        fail(422, f"'{name}' must be one of {sorted(options)}")
    return v

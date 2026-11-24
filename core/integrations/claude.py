"""Anthropic (Claude) API: client, error translation, pricing and token accounting.

The only module that talks to the Anthropic SDK directly. Feature logic (prompts, limits, stored runs) lives in
core/services/ai/. The API key stays server-side (ANTHROPIC_API_KEY); the model is CLAUDE_MODEL.

Usage in a service:

    from core.integrations import claude

    if not claude.configured():
        raise claude.AIError("Claude isn't connected yet ...")
    with claude.api_errors():
        resp = claude.client().messages.parse(model=CLAUDE_MODEL, ...)

Call these through the module (claude.configured(), not an imported name), so tests can patch them in one place.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

from core.conf import ANTHROPIC_API_KEY

# USD per million tokens (input, output). Thinking tokens are billed as output.
PRICES = {
    "claude-opus-5-5": (Decimal("4"), Decimal("20")),
    "claude-sonnet-5-5": (Decimal("2"), Decimal("10")),
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50")),
}

RATE_LIMITED = "Claude's usage limit was reached. Try again in a minute."


class AIError(Exception):
    """Shown to the user as-is."""


def configured() -> bool:
    return bool(ANTHROPIC_API_KEY)


def client(timeout: float = 180.0):
    """An Anthropic client with the server's key. Imported lazily: the SDK is only needed when Claude is used."""
    import anthropic

    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=timeout, max_retries=2)


@contextmanager
def api_errors(rate_limited: str = RATE_LIMITED, bad_request: str = "Claude rejected the request: {message}") -> Iterator[None]:
    """Turn the SDK's exceptions into AIError with a message the team can act on."""
    import anthropic

    try:
        yield
    except anthropic.AuthenticationError:
        raise AIError("The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in server/.env.")
    except anthropic.PermissionDeniedError:
        raise AIError("The API key doesn't have permission for this model.")
    except anthropic.RateLimitError:
        raise AIError(rate_limited)
    except anthropic.BadRequestError as e:
        raise AIError(bad_request.format(message=e.message))
    except anthropic.APIConnectionError:
        raise AIError("Couldn't reach Claude. Check the internet connection and try again.")
    except anthropic.APIStatusError as e:
        raise AIError(f"Claude is unavailable right now (HTTP {e.status_code}). Try again shortly.")


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    pin, pout = PRICES.get(model, PRICES["claude-opus-5-5"])
    return (pin * input_tokens + pout * output_tokens) / Decimal(1_000_000)


def billed_input_tokens(usage) -> int:
    """Input tokens weighted by price: cache writes cost 1.25x, cache reads 0.1x (so the stored cost stays honest)."""
    written = getattr(usage, "cache_creation_input_tokens", 0) or 0
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    return round(usage.input_tokens + 1.25 * written + 0.1 * read)

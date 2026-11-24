"""Client for LinkedIn's Community Management API (versioned REST, Rest.li 2.0).

The base URL comes from LINKEDIN_API_BASE: https://api.linkedin.com for the real API, or the local mock
(http://127.0.0.1:8002/mock-linkedin) while there is no API access. Everything else is identical, so code tested
against the mock works unchanged on the real API.

Rest.li 2.0 encoding: URNs inside List(…) and path segments are URL-encoded; the structure itself
(parentheses, commas, colons between keys) is sent as-is.
"""

import os
from urllib.parse import quote

import httpx

DEFAULT_BASE = "https://api.linkedin.com"


class LinkedInAPIError(Exception):
    def __init__(self, status: int, body):
        self.status = status
        self.body = body
        msg = body.get("message") if isinstance(body, dict) else str(body)[:200]
        super().__init__(f"LinkedIn API {status}: {msg}")


def enc(urn: str) -> str:
    return quote(urn, safe="")


def rl_list(urns) -> str:
    return "List(" + ",".join(enc(u) for u in urns) + ")"


def rl_time(start_ms: int, end_ms: int, granularity: str = "DAY") -> str:
    return f"(timeRange:(start:{start_ms},end:{end_ms}),timeGranularityType:{granularity})"


def rl_date_range(start, end) -> str:
    return f"(start:(day:{start.day},month:{start.month},year:{start.year}),end:(day:{end.day},month:{end.month},year:{end.year}))"


class LinkedInAPI:
    def __init__(self, token: str, base: str | None = None, version: str | None = None, timeout: float = 30):
        self.base = (base or os.environ.get("LINKEDIN_API_BASE") or DEFAULT_BASE).rstrip("/")
        self.version = version or os.environ.get("LINKEDIN_API_VERSION", "202611")
        self.token = token
        self.calls = 0
        self.http = httpx.Client(timeout=timeout)

    @property
    def is_mock(self) -> bool:
        return "mock-linkedin" in self.base

    def get(self, path: str, query: str = "") -> dict:
        """path like '/rest/posts' (already encoded segments); query already in Rest.li form."""
        url = f"{self.base}{path}" + (f"?{query}" if query else "")
        self.calls += 1
        r = self.http.get(url, headers={
            "Authorization": f"Bearer {self.token}",
            "Linkedin-Version": self.version,
            "X-Restli-Protocol-Version": "2.0.0",
        })
        try:
            body = r.json()
        except ValueError:
            body = r.text
        if r.status_code >= 400:
            raise LinkedInAPIError(r.status_code, body)
        return body

    def all_pages(self, path: str, query: str, count: int = 100) -> list[dict]:
        out, start = [], 0
        while True:
            page = self.get(path, f"{query}&count={count}&start={start}")
            els = page.get("elements", [])
            out.extend(els)
            if len(els) < count or not page.get("paging", {}).get("links"):
                return out
            start += count

    def close(self):
        self.http.close()

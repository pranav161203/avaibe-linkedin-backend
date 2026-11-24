"""Thin client for the LinkedIn endpoints this app is allowed to use with
"Share on LinkedIn" + "Sign In with LinkedIn using OpenID Connect":

- OAuth 2.0 authorisation-code flow and the OpenID userinfo endpoint
- Images API (initializeUpload) and Posts API, posting as the member (w_member_social)

No analytics endpoints: those need products this app doesn't have.
"""

import re
import secrets
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

import httpx

from core.conf import (
    LINKEDIN_API_VERSION,
    LINKEDIN_CLIENT_ID,
    LINKEDIN_CLIENT_SECRET,
    LINKEDIN_REDIRECT_URI,
    LINKEDIN_SCOPES,
)

AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
REST = "https://api.linkedin.com/rest"
TIMEOUT = httpx.Timeout(30.0)


class LinkedInError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"LinkedIn API error {status}: {message}")
        self.status = status
        self.message = message


class LinkedInBusy(LinkedInError):
    """LinkedIn is overloaded or throttling us (429 / 5xx). Temporary: try again later.

    retry_after: seconds LinkedIn asked us to wait (Retry-After header), if it said.
    not_processed: True when the status guarantees the request was NOT carried out
    (429 throttled, 503 unavailable), so retrying can't create a duplicate post.
    """

    def __init__(self, status: int, message: str, retry_after: int | None = None):
        super().__init__(status, message)
        self.retry_after = retry_after
        self.not_processed = status in (429, 503)


def _retry_after(r: httpx.Response) -> int | None:
    """Retry-After is either seconds or an HTTP date."""
    v = (r.headers.get("retry-after") or "").strip()
    if not v:
        return None
    if v.isdigit():
        return int(v)
    try:
        when = parsedate_to_datetime(v)
        return max(0, int((when - datetime.now(timezone.utc)).total_seconds()))
    except (TypeError, ValueError):
        return None


def _check(r: httpx.Response) -> httpx.Response:
    if r.status_code >= 400:
        try:
            data = r.json()
            msg = data.get("message") or data.get("error_description") or data.get("error") or r.text
        except ValueError:
            msg = r.text
        if r.status_code == 429 or r.status_code >= 500:
            raise LinkedInBusy(r.status_code, str(msg)[:500], _retry_after(r))
        raise LinkedInError(r.status_code, str(msg)[:500])
    return r


# ------------------------------------------------------------------ OAuth


def new_state() -> str:
    return secrets.token_urlsafe(32)


def authorization_url(state: str) -> str:
    return AUTH_URL + "?" + urlencode(
        {
            "response_type": "code",
            "client_id": LINKEDIN_CLIENT_ID,
            "redirect_uri": LINKEDIN_REDIRECT_URI,
            "state": state,
            "scope": LINKEDIN_SCOPES,
        }
    )


def exchange_code(code: str) -> dict:
    """Returns {access_token, expires_at (aware UTC), scope}."""
    r = _check(
        httpx.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": LINKEDIN_CLIENT_ID,
                "client_secret": LINKEDIN_CLIENT_SECRET,
                "redirect_uri": LINKEDIN_REDIRECT_URI,
            },
            timeout=TIMEOUT,
        )
    )
    data = r.json()
    return {
        "access_token": data["access_token"],
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=int(data.get("expires_in", 0))),
        "scope": data.get("scope"),
    }


def userinfo(token: str) -> dict:
    """OpenID Connect userinfo: sub, name, email, picture."""
    r = _check(httpx.get(USERINFO_URL, headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT))
    return r.json()


# ------------------------------------------------------------------ posting


def _rest_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "LinkedIn-Version": LINKEDIN_API_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }


# Characters with special meaning in the Posts API "little text" format
_RESERVED = set("\\|{}@[]()<>#*_~")
_HASHTAG = re.compile(r"(?<![\w&#])#(\w+)")


def _escape(text: str) -> str:
    return "".join("\\" + c if c in _RESERVED else c for c in text)


def to_commentary(text: str) -> str:
    """Escape reserved characters so text is posted exactly as written, and turn
    #tags into real hashtags ({hashtag|\\#|tag}) so they stay clickable."""
    out: list[str] = []
    pos = 0
    for m in _HASHTAG.finditer(text):
        out.append(_escape(text[pos : m.start()]))
        out.append("{hashtag|\\#|" + _escape(m.group(1)) + "}")
        pos = m.end()
    out.append(_escape(text[pos:]))
    return "".join(out)


def upload_image(token: str, owner_urn: str, data: bytes) -> str:
    """Upload an image and return its urn:li:image:... id."""
    r = _check(
        httpx.post(
            f"{REST}/images?action=initializeUpload",
            headers=_rest_headers(token),
            json={"initializeUploadRequest": {"owner": owner_urn}},
            timeout=TIMEOUT,
        )
    )
    value = r.json()["value"]
    _check(
        httpx.put(
            value["uploadUrl"],
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"},
            content=data,
            timeout=httpx.Timeout(120.0),
        )
    )
    return value["image"]


def create_post(
    token: str,
    author_urn: str,
    text: str,
    visibility: str = "PUBLIC",
    image_urn: str | None = None,
    image_alt: str | None = None,
) -> str:
    """Publish a post and return its URN (urn:li:share:... or urn:li:ugcPost:...)."""
    body: dict = {
        "author": author_urn,
        "commentary": to_commentary(text),
        "visibility": visibility,
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    if image_urn:
        media: dict = {"id": image_urn}
        if image_alt:
            media["altText"] = image_alt
        body["content"] = {"media": media}
    r = _check(httpx.post(f"{REST}/posts", headers=_rest_headers(token), json=body, timeout=TIMEOUT))
    urn = r.headers.get("x-restli-id") or r.headers.get("x-linkedin-id")
    if not urn:
        raise LinkedInError(r.status_code, "Post created but LinkedIn returned no post id")
    return urn


def post_url(urn: str) -> str:
    return f"https://www.linkedin.com/feed/update/{urn}/"

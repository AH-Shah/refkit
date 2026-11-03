"""HTTP GET with retries, per-host rate limiting and clear errors (standard library only)."""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__
from .errors import FetchError, NotFound

HOMEPAGE = "https://github.com/AH-Shah/refkit"
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}
# Minimum seconds between requests to one host. arXiv's API terms ask for one request every 3 s.
MIN_INTERVAL = {"export.arxiv.org": 3.0, "127.0.0.1": 0.0, "localhost": 0.0}
DEFAULT_INTERVAL = 1.0

_contact: str | None = None
_last: dict[str, float] = {}


def configure(email: str | None) -> None:
    """Contact address sent to Crossref / OpenAlex (their 'polite pool')."""
    global _contact
    _contact = email or None


def contact() -> str | None:
    return _contact


def user_agent() -> str:
    return f"refkit/{__version__} ({HOMEPAGE}" + (f"; mailto:{_contact}" if _contact else "") + ")"


def _throttle(host: str) -> None:
    gap = MIN_INTERVAL.get(host, DEFAULT_INTERVAL)
    wait = _last.get(host, 0.0) + gap - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last[host] = time.monotonic()


def _retry_after(err: urllib.error.HTTPError) -> float | None:
    v = err.headers.get("Retry-After") if err.headers else None
    try:
        return min(float(v), 120.0) if v else None
    except ValueError:
        return None


def get(url: str, accept: str | None = None, tries: int = 4, timeout: float = 60) -> str:
    """Body of `url` as text. Raises NotFound on 404/410, FetchError on any other failure after `tries` attempts."""
    headers = {"User-Agent": user_agent()}
    if accept:
        headers["Accept"] = accept
    host = urllib.parse.urlsplit(url).hostname or ""
    last = "no attempt made"
    for attempt in range(tries):
        _throttle(host)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                raise NotFound(f"{url}: HTTP {e.code} (no such record)") from None
            if e.code not in RETRY_STATUS:
                raise FetchError(f"{url}: HTTP {e.code} {e.reason}") from None
            last, wait = f"HTTP {e.code} {e.reason}", _retry_after(e) or (15 if e.code == 429 else 3) * (attempt + 1)
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
            last, wait = str(getattr(e, "reason", e)), 3 * (attempt + 1)
        if attempt < tries - 1:
            time.sleep(wait)
    raise FetchError(f"{url}: {last} (gave up after {tries} attempts)")


def get_json(url: str, accept: str | None = None, tries: int = 4):
    text = get(url, accept, tries)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise FetchError(f"{url}: response is not valid JSON") from None


def quote_doi(doi: str) -> str:
    return urllib.parse.quote(doi, safe="/")

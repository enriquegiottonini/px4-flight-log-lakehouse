"""Polite HTTP helpers for the PX4 Flight Review API (stdlib only).

Retry policy mirrors PX4's own app/download_logs.py (CLAUDE.md section 3.4):
- 503: wait Retry-After, or 30 * 2**attempt seconds (capped at 300)
- 403 / 444: we've been blocked; abort everything
- 404: not retried, returned to the caller
- anything else: retried, at most 5 attempts
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

INDEX_URL = "https://review.px4.io/dbinfo"
USER_AGENT = "px4-lakehouse-student-project/0.1 (+educational, low volume)"
MAX_ATTEMPTS = 5
CHUNK = 1 << 16


class BlockedError(RuntimeError):
    """PX4 answered 403/444: stop all requests."""


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes = b""


def _backoff(attempt: int, retry_after: str | None) -> float:
    if retry_after and retry_after.isdigit():
        return float(retry_after)
    return min(30 * 2**attempt, 300)


def request(url: str, method: str = "GET", headers: dict[str, str] | None = None,
            dest: Path | None = None, timeout: float = 300) -> Response:
    """Send a request with PX4's retry rules.

    With `dest`, a 200 body is streamed to that file instead of kept in memory.
    304 and 404 come back as normal responses; the caller decides what they mean.
    """
    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
    for attempt in range(MAX_ATTEMPTS):
        req = urllib.request.Request(url, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status, resp_headers = resp.status, {k.lower(): v for k, v in resp.headers.items()}
                if dest is not None and method == "GET":
                    tmp = dest.with_suffix(dest.suffix + ".part")
                    with open(tmp, "wb") as f:
                        while chunk := resp.read(CHUNK):
                            f.write(chunk)
                    tmp.replace(dest)
                    return Response(status, resp_headers)
                return Response(status, resp_headers, resp.read() if method == "GET" else b"")
        except urllib.error.HTTPError as e:
            resp_headers = {k.lower(): v for k, v in e.headers.items()}
            if e.code in (304, 404):
                return Response(e.code, resp_headers)
            if e.code in (403, 444):
                raise BlockedError(f"PX4 blocked us ({e.code}) on {url}") from e
            wait = _backoff(attempt, resp_headers.get("retry-after")) if e.code == 503 else 10
            print(f"  HTTP {e.code} on {url}; retry {attempt + 1}/{MAX_ATTEMPTS} in {wait:.0f}s")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            wait = 10
            print(f"  {type(e).__name__} on {url}: {e}; retry {attempt + 1}/{MAX_ATTEMPTS} in {wait}s")
        time.sleep(wait)
    raise RuntimeError(f"giving up on {url} after {MAX_ATTEMPTS} attempts")

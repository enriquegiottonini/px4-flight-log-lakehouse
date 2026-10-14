"""Polite HTTP client for the PX4 Flight Review API (stdlib only).

Retry policy mirrors PX4's app/download_logs.py (CLAUDE.md section 3.4):
- 503: wait Retry-After, or 30 * 2**attempt seconds (capped at 300)
- 403 / 444: we've been blocked -> BlockedError, abort the whole run
- 304 / 404: returned to the caller (not errors here)
- anything else: retried, at most 5 attempts
"""

from __future__ import annotations

import hashlib
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

USER_AGENT = "px4-lakehouse-student-project/0.1 (+educational, low volume)"
MAX_ATTEMPTS = 5
CHUNK = 1 << 16

log = logging.getLogger(__name__)


class BlockedError(RuntimeError):
    """PX4 answered 403/444: stop all requests."""


@dataclass
class Response:
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    bytes_written: int = 0
    sha256: str | None = None


def _backoff(attempt: int, retry_after: str | None) -> float:
    if retry_after and retry_after.isdigit():
        return float(retry_after)
    return min(30 * 2**attempt, 300)


def request(url: str, method: str = "GET", headers: dict[str, str] | None = None,
            dest: Path | None = None, timeout: float = 300, sleep=time.sleep) -> Response:
    """Send a request with PX4's retry rules.

    With `dest`, a 200 body is streamed to that file (written atomically) and its size and
    sha256 are returned. Without `dest`, the body is discarded (HEAD-like usage).
    """
    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
    for attempt in range(MAX_ATTEMPTS):
        req = urllib.request.Request(url, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = Response(resp.status, {k.lower(): v for k, v in resp.headers.items()})
                if dest is not None and method == "GET":
                    digest, tmp = hashlib.sha256(), dest.with_suffix(dest.suffix + ".part")
                    with open(tmp, "wb") as f:
                        while chunk := resp.read(CHUNK):
                            f.write(chunk)
                            digest.update(chunk)
                            result.bytes_written += len(chunk)
                    tmp.replace(dest)
                    result.sha256 = digest.hexdigest()
                return result
        except urllib.error.HTTPError as e:
            resp_headers = {k.lower(): v for k, v in e.headers.items()}
            if e.code in (304, 404):
                return Response(e.code, resp_headers)
            if e.code in (403, 444):
                raise BlockedError(f"PX4 blocked us ({e.code}) on {url}") from e
            wait = _backoff(attempt, resp_headers.get("retry-after")) if e.code == 503 else 10
            log.warning("HTTP %s on %s; retry %d/%d in %.0fs", e.code, url, attempt + 1, MAX_ATTEMPTS, wait)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            wait = 10
            log.warning("%s on %s: %s; retry %d/%d in %ds", type(e).__name__, url, e, attempt + 1, MAX_ATTEMPTS, wait)
        sleep(wait)
    raise RuntimeError(f"giving up on {url} after {MAX_ATTEMPTS} attempts")

"""Download the PX4 log index with a conditional GET.

The first run downloads ~32 MB. Later runs send the saved ETag as If-None-Match;
the CDN answers 304 (empty body) until PX4 regenerates the file (~00:01 UTC daily).

    uv run python fetch_index.py
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from px4http import INDEX_URL, request

DATA = Path(__file__).parent / "data"
INDEX_FILE = DATA / "dbinfo.json.gz"
STATE_FILE = DATA / "dbinfo.state.json"  # stands in for audit.index_snapshots


def main() -> None:
    DATA.mkdir(exist_ok=True)
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() and INDEX_FILE.exists() else {}
    headers = {"If-None-Match": state["etag"]} if "etag" in state else {}
    print(f"GET {INDEX_URL}  If-None-Match: {headers.get('If-None-Match', '(none, first run)')}")

    resp = request(INDEX_URL, headers=headers, dest=INDEX_FILE)
    if resp.status == 304:
        print(f"304 Not Modified -> 0 bytes downloaded; local copy from {state['fetched_at']} is current")
        return

    state = {
        "etag": resp.headers.get("etag"),
        "last_modified": resp.headers.get("last-modified"),
        "bytes": INDEX_FILE.stat().st_size,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    STATE_FILE.write_text(json.dumps(state, indent=2))
    print(f"{resp.status} -> {state['bytes'] / 1e6:.1f} MB saved to {INDEX_FILE.name}")
    print(f"ETag {state['etag']}  Last-Modified {state['last_modified']}")


if __name__ == "__main__":
    main()

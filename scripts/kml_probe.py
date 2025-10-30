import hashlib
import time
import sys
from datetime import datetime, timezone

import requests


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/kml_probe.py <TOKEN> [BASE_URL]")
        sys.exit(1)

    token = sys.argv[1]
    base = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000"
    url = f"{base.rstrip('/')}/api/kml/live/{token}"

    prev_hash = None
    for i in range(15):
        now = datetime.now(timezone.utc).isoformat()
        try:
            r = requests.get(url, headers={"Cache-Control": "no-cache"}, timeout=10)
            body = r.content
            chash = sha256_hex(body)
            etag = r.headers.get("ETag")
            last_mod = r.headers.get("Last-Modified")
            cache_ctrl = r.headers.get("Cache-Control")
            changed = "CHANGED" if chash != prev_hash else "same"
            print(
                f"[{now}] status={r.status_code} etag={etag} lastmod={last_mod} cache={cache_ctrl} hash={chash[:12]} {changed}"
            )
            prev_hash = chash
        except Exception as e:
            print(f"[{now}] ERROR: {e}")

        time.sleep(60)


if __name__ == "__main__":
    main()



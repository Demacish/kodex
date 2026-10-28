"""Downloads the public-domain test EPUBs listed in gutenberg.json into a
cache directory and checks them against their recorded SHA-256.

    python tools/fixtures/fetch_gutenberg.py --out ~/.cache/kodex/gutenberg

Files already present with the right checksum are not downloaded again,
and requests are spaced out as Project Gutenberg asks of robots.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

_LOCK = Path(__file__).with_name("gutenberg.json")
_USER_AGENT = "kodex-test-fixtures (+https://github.com/; a handful of files for tests)"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--accept-changed", action="store_true", help="record new checksums instead of failing")
    args = parser.parse_args()

    lock = json.loads(_LOCK.read_text())
    args.out.mkdir(parents=True, exist_ok=True)
    changed = False
    failures = 0
    for book in lock["books"]:
        target = args.out / f"pg{book['id']}.epub"
        if target.is_file() and _sha256(target) == book["sha256"]:
            continue
        request = urllib.request.Request(lock["url"].format(id=book["id"]), headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            target.write_bytes(response.read())
        time.sleep(2)
        digest = _sha256(target)
        if digest != book["sha256"]:
            if args.accept_changed:
                book["sha256"] = digest
                changed = True
                print(f"pg{book['id']}: checksum updated")
            else:
                failures += 1
                print(f"pg{book['id']}: checksum {digest} differs from gutenberg.json", file=sys.stderr)
        print(f"pg{book['id']}.epub  {book['title']} ({book['language']})")
    if changed:
        _LOCK.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

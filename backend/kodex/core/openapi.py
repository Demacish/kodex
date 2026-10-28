"""Writes the API's OpenAPI document (ADR 0013), from which the clients are
generated: ``python -m kodex.core.openapi ../web/openapi.json``. CI checks
that the committed copy is current."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def document() -> str:
    from app.main import app

    return json.dumps(app.openapi(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    text = document()
    if not argv:
        sys.stdout.write(text)
    else:
        Path(argv[0]).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

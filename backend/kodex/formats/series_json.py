"""``series.json`` in a series folder, in Mylar3's format (v1.0.2: a
``version`` and a ``metadata`` block that Mylar, Kapowarr and Komga's
plugins read) together with Kodex's own backup of the series' books (v1's
keys, read back by app/scanning/series_json.py's import). One file serves
both: each reader takes its own keys."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MYLAR_VERSION = "1.0.2"
_BOOKTYPE = {"collected": "TPB", "issue": "Print", "annual": "Print", "one_shot": "One-Shot", "manga": "Print"}
_STATUS = {"ongoing": "Continuing", "continuing": "Continuing", "ended": "Ended", "completed": "Ended",
           "finished": "Ended", "cancelled": "Ended"}  # fmt: skip


def mylar_metadata(*, name: str, comicvine_id: str | int | None, start_year: int | None, publisher: str | None,
                   summary: str | None, format_family: str | None, status: str | None,
                   book_count: int) -> dict[str, Any]:  # fmt: skip
    return {
        "type": "comicSeries",
        "publisher": publisher,
        "imprint": None,
        "name": name,
        "comicid": int(comicvine_id) if comicvine_id is not None and str(comicvine_id).isdigit() else comicvine_id,
        "year": start_year,
        "description_text": summary,
        "description_formatted": None,
        "volume": None,
        "booktype": _BOOKTYPE.get(format_family or "", "Print"),
        "age_rating": None,
        "collects": None,
        "ComicImage": None,
        "total_issues": book_count,
        "publication_run": None,
        "status": _STATUS.get((status or "").lower()),
    }


def merge(kodex_backup: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    return {"version": MYLAR_VERSION, "metadata": metadata, **kodex_backup}


def read(path: Path) -> dict[str, Any]:
    """The file's contents, or {} when it is missing or not JSON."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return {}
    return data if isinstance(data, dict) else {}

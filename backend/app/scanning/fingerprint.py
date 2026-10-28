"""KOReader's document id for a book file; see kodex.formats.identity,
which also has Kodex's own content id."""

from __future__ import annotations

from pathlib import Path

from app.models.enums import BookFormat
from kodex.formats.identity import image_folder_fingerprint, koreader_partial_md5
from kodex.formats.identity import koreader_id as _koreader_id

__all__ = ["book_fingerprint", "image_folder_fingerprint", "koreader_partial_md5"]


def book_fingerprint(path: Path, file_format: BookFormat) -> str:
    return _koreader_id(path, file_format)

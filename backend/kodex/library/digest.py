"""A book file's SHA-256, for apps that verify what they downloaded:
taken the first time it is asked for and kept until the file changes (its
size or modification time)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.models.book import Book

_CHUNK = 1 << 20


def _of(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def sha256(book: Book, path: Path) -> str:
    """The file's digest, from the book when it is still the same file.
    Sets the book's columns (the caller commits)."""
    stamp = _of(path)
    if book.file_sha256 and book.file_sha256_of == stamp:
        return book.file_sha256
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    book.file_sha256, book.file_sha256_of = digest.hexdigest(), stamp
    return book.file_sha256

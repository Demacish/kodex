"""Pages for the image reader (ADR 0010): a page as it is stored, or
re-encoded by pyvips to WebP, narrower (``max_width``, the knob OPDS-PSE
uses too) and/or with its blank margins trimmed. OPDS-PSE clients get JPEG
instead (``encoding="jpeg"``): not all of them show WebP. Widths round up
to a few steps, and re-encoded pages are kept on disk under
``covers_dir/pages/<book id>/<content>``, keyed by the book's content, so a
changed file gets new ones and an unchanged one is encoded once."""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.models.book import Book
from kodex.formats import archive

logger = logging.getLogger(__name__)

WIDTHS = (480, 720, 1080, 1440, 1920, 2560, 3840)
_SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF8", "image/gif"),
    (b"RIFF", "image/webp"),
)
_TRIM_THRESHOLD = 24
_TRIM_KEEPS = 0.5  # trimming never cuts a page below half its width or height
# What every image viewer shows; anything else is re-encoded for "jpeg".
_CLASSIC = ("image/jpeg", "image/png", "image/gif")
Encoding = Literal["webp", "jpeg"]
_TYPES = {"webp": "image/webp", "jpeg": "image/jpeg"}


@dataclass(frozen=True)
class Page:
    data: bytes
    media_type: str
    etag: str


def media_type(data: bytes) -> str | None:
    """The type of an image a browser shows as it is, from its first bytes."""
    for signature, kind in _SIGNATURES:
        if data.startswith(signature):
            if kind == "image/webp" and data[8:12] != b"WEBP":
                return None
            return kind
    if data[4:12] in (b"ftypavif", b"ftypavis"):
        return "image/avif"
    return None


def step_width(max_width: int) -> int:
    return next((w for w in WIDTHS if w >= max_width), WIDTHS[-1])


def content_key(book: Book, path: Path) -> str:
    if book.content_id:
        return book.content_id[:20]
    stat = path.stat()
    return hashlib.sha256(f"{stat.st_mtime_ns}-{stat.st_size}".encode()).hexdigest()[:20]


def read_page(book: Book, path: Path, index: int) -> bytes:
    from app.scanning.archive import open_book  # configures the RAR tools from the settings

    with open_book(path, book.file_format) as pages_of:
        pages = pages_of.pages()
        if index < 0 or index >= len(pages):
            raise archive.PageOutOfRange(f"Page {index} of {len(pages)}")
        return pages_of.read(pages[index].name)


def render(data: bytes, max_width: int | None, trim: bool, encoding: Encoding = "webp") -> bytes:
    import pyvips

    image = pyvips.Image.new_from_buffer(data, "")
    if image.hasalpha():
        image = image.flatten(background=[255, 255, 255])
    if trim:
        background = image.getpoint(0, 0)
        left, top, width, height = image.find_trim(threshold=_TRIM_THRESHOLD, background=background)
        if width >= image.width * _TRIM_KEEPS and height >= image.height * _TRIM_KEEPS:
            image = image.crop(left, top, width, height)
    if max_width and image.width > max_width:
        image = image.resize(max_width / image.width, kernel="lanczos3")
    if encoding == "jpeg":
        jpeg: bytes = image.jpegsave_buffer(Q=85, strip=True, optimize_coding=True)
        return jpeg
    encoded: bytes = image.webpsave_buffer(Q=82, effort=2, strip=True)
    return encoded


def etag(book: Book, path: Path, index: int, *, max_width: int | None = None, trim: bool = False,
         encoding: Encoding = "webp") -> str:  # fmt: skip
    width = step_width(max_width) if max_width else 0
    suffix = "-jpeg" if encoding == "jpeg" else ""
    return f'"{content_key(book, path)}-{index}-{width}-{int(trim)}{suffix}"'


def page(book: Book, path: Path, index: int, cache_dir: Path, *, max_width: int | None = None,
         trim: bool = False, encoding: Encoding = "webp") -> Page:  # fmt: skip
    """Page ``index`` of ``book`` (whose file is at ``path``). Raises
    archive.PageOutOfRange and archive.ArchiveError."""
    tag = etag(book, path, index, max_width=max_width, trim=trim, encoding=encoding)
    width = step_width(max_width) if max_width else None
    data: bytes | None = None
    if width is None and not trim:
        data = read_page(book, path, index)
        kind = media_type(data)
        if kind is not None and (encoding == "webp" or kind in _CLASSIC):
            return Page(data, kind, tag)
    cached = cache_dir / str(book.id) / content_key(book, path) / f"{index}-{width or 0}-{int(trim)}.{encoding}"
    if cached.is_file():
        return Page(cached.read_bytes(), _TYPES[encoding], tag)
    encoded = render(data if data is not None else read_page(book, path, index), width, trim, encoding)
    try:
        cached.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=cached.parent, delete=False, suffix=".part") as handle:
            handle.write(encoded)
        os.replace(handle.name, cached)
    except OSError as exc:  # a read-only or full disk only costs the cache
        logger.warning("Could not cache page %s of book %s: %s", index, book.id, exc)
    return Page(encoded, _TYPES[encoding], tag)

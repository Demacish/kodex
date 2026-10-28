"""Pixel size of every page of a page-based book (CBZ/CBR/image folder),
in reading order — what the image reader needs to show a double-page
spread on its own in two-page mode, and to reserve each page's height in
scroll mode so the layout doesn't jump as images load (see
frontend ImageReader.tsx). Stored on Book.page_dimensions.

Only image headers are read (PIL's lazy open), never full decodes. CBZ
and image folders are cheap enough to do during a scan; CBR needs every
page decompressed out of the RAR first, so it's done by a background job
the first time someone opens the book (see
compute_page_dimensions_task), which also warms the reader's page cache.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

from app.models.enums import BookFormat
from app.scanning import archive

logger = logging.getLogger(__name__)

# [width, height], or None for a page whose header couldn't be read.
PageSize = list[int] | None

CHEAP_FORMATS = (BookFormat.CBZ, BookFormat.IMAGE_FOLDER)


def _size(source) -> PageSize:
    try:
        with Image.open(source) as image:
            width, height = image.size
            return [int(width), int(height)]
    except Exception:  # noqa: BLE001 - one unreadable page mustn't lose the rest
        return None


def cheap_page_dimensions(path: Path, file_format: BookFormat) -> list[PageSize] | None:
    """Sizes for CBZ/image-folder books, or None for other formats. Only
    each page's header is read."""
    if file_format not in CHEAP_FORMATS:
        return None
    sizes: list[PageSize] = []
    with archive.open_book(path, file_format) as book:
        for entry in book.pages():
            try:
                with book.open(entry.name) as handle:
                    sizes.append(_size(handle))
            except archive.ArchiveError:
                sizes.append(None)
    return sizes


def cbr_page_dimensions(
    path: Path, page_count: int, cache_dir: Path, file_format: BookFormat = BookFormat.CBR
) -> list[PageSize]:
    """Sizes for a CBR or CB7, by extracting each page into the reader's
    page cache (the same files get_book_page serves) and reading its
    header."""
    sizes: list[PageSize] = []
    for index in range(page_count):
        try:
            sizes.append(_size(archive.extract_page(path, file_format, index, cache_dir)))
        except (IndexError, archive.ArchiveError) as exc:
            logger.warning("Could not size page %s of %s: %s", index, path, exc)
            sizes.append(None)
    return sizes

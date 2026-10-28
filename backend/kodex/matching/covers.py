"""Cover comparison by perceptual hash.

``phash`` reproduces ``imagehash.phash`` (64 bits: a 32×32 greyscale
Lanczos thumbnail, a 2-D DCT-II, the top-left 8×8 coefficients against
their median) and formats it the same way, so Metron's precomputed
``cover_hash`` values compare directly with ours and no cover has to be
downloaded for them. Written with NumPy alone to avoid pulling in SciPy.

A book's cover is its ComicInfo ``FrontCover`` page, else its first page;
besides the whole page, a version with flat borders cropped and, for a
wide two-page spread, its right half are hashed too, and the best of them
counts.

A collected edition usually reuses an issue's artwork under its own trade
dress (a banner, a new logo, credits), which moves everything on the page
and defeats the hash. ``same_artwork`` finds such covers by matching ORB
keypoints and fitting one homography: the same artwork gives hundreds of
consistent matches across a large part of the image, a shared logo or
banner a few dozen in a small corner, unrelated covers about ten.
"""

from __future__ import annotations

import io
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageChops

from app.models.enums import PAGE_BASED_FORMATS, BookFormat
from app.scanning import archive
from kodex.formats.comicinfo import front_cover_index

logger = logging.getLogger(__name__)

_HASH_SIZE = 8
_IMAGE_SIZE = 32


@lru_cache
def _dct_matrix(n: int) -> np.ndarray:
    k = np.arange(n).reshape(-1, 1)
    i = np.arange(n).reshape(1, -1)
    # SciPy's unnormalised DCT-II; the factor 2 doesn't change the bits.
    return 2 * np.cos(np.pi * k * (2 * i + 1) / (2 * n))


def phash(image: Image.Image) -> str:
    small = image.convert("L").resize((_IMAGE_SIZE, _IMAGE_SIZE), Image.Resampling.LANCZOS)
    pixels = np.asarray(small, dtype=np.float64)
    matrix = _dct_matrix(_IMAGE_SIZE)
    dct = matrix @ pixels @ matrix.T
    low = dct[:_HASH_SIZE, :_HASH_SIZE]
    bits = (low > np.median(low)).flatten()
    value = int("".join("1" if b else "0" for b in bits), 2)
    return f"{value:016x}"


def hamming(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()


def best_distance(ours: list[str], theirs: list[str]) -> int | None:
    pairs = [hamming(a, b) for a in ours for b in theirs if a and b]
    return min(pairs) if pairs else None


def _crop_borders(image: Image.Image) -> Image.Image:
    grey = image.convert("L")
    background = Image.new("L", grey.size, grey.getpixel((0, 0)))
    box = ImageChops.difference(grey, background).point(lambda v: 255 if v > 24 else 0).getbbox()
    return image.crop(box) if box and box != (0, 0, *grey.size) else image


def image_hashes(image: Image.Image) -> list[str]:
    hashes = [phash(image)]
    cropped = _crop_borders(image)
    if cropped.size != image.size:
        hashes.append(phash(cropped))
    width, height = image.size
    if width > height * 1.2:  # a spread: the cover is the right half
        hashes.append(phash(image.crop((width // 2, 0, width, height))))
    return list(dict.fromkeys(hashes))


def hashes_from_bytes(data: bytes) -> list[str]:
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        return image_hashes(image)


def book_cover_page(path: Path, file_format: BookFormat, embedded: dict[str, Any]) -> bytes | None:
    """The image file of a comic's cover page; None for formats without
    pages or when the page can't be read."""
    if file_format not in PAGE_BASED_FORMATS:
        return None
    index = front_cover_index(embedded.get("comicinfo") or {}) or 0
    try:
        with archive.open_book(path, file_format) as book:
            pages = book.pages()
            if not pages:
                return None
            return book.read(pages[min(index, len(pages) - 1)].name)
    except Exception as exc:  # noqa: BLE001 - a cover we can't read is just no signal
        logger.info("No cover for %s: %s", path, exc)
        return None


def book_cover_hashes(path: Path, file_format: BookFormat, embedded: dict[str, Any]) -> list[str]:
    """Hashes of a comic's cover page; empty when there is none."""
    page = book_cover_page(path, file_format, embedded)
    if page is None:
        return []
    try:
        return hashes_from_bytes(page)
    except Exception as exc:  # noqa: BLE001
        logger.info("Unreadable cover in %s: %s", path, exc)
        return []


# Calibrated on a real library against Comic Vine's covers: the same artwork
# under another trade dress gave 100+ inliers over 11 %+ of the image; a
# shared logo up to about 80 inliers over at most 6 %; unrelated covers 10.
ARTWORK_MIN_INLIERS = 100
ARTWORK_MIN_AREA = 0.10
_ARTWORK_SIZE = 600


def _keypoints(data: bytes) -> tuple[Any, Any, tuple[int, int]] | None:
    import cv2  # imported lazily: only matching needs OpenCV here

    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return None
    scale = _ARTWORK_SIZE / max(image.shape)
    image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    keypoints, descriptors = cv2.ORB.create(nfeatures=1000).detectAndCompute(image, None)
    return (keypoints, descriptors, image.shape) if descriptors is not None else None


def artwork_match(ours: bytes, theirs: bytes) -> tuple[int, float]:
    """(inliers, area): keypoint matches consistent with one homography,
    and the share of ``theirs`` their convex hull covers."""
    import cv2

    a, b = _keypoints(ours), _keypoints(theirs)
    if a is None or b is None:
        return 0, 0.0
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(a[1], b[1], k=2)
    good = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < 0.75 * n.distance]
    if len(good) < 8:
        return len(good), 0.0
    src = np.array([a[0][m.queryIdx].pt for m in good], dtype=np.float32)
    dst = np.array([b[0][m.trainIdx].pt for m in good], dtype=np.float32)
    _, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    if getattr(mask, "size", 0) == 0:  # no homography fits (None at runtime)
        return 0, 0.0
    points = dst[mask.ravel() == 1]
    if len(points) < 3:
        return len(points), 0.0
    height, width = b[2]
    return len(points), float(cv2.contourArea(cv2.convexHull(points))) / (height * width)


def same_artwork(ours: bytes, theirs: bytes) -> bool:
    try:
        inliers, area = artwork_match(ours, theirs)
    except Exception as exc:  # noqa: BLE001 - an image OpenCV can't read is no signal
        logger.info("Artwork comparison failed: %s", exc)
        return False
    return inliers >= ARTWORK_MIN_INLIERS and area >= ARTWORK_MIN_AREA

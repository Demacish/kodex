"""EPUB to KEPUB with kepubify (MIT; in the image), for Kobo e-readers:
a KEPUB gets Kobo's own reading engine, with page counts, reading
statistics and a position the device reports exactly. Converted books are
kept under ``covers_dir/kepub``, keyed by the book's content, so a book is
converted once until its file changes."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

TIMEOUT = 300  # seconds


def available(binary: str) -> bool:
    return shutil.which(binary) is not None


def convert(binary: str, source: Path, target: Path) -> bool:
    """Writes the KEPUB of ``source`` to ``target``; False when kepubify is
    missing or fails (the caller serves the EPUB as it is)."""
    if not available(binary):
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as work:
        output = Path(work) / "book.kepub.epub"
        try:
            subprocess.run([binary, "--output", str(output), str(source)], check=True, capture_output=True,
                           timeout=TIMEOUT)  # fmt: skip
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("kepubify couldn't convert %s: %s", source, exc)
            return False
        if not output.is_file():
            logger.warning("kepubify made nothing for %s", source)
            return False
        os.replace(output, target)
    return True


def cached(binary: str, source: Path, cache_dir: Path, key: str) -> Path | None:
    """The KEPUB of ``source``, converted now if it isn't already."""
    target = cache_dir / "kepub" / f"{key}.kepub.epub"
    if target.is_file():
        return target
    return target if convert(binary, source, target) else None

"""Paths inside the libraries root. A library's path and a book's file path
come from the database (an admin typed the first, the scanner wrote the
second), and neither may lead outside the root.

Containment is checked on the normalised path, not the resolved one: a
library folder that is a symlink to another disk is a legitimate setup,
while ``..`` in a stored path never is.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath


class OutsideLibraries(ValueError):
    """The path leads outside the libraries root."""


def clean_relative(value: str) -> str:
    """A library path as stored: relative to the libraries root (a leading
    "/" means the root), with "/" separators, without empty parts, "." or
    ".."; raises OutsideLibraries otherwise."""
    text = value.strip().replace("\\", "/")
    if len(text) > 1 and text[1] == ":":
        raise OutsideLibraries(f"{value!r} is not a path relative to the libraries root")
    parts = [p for p in PurePosixPath(text).parts if p not in ("", ".", "/")]
    if not parts or ".." in parts:
        raise OutsideLibraries(f"{value!r} is not a folder inside the libraries root")
    return "/".join(parts)


def within(root: Path, *parts: str) -> Path:
    """``root / parts...``, refusing anything that normalises to outside
    ``root``."""
    base = os.path.normpath(root)
    target = os.path.normpath(os.path.join(base, *parts))
    if target != base and not target.startswith(base.rstrip(os.sep) + os.sep):
        raise OutsideLibraries(f"{os.path.join(*parts)!r} leads outside {base}")
    return Path(target)

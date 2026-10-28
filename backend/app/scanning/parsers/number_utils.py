"""Shared issue-number normalization for both the embedded-metadata parser
(comicinfo.py's <Number>) and the filename-fallback parser
(comicinfo_writer.py's parse_series_and_number) — both used to silently drop
half-issue values like "13½" via a bare float(), leaving Book.number NULL
and the issue unsorted/unmatched. See claude/forbattringar-serier-
samlingar.md section B for the same bug class in the plain-integer case.
"""

from __future__ import annotations

import re

# Public (no leading underscore) so comicinfo_writer.py's filename regexes
# can build a character class matching the same set of glyphs this module
# understands, rather than the two drifting out of sync.
VULGAR_FRACTIONS: dict[str, float] = {
    "¼": 0.25,
    "½": 0.5,
    "¾": 0.75,
    "⅓": 1 / 3,
    "⅔": 2 / 3,
    "⅕": 0.2,
    "⅖": 0.4,
    "⅗": 0.6,
    "⅘": 0.8,
    "⅙": 1 / 6,
    "⅚": 5 / 6,
    "⅛": 0.125,
    "⅜": 0.375,
    "⅝": 0.625,
    "⅞": 0.875,
}

_VULGAR_FRACTION_RE = re.compile(r"^\s*(?P<whole>\d+)?\s*(?P<frac>[" + "".join(VULGAR_FRACTIONS) + r"])\s*$")
_ASCII_FRACTION_RE = re.compile(r"^\s*(?:(?P<whole>\d+)\s+)?(?P<num>\d+)\s*/\s*(?P<den>\d+)\s*$")


def normalize_issue_number(raw: str | None) -> float | None:
    """Best-effort parse of a ComicInfo <Number>/filename-derived issue
    number into a float, understanding half-issue notations a bare
    float(raw) chokes on. Never raises — returns None for anything it can't
    make sense of, same contract as the bare-float call sites it replaces.
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None

    if match := _VULGAR_FRACTION_RE.match(text):
        whole = int(match.group("whole") or 0)
        return whole + VULGAR_FRACTIONS[match.group("frac")]

    if match := _ASCII_FRACTION_RE.match(text):
        den = int(match.group("den"))
        if den == 0:
            return None
        whole = int(match.group("whole") or 0)
        return whole + int(match.group("num")) / den

    try:
        return float(text)
    except ValueError:
        return None

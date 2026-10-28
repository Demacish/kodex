"""Tests for app/scanning/parsers/number_utils.py — the shared half-issue
normalization used by both comicinfo.py's <Number> parsing and
comicinfo_writer.py's filename-fallback parsing (see claude/forbattringar-
serier-samlingar.md section B for the plain-integer version of this bug).
"""

from __future__ import annotations

import pytest

from app.scanning.parsers.number_utils import normalize_issue_number


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", 1.0),
        ("12.5", 12.5),
        ("½", 0.5),
        ("13½", 13.5),
        ("13 1/2", 13.5),
        ("1/2", 0.5),
        (" 13½ ", 13.5),
    ],
)
def test_normalize_issue_number_parses(raw, expected):
    assert normalize_issue_number(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", [None, "", "   ", "not-a-number", "13/0"])
def test_normalize_issue_number_returns_none_instead_of_raising(raw):
    assert normalize_issue_number(raw) is None

"""Tests for the folder-name classifier added for C (issue vs. collected
edition) — kodex/acquire/sorting/comicinfo_writer.py's detect_edition_type. See
app/scanning/scanner.py's test_scan_falls_back_to_filename_number_and_
detects_edition_type for the full scan-pipeline version of this.
"""

from __future__ import annotations

import pytest

from app.models.enums import BookEditionType
from kodex.acquire.sorting.comicinfo_writer import detect_edition_type, parse_series_and_number


def test_parse_series_and_number_plain_issue():
    series, number, year = parse_series_and_number("Absolute Corvid 004 (2025) (Webrip) (Some-Group)")
    assert series == "Absolute Corvid"
    assert number == 4.0
    assert year == 2025


def test_parse_series_and_number_half_issue_decimal():
    # Previously matched nothing at all (the old regex required exactly
    # 3-4 digits immediately followed by whitespace/end) — see
    # claude/forbattringar-serier-samlingar.md section B for the same bug
    # class in the plain-integer case.
    series, number, year = parse_series_and_number("Absolute Corvid 013.5 (2025) (Webrip) (Some-Group)")
    assert series == "Absolute Corvid"
    assert number == pytest.approx(13.5)
    assert year == 2025


def test_parse_series_and_number_half_issue_vulgar_fraction():
    series, number, _year = parse_series_and_number("Absolute Corvid 013½ (2025) (Webrip) (Some-Group)")
    assert series == "Absolute Corvid"
    assert number == pytest.approx(13.5)


def test_detect_edition_type_plain_issue_number():
    assert detect_edition_type("Absolute Corvid 004 (2025) (Webrip) (Some-Group)") == BookEditionType.ISSUE


def test_detect_edition_type_volume_prefix_is_collected():
    assert (
        detect_edition_type("Absolute Corvid v02 - Abomination (2026) (digital) (Some-Group)")
        == BookEditionType.COLLECTED
    )


def test_detect_edition_type_tpb_keyword():
    assert detect_edition_type("Absolute Corvid TPB 001 (2025)") == BookEditionType.COLLECTED


def test_detect_edition_type_omnibus_keyword():
    assert detect_edition_type("Absolute Corvid Omnibus (2025)") == BookEditionType.COLLECTED


def test_detect_edition_type_deluxe_edition_keyword():
    assert detect_edition_type("Harbour Lights Deluxe Edition - Book 02 (2024)") == BookEditionType.COLLECTED


def test_detect_edition_type_no_signal_defaults_to_issue():
    assert detect_edition_type("Some Weird Release Name (2025)") == BookEditionType.ISSUE

"""Tests for app/scanning/parsers/comicinfo.py, focused on <StoryArc>/
<StoryArcNumber> — the fields that make arc/crossover-event smart
collections possible (e.g. "Silent Tides", "Absolute Universe"). See
kodex/collections/rules.py for how these end up usable in a smart
collection's rule.
"""

from __future__ import annotations

import pytest

from app.scanning.parsers.comicinfo import parse_comicinfo


def _xml(*, story_arc: str | None = None, story_arc_number: str | None = None) -> bytes:
    fields = ""
    if story_arc is not None:
        fields += f"<StoryArc>{story_arc}</StoryArc>"
    if story_arc_number is not None:
        fields += f"<StoryArcNumber>{story_arc_number}</StoryArcNumber>"
    return f"<?xml version='1.0'?><ComicInfo>{fields}</ComicInfo>".encode()


def _xml_with_number(number: str) -> bytes:
    return f"<?xml version='1.0'?><ComicInfo><Number>{number}</Number></ComicInfo>".encode()


def test_parse_comicinfo_plain_number():
    assert parse_comicinfo(_xml_with_number("12"))["number"] == 12.0


def test_parse_comicinfo_half_issue_number():
    # Previously dropped silently (bare float() raised ValueError) — see
    # claude/forbattringar-serier-samlingar.md section B for the same bug
    # class in the plain-integer case, and number_utils.py for the fix.
    assert parse_comicinfo(_xml_with_number("13½"))["number"] == pytest.approx(13.5)


def test_parse_comicinfo_unparseable_number_is_omitted():
    assert "number" not in parse_comicinfo(_xml_with_number("TBD"))


def test_parse_comicinfo_without_story_arc_omits_the_fields():
    result = parse_comicinfo(_xml())
    assert "story_arcs" not in result
    assert "story_arc_numbers" not in result


def test_parse_comicinfo_single_story_arc():
    result = parse_comicinfo(_xml(story_arc="Silent Tides"))
    assert result["story_arcs"] == ["Silent Tides"]
    assert "story_arc_numbers" not in result


def test_parse_comicinfo_multiple_story_arcs_with_numbers():
    result = parse_comicinfo(_xml(story_arc="Silent Tides, Civil War", story_arc_number="3, 1"))
    assert result["story_arcs"] == ["Silent Tides", "Civil War"]
    assert result["story_arc_numbers"] == {"Silent Tides": 3.0, "Civil War": 1.0}


def test_parse_comicinfo_story_arc_number_without_story_arc_is_ignored():
    # Malformed input (a number list with nothing to attach it to) — the
    # zip in parse_comicinfo naturally produces nothing here since there
    # are no arc names to zip against.
    result = parse_comicinfo(_xml(story_arc_number="3"))
    assert "story_arcs" not in result
    assert "story_arc_numbers" not in result


def test_parse_comicinfo_mismatched_length_drops_extra_numbers():
    result = parse_comicinfo(_xml(story_arc="Silent Tides", story_arc_number="3, 1"))
    assert result["story_arcs"] == ["Silent Tides"]
    # Only "Silent Tides" has a name to zip against; the second number (1)
    # has no corresponding arc name and is dropped rather than guessed at.
    assert result["story_arc_numbers"] == {"Silent Tides": 3.0}


def test_parse_comicinfo_non_numeric_story_arc_number_is_skipped():
    result = parse_comicinfo(_xml(story_arc="Silent Tides, Civil War", story_arc_number="not-a-number, 1"))
    assert result["story_arc_numbers"] == {"Civil War": 1.0}


def test_parse_comicinfo_strips_whitespace_around_arc_names():
    result = parse_comicinfo(_xml(story_arc=" Silent Tides ,  Civil War "))
    assert result["story_arcs"] == ["Silent Tides", "Civil War"]

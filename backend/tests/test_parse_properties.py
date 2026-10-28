"""Property-based tests for kodex.matching.parse: no input makes it raise,
and adding the usual decorations to a name doesn't change what it means."""

from __future__ import annotations

from hypothesis import assume, given
from hypothesis import strategies as st

from kodex.matching.parse import normalize_number, parse_filename

_WORD = st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=3, max_size=10)
_SERIES = st.lists(_WORD, min_size=1, max_size=4).map(" ".join).filter(
    lambda s: not any(w.lower() in {"vol", "volume", "annual", "special", "tpb", "omnibus", "hc", "book", "tome",
                                     "chapter", "episode", "fcbd", "one", "compendium", "oneshot", "of"}
                      for w in s.split())
    and not any(w.lower().startswith(("v", "c", "ch", "t", "s", "ep")) and w[1:].isdigit() for w in s.split())
)  # fmt: skip
_TAGS = st.lists(st.sampled_from(["(Digital)", "(Zone-Empire)", "(c2c)", "(Webrip)", "[HQ]", "(2 covers)"]), max_size=3)


@given(st.text())
def test_never_raises(name):
    parsed = parse_filename(name)
    assert isinstance(parsed.series, str)


@given(st.text(), st.sampled_from(["comic", "manga", "book"]))
def test_never_raises_for_any_kind(name, kind):
    parse_filename(name, kind=kind)


@given(_SERIES, st.integers(min_value=0, max_value=999), st.integers(min_value=1940, max_value=2026), _TAGS)
def test_scene_decorations_dont_change_series_or_issue(series, number, year, tags):
    plain = parse_filename(f"{series} {number:03d}.cbz", kind="comic")
    decorated = parse_filename(f"{series} {number:03d} ({year}) {' '.join(tags)}.cbz", kind="comic")
    assert (decorated.series, decorated.issue) == (plain.series, plain.issue) == (series, str(number))
    assert decorated.year == year


@given(_SERIES, st.integers(min_value=1, max_value=999), st.sampled_from(["cbz", "cbr", "zip", "CBZ", "cb7"]))
def test_extension_does_not_matter(series, number, extension):
    assert parse_filename(f"{series} #{number}.{extension}") == parse_filename(f"{series} #{number}.cbz")


@given(_SERIES, st.integers(min_value=1, max_value=60), st.integers(min_value=1, max_value=999))
def test_manga_volume_and_chapter_markers(series, volume, chapter):
    parsed = parse_filename(f"{series} v{volume:02d} c{chapter:03d}.cbz", kind="manga")
    assert (parsed.series, parsed.volume, parsed.chapter, parsed.issue) == (series, str(volume), str(chapter), None)


@given(_SERIES, st.integers(min_value=1, max_value=999))
def test_series_hint_wins_over_a_trailing_number_in_the_name(series, number):
    assume(not series[-1].isdigit())
    named = f"{series} 2099"
    parsed = parse_filename(f"{named} {number:03d}.cbz", kind="comic", series_hint=named)
    assert (parsed.series, parsed.issue) == (named, str(number))


@given(st.from_regex(r"-?[0-9]{1,4}(\.[0-9]{1,2})?[ab½]?", fullmatch=True))
def test_normalize_number_is_idempotent(raw):
    once = normalize_number(raw)
    assert normalize_number(once) == once

"""The golden filename corpus (tests/golden/filenames.jsonl) against
kodex.matching.parse. Every case not marked xfail must parse exactly as
written; a parser bug is added to the corpus before it is fixed.

Each line: {"input", "kind", "expect", optional "series_hint", optional
"xfail": "reason"}. The core fields below are always compared (missing
from "expect" means empty); the optional ones only when listed.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from kodex.matching.parse import parse_filename

CORPUS = Path(__file__).parent / "golden" / "filenames.jsonl"
CORE = (
    "series", "title", "volume", "volume_end", "issue", "issue_count", "chapter", "chapter_end", "year",
    "series_year", "format", "ambiguous",
)  # fmt: skip
OPTIONAL = ("edition", "scan_group", "language", "extra_tags")


def _cases() -> list:
    lines = CORPUS.read_text(encoding="utf-8").splitlines()
    params = []
    for number, line in enumerate(lines, start=1):
        entry = json.loads(line)
        marks = [pytest.mark.xfail(reason=entry["xfail"], strict=True)] if "xfail" in entry else []
        params.append(pytest.param(entry, id=f"{number}:{entry['input']}", marks=marks))
    return params


def _default_format(kind: str, expect: dict) -> str:
    if expect.get("chapter"):
        return "chapter"
    if kind == "manga":
        return "volume"
    if kind == "book":
        return "book"
    if expect.get("volume") and not expect.get("issue"):
        return "collected"
    return "issue"


def _expected(entry: dict) -> dict:
    expect = entry["expect"]
    wanted = {field: expect.get(field) for field in CORE}
    wanted["series"] = expect.get("series", "")
    wanted["ambiguous"] = expect.get("ambiguous", False)
    wanted["format"] = expect.get("format") or _default_format(entry["kind"], expect)
    for field in OPTIONAL:
        if field in expect:
            wanted[field] = tuple(expect[field]) if field == "extra_tags" else expect[field]
    return wanted


def test_corpus_is_big_enough():
    assert len(CORPUS.read_text(encoding="utf-8").splitlines()) >= 300


@pytest.mark.parametrize("entry", _cases())
def test_golden_filename(entry):
    parsed = asdict(parse_filename(entry["input"], kind=entry["kind"], series_hint=entry.get("series_hint")))
    wanted = _expected(entry)
    got = {field: parsed[field] for field in wanted}
    assert got == wanted

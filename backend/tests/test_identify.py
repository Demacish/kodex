"""kodex.matching.identify: external ids from embedded metadata, sidecar
files and names."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kodex.matching.identify import ExternalRef, identify, ids_from_embedded, ids_from_name, ids_from_text, strongest


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://comicvine.gamespot.com/batman/4050-42721/", [("comicvine", "series", "42721")]),
        ("https://comicvine.gamespot.com/batman-1-the-court-of-owls/4000-290425/", [("comicvine", "issue", "290425")]),
        (
            "Tagged with ComicTagger 1.6.0 using info from Comic Vine on 2023-05-01. [Issue ID 290425]",
            [("comicvine", "issue", "290425")],
        ),
        ("ComicVine [CVDB290425]", [("comicvine", "issue", "290425")]),
        (
            "urn:comicvine:series:42721 urn:comicvine:issue:290425",
            [("comicvine", "series", "42721"), ("comicvine", "issue", "290425")],
        ),
        (
            "Tagged with MetronTagger-2.3 using info from Metron on 2024-02-11. [issue_id:12345]",
            [("metron", "issue", "12345")],
        ),
        ("https://www.comics.org/issue/1234567/", [("gcd", "issue", "1234567")]),
        (
            "https://mangadex.org/title/A1C7C817-4E59-43B7-9365-09675A149A6F/one-piece",
            [("mangadex", "series", "a1c7c817-4e59-43b7-9365-09675a149a6f")],
        ),
        ("https://anilist.co/manga/30013/One-Piece/", [("anilist", "series", "30013")]),
        ("https://myanimelist.net/manga/13/One_Piece", [("mal", "series", "13")]),
        ("https://www.mangaupdates.com/series/pb8uwds/one-piece", [("mangaupdates", "series", "pb8uwds")]),
        (
            "Volume 4050-42721 and issue 4000-290425",
            [("comicvine", "series", "42721"), ("comicvine", "issue", "290425")],
        ),
        ("a phone number 555-4050-12 is not an id", []),
        ("", []),
    ],
)
def test_ids_from_text(text, expected):
    assert [(r.provider, r.kind, r.id) for r in ids_from_text(text, "test")] == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Batman (2016) [cv-91273]", [("comicvine", "series", "91273")]),
        ("Batman (2016) (cv91273)", [("comicvine", "series", "91273")]),
        ("Batman cv:91273", [("comicvine", "series", "91273")]),
        ("Batman 4050-91273", [("comicvine", "series", "91273")]),
        ("Batman 001 (2016).cbz", []),
        ("Recover 4000-123 Remover.cbz", [("comicvine", "issue", "123")]),
    ],
)
def test_ids_from_name(name, expected):
    assert [(r.provider, r.kind, r.id) for r in ids_from_name(name, "folder")] == expected


def test_ids_from_embedded_combines_sources():
    embedded = {
        "comicinfo": {
            "web": "https://comicvine.gamespot.com/x/4000-290425/",
            "notes": "[Issue ID 290425]",
            "gtin": "978-1-4012-3541-3",
        },
        "metroninfo": {
            "ids": [{"source": "Metron", "id": "12345"}, {"source": "Comic Vine", "id": "290425"}],
            "series": {"id": "789"},
        },
        "opf": {"identifiers": {"isbn": "9780316129084", "goodreads": "8855321"}},
    }
    refs = [(r.provider, r.kind, r.id) for r in ids_from_embedded(embedded)]
    assert refs == [
        ("comicvine", "issue", "290425"),
        ("isbn", "book", "9781401235413"),
        ("metron", "issue", "12345"),
        ("metron", "series", "789"),
        ("isbn", "book", "9780316129084"),
        ("goodreads", "book", "8855321"),
    ]


def test_identify_reads_sidecars_and_names_strongest_first(tmp_path: Path):
    series_dir = tmp_path / "Batman (2016) [cv-91273]"
    issue_dir = series_dir / "Batman 001"
    issue_dir.mkdir(parents=True)
    (series_dir / "cvinfo").write_text("https://comicvine.gamespot.com/batman/4050-91273/\n")
    (series_dir / "series.json").write_text(json.dumps({"metadata": {"type": "comicSeries", "comicid": 91273}}))
    (issue_dir / "metadata.opf").write_text(
        '<package xmlns="http://www.idpf.org/2007/opf"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier xmlns:opf="http://www.idpf.org/2007/opf" opf:scheme="ISBN">9780306406157</dc:identifier>'
        "</metadata></package>"
    )
    relative = Path("Batman (2016) [cv-91273]") / "Batman 001" / "Batman 001.cbz"
    embedded = {"comicinfo": {"web": "https://comicvine.gamespot.com/x/4000-555/"}}

    refs = identify(relative, tmp_path, embedded)

    assert refs[0] == ExternalRef("comicvine", "issue", "555", "comicinfo.web")
    assert ("isbn", "book", "9780306406157", "metadata.opf") in [(r.provider, r.kind, r.id, r.source) for r in refs]
    series_refs = [r for r in refs if r.provider == "comicvine" and r.kind == "series"]
    assert [r.source for r in series_refs] == ["cvinfo"]  # the name's [cv-…] is the same id, deduplicated
    assert strongest(refs, "comicvine", "series") == "91273"
    assert strongest(refs, "metron", "series") is None


def test_identify_survives_broken_sidecars(tmp_path: Path):
    (tmp_path / "S").mkdir()
    (tmp_path / "S" / "series.json").write_text("{not json")
    (tmp_path / "S" / "metadata.opf").write_text("<broken")
    assert identify(Path("S") / "a.cbz", tmp_path, {}) == []

"""The provider clients against synthetic responses shaped like the real
APIs (see tests/providers/synthetic.py)."""

from __future__ import annotations

import pytest

from kodex.matching.providers.base import ClientSettings, NotConfigured, NotFound, RateLimited, ReplayTransport
from kodex.matching.providers.books import GoogleBooks, Hardcover, OpenLibrary
from kodex.matching.providers.comicvine import ComicVine
from kodex.matching.providers.manga import AniList, MangaDex, MangaUpdates
from kodex.matching.providers.metron import Metron
from tests.db import fresh_engine
from tests.providers import synthetic as s

SETTINGS = ClientSettings(user_agent="kodex-tests")


def _make(cls, records, **kwargs):
    return cls(engine=fresh_engine(), settings=SETTINGS, transport=ReplayTransport(records, cls.secret_params),
               sleep=lambda seconds: None, **kwargs)  # fmt: skip


def test_comicvine_search_fetches_fresh_details_for_the_hits():
    harbor = s.cv_volume(900001, "The Crimson Harbor", 2016, "Northwind Comics", 48, aliases="Crimson Harbor\nTCH")
    tpb = s.cv_volume(900002, "The Crimson Harbor", 2017, "Northwind Comics", 8)
    foreign = s.cv_volume(900003, "The Crimson Harbor", 2018, "Edition Nordlicht", 12)
    cv = _make(ComicVine, [s.cv_search("Crimson Harbor", [900003, 900001, 900002]), s.cv_volumes([foreign, harbor, tpb])],
               api_key="k")  # fmt: skip

    runs = cv.search_runs("Crimson Harbor")

    assert [r.id for r in runs] == ["900003", "900001", "900002"]  # relevance order kept
    main = runs[1]
    assert (main.name, main.start_year, main.publisher, main.issue_count) == (
        "The Crimson Harbor",
        2016,
        "Northwind Comics",
        48,
    )
    assert main.aliases == ["Crimson Harbor", "TCH"]
    assert main.links == {"comicvine": "900001"}


def test_comicvine_issue_list_is_paginated():
    first = [s.cv_issue(800000 + n, 900001, str(n), f"2016-{(n % 12) + 1:02d}-01") for n in range(1, 101)]
    second = [s.cv_issue(800101, 900001, "101", "2024-05-01")]
    cv = _make(ComicVine, [s.cv_issues(900001, first, total=101), s.cv_issues(900001, second, offset=100, total=101)],
               api_key="k")  # fmt: skip
    issues = cv.list_issues("900001")
    assert len(issues) == 101
    assert (issues[0].number, issues[0].year, issues[0].run_id) == ("1", 2016, "900001")


def test_comicvine_error_status_codes():
    cv = _make(ComicVine, [
        s.record("GET", s.CV + "issue/4000-1/", {"format": "json", "field_list": s.ISSUE_FIELDS},
                 response=s.cv_envelope([], status_code=101, error="Object Not Found")),
        s.record("GET", s.CV + "issue/4000-2/", {"format": "json", "field_list": s.ISSUE_FIELDS},
                 response=s.cv_envelope([], status_code=107, error="Rate limit exceeded")),
    ], api_key="k")  # fmt: skip
    with pytest.raises(NotFound):
        cv.get_issue("1")
    with pytest.raises(RateLimited):
        cv.get_issue("2")


def test_comicvine_needs_a_key():
    with pytest.raises(NotConfigured):
        ComicVine(api_key="", engine=fresh_engine(), settings=SETTINGS)


def test_metron_series_issues_and_comicvine_bridges():
    series = s.metron_series(5001, "The Crimson Harbor", 2016, cv_id=900001, count=48)
    tpb = s.metron_series(5002, "The Crimson Harbor TPB", 2017, series_type="Trade Paperback", count=8)
    issues_p1 = [s.metron_issue(6000 + n, 5001, str(n), "2016-01-01", cv_id=800000 + n, pages=24) for n in (1, 2)]
    issues_p2 = [s.metron_issue(6003, 5001, "3", "2016-03-01")]
    metron = _make(Metron, [
        s.record("GET", s.METRON + "series/", {"name": "Crimson Harbor", "page": "1"}, response=s.metron_page([series, tpb])),
        s.record("GET", s.METRON + "issue/", {"series_id": "5001", "page": "1"}, response=s.metron_page(issues_p1, has_next=True)),
        s.record("GET", s.METRON + "issue/", {"series_id": "5001", "page": "2"}, response=s.metron_page(issues_p2)),
        s.record("GET", s.METRON + "series/", {"cv_id": "900001"}, response=s.metron_page([series])),
        s.record("GET", s.METRON + "series/5001/", response={**series, "name": "The Crimson Harbor", "desc": "Invented."}),
    ], username="u", password="p")  # fmt: skip

    runs = metron.search_runs("Crimson Harbor")
    assert [(r.name, r.start_year, r.format, r.links.get("comicvine")) for r in runs] == [
        ("The Crimson Harbor", 2016, "issue", "900001"),
        ("The Crimson Harbor TPB", 2017, "collected", None),
    ]
    issues = metron.list_issues("5001")
    assert [i.number for i in issues] == ["1", "2", "3"]
    assert (issues[0].cover_hash, issues[0].links["comicvine"], issues[0].page_count) == (
        "c3a5f00f0f0fa5c3",
        "800001",
        24,
    )
    bridged = metron.run_for_comicvine("900001")
    assert bridged is not None and bridged.summary == "Invented."


def test_mangadex_titles_links_and_aggregate():
    manga = s.mangadex_manga(
        "0000aaaa-0000-0000-0000-000000000001", "Hoshi no Uta",
        alt=[{"ja": "星の歌"}, {"en": "Song of the Stars"}], links={"al": "700001", "mal": "800001", "mu": "abc12"},
    )  # fmt: skip
    aggregate = {"result": "ok", "volumes": {
        "1": {"volume": "1", "count": 2, "chapters": {"1": {"chapter": "1", "id": "c1", "count": 1}, "2": {"chapter": "2", "id": "c2", "count": 1}}},
        "none": {"volume": "none", "count": 1, "chapters": {"3": {"chapter": "3", "id": "c3", "count": 1}}},
    }}  # fmt: skip
    mangadex = _make(MangaDex, [
        s.record("GET", s.MANGADEX + "manga", {"title": "Hoshi no Uta", "limit": "10", "includes[]": "cover_art",
                                               "order[relevance]": "desc"},
                 response={"result": "ok", "response": "collection", "data": [manga], "limit": 10, "offset": 0, "total": 1}),
        s.record("GET", s.MANGADEX + f"manga/{manga['id']}/aggregate", response=aggregate),
    ])  # fmt: skip
    (run,) = mangadex.search_runs("Hoshi no Uta")
    # MangaDex writes MangaUpdates' id in base 36, the API in decimal.
    assert run.links == {"mangadex": manga["id"], "anilist": "700001", "mal": "800001", "mangaupdates": "17324966"}
    assert "星の歌" in run.aliases and "Song of the Stars" in run.aliases
    assert run.cover_url == f"https://uploads.mangadex.org/covers/{manga['id']}/cover.jpg"
    chapters = mangadex.list_issues(manga["id"])
    assert [(c.number, c.name, c.volume) for c in chapters] == [("1", "v1", "1"), ("2", "v1", "1"), ("3", None, None)]


def test_anilist_and_mangaupdates():
    from kodex.matching.providers.manga import _ANILIST_QUERY

    media = {
        "id": 700001, "idMal": 800001, "format": "MANGA", "status": "RELEASING", "countryOfOrigin": "JP", "volumes": None,
        "chapters": None, "title": {"romaji": "Hoshi no Uta", "english": "Song of the Stars", "native": "星の歌"},
        "synonyms": ["HnU"], "startDate": {"year": 2020}, "endDate": {"year": None}, "coverImage": {"large": "x"},
        "siteUrl": "https://anilist.co/manga/700001", "staff": {"edges": []},
    }  # fmt: skip
    anilist = _make(AniList, [s.record("POST", s.ANILIST, body={"query": _ANILIST_QUERY, "variables": {"search": "Hoshi"}},
                                       response={"data": {"Page": {"media": [media]}}})])  # fmt: skip
    (run,) = anilist.search_runs("Hoshi")
    assert (run.name, run.format, run.country, run.links) == (
        "Song of the Stars",
        "manga",
        "JP",
        {"anilist": "700001", "mal": "800001"},
    )
    assert run.aliases == ["Hoshi no Uta", "星の歌", "HnU"]

    record = {"series_id": 55501, "title": "Hoshi no Uta", "url": "x", "type": "Manga", "year": "2020",
              "associated": [{"title": "Song of the Stars"}], "image": {"url": {"original": "o.jpg"}}}  # fmt: skip
    mangaupdates = _make(MangaUpdates, [
        s.record("POST", s.MANGAUPDATES + "series/search", body={"search": "Hoshi", "perpage": 10},
                 response={"total_hits": 1, "page": 1, "per_page": 10, "results": [{"record": record, "hit_title": "Hoshi no Uta"}]}),
    ])  # fmt: skip
    (hit,) = mangaupdates.search_runs("Hoshi")
    assert (hit.id, hit.start_year, hit.aliases, hit.cover_url) == ("55501", 2020, ["Song of the Stars"], "o.jpg")


def test_open_library_and_google_books():
    edition = {"key": "/books/OL9000001M", "title": "The Crimson Orchard", "publishers": ["Bright Harbor Press"],
               "publish_date": "March 2011", "works": [{"key": "/works/OL9000001W"}], "isbn_13": ["9780306406157"],
               "isbn_10": ["0306406152"], "number_of_pages": 320}  # fmt: skip
    openlibrary = _make(OpenLibrary, [s.record("GET", s.OPENLIBRARY + "isbn/9780306406157.json", response=edition)])
    book = openlibrary.lookup_isbn("9780306406157")
    assert (book.id, book.year, book.work_id, book.isbn13, book.page_count) == (
        "OL9000001M", 2011, "OL9000001W", ["9780306406157"], 320,
    )  # fmt: skip

    volume = {"id": "gb1", "volumeInfo": {"title": "The Crimson Orchard", "subtitle": "A Novel", "authors": ["Ada Alder"],
              "publishedDate": "2011-03-01", "industryIdentifiers": [{"type": "ISBN_10", "identifier": "0306406152"}],
              "pageCount": 320}}  # fmt: skip
    google = _make(GoogleBooks, [
        s.record("GET", s.GOOGLE + "volumes", {"q": "isbn:9780306406157", "maxResults": "10", "printType": "books"},
                 response={"kind": "books#volumes", "totalItems": 1, "items": [volume]}),
        s.record("GET", s.GOOGLE + "volumes", {"q": "isbn:9780000000002", "maxResults": "10", "printType": "books"},
                 response={"kind": "books#volumes", "totalItems": 0}),
    ], api_key="key")  # fmt: skip
    found = google.lookup_isbn("9780306406157")
    assert (found.title, found.authors, found.year, found.isbn13) == (
        "The Crimson Orchard A Novel",
        ["Ada Alder"],
        2011,
        ["9780306406157"],
    )
    with pytest.raises(NotFound):
        google.lookup_isbn("9780000000002")


def test_hardcover_needs_a_token():
    with pytest.raises(NotConfigured):
        Hardcover(token="", engine=fresh_engine(), settings=SETTINGS)

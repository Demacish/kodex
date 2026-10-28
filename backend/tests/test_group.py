"""Grouping books into series (kodex.matching.group and series_ops),
through the scanner, for each grouping strategy, plus the regroup
proposals that replace silent moves."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.config import Settings
from app.models.book import Book
from app.models.enums import LibraryType
from app.models.library import Library
from app.models.reading_progress import ReadingProgress
from app.models.series import Series
from app.models.user import User
from app.scanning import scanner
from kodex.matching.models import MatchReview
from kodex.matching.series_ops import accept_regroup, merge_series, reject_regroup, split_series

_PAGE = b"page"


def _cbz(path: Path, comicinfo: str | None = None, pages: int = 1, salt: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for i in range(pages):
            # Content differs per file, so files never look like moves of each other.
            zf.writestr(f"{i:03d}.png", _PAGE + path.name.encode() + salt.encode())
        if comicinfo is not None:
            zf.writestr("ComicInfo.xml", comicinfo)
    return path


def _comicinfo(series: str, number: str, volume: str | None = None, fmt: str | None = None, manga: bool = False) -> str:
    fields = f"<Series>{series}</Series><Number>{number}</Number>"
    if volume:
        fields += f"<Volume>{volume}</Volume>"
    if fmt:
        fields += f"<Format>{fmt}</Format>"
    if manga:
        fields += "<Manga>YesAndRightToLeft</Manga>"
    return f"<ComicInfo>{fields}</ComicInfo>"


def _epub(path: Path, title: str, author: str, series: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = f'<meta name="calibre:series" content="{series}"/>' if series else ""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
            '<rootfile full-path="content.opf"/></rootfiles></container>',
        )
        zf.writestr(
            "content.opf",
            '<package xmlns="http://www.idpf.org/2007/opf"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f"<dc:title>{title}</dc:title><dc:creator>{author}</dc:creator>{meta}</metadata></package>",
        )
    return path


@pytest.fixture
def library_factory(db_session, tmp_path, monkeypatch):
    root = tmp_path / "libraries"
    monkeypatch.setattr(scanner, "get_settings", lambda: Settings(libraries_root=root))

    def make(library_type: LibraryType = LibraryType.COMICS, strategy: str = "metadata") -> tuple[Library, Path]:
        path = f"{library_type.value}-{strategy}"
        (root / path).mkdir(parents=True, exist_ok=True)
        library = Library(name=path, path=path, library_type=library_type, grouping_strategy=strategy)
        db_session.add(library)
        db_session.commit()
        return library, root / path

    return make


def _series_titles(db) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for series in db.query(Series).order_by(Series.title):
        out[series.title] = sorted(Path(b.file_path).name for b in series.books)
    return out


def _scan(db, library):
    stats = scanner.scan_library(db, library)
    assert stats.errors == []
    return stats


def test_folder_per_issue_still_gives_one_series(db_session, library_factory):
    library, root = library_factory()
    for n, year in ((1, 2024), (2, 2024), (13, 2025)):
        name = f"Absolute Corvid {n:03d} ({year}) (Webrip) (Some-Group)"
        _cbz(root / name / f"{name}.cbz")
    _scan(db_session, library)
    assert list(_series_titles(db_session)) == ["Absolute Corvid"]
    numbers = sorted(b.number_label for b in db_session.query(Book))
    assert numbers == ["1", "13", "2"]


def test_relaunches_in_year_folders_are_separate_runs(db_session, library_factory):
    library, root = library_factory()
    _cbz(root / "Batman (2011)" / "Batman 001 (2011).cbz")
    _cbz(root / "Batman (2016)" / "Batman 001 (2016).cbz")
    _cbz(root / "Batman (2016)" / "Batman 002 (2016).cbz")
    _scan(db_session, library)
    runs = sorted((s.title, s.start_year, len(s.books)) for s in db_session.query(Series))
    assert runs == [("Batman", 2011, 1), ("Batman", 2016, 2)]


def test_comicinfo_series_and_volume_group_across_folders(db_session, library_factory):
    library, root = library_factory()
    _cbz(root / "incoming" / "a.cbz", _comicinfo("Saga", "1", "2012"))
    _cbz(root / "elsewhere" / "b.cbz", _comicinfo("Saga", "2", "2012"))
    _cbz(root / "elsewhere" / "c.cbz", _comicinfo("Batman", "1", "2"))
    _cbz(root / "elsewhere" / "d.cbz", _comicinfo("Batman", "1", "3"))
    _scan(db_session, library)
    keys = sorted((s.title, s.group_key, len(s.books)) for s in db_session.query(Series))
    assert keys == [("Batman", "batman|v2|issue", 1), ("Batman", "batman|v3|issue", 1), ("Saga", "saga|2012|issue", 2)]


def test_collected_editions_get_their_own_series_next_to_the_issues(db_session, library_factory):
    library, root = library_factory()
    _cbz(root / "Saga (2012)" / "Saga 001 (2012).cbz")
    _cbz(root / "Saga (2012)" / "Saga Vol. 01 (2012) (TPB).cbz")
    _cbz(root / "Saga (2012)" / "Saga Omnibus 01.cbz", _comicinfo("Saga", "1", "2012", fmt="Omnibus"))
    _scan(db_session, library)
    families = sorted((s.format_family, len(s.books)) for s in db_session.query(Series))
    assert families == [("collected", 2), ("issue", 1)]
    formats = {Path(b.file_path).name: (b.format, b.edition_type.value) for b in db_session.query(Book)}
    assert formats["Saga Vol. 01 (2012) (TPB).cbz"] == ("collected", "collected")
    assert formats["Saga 001 (2012).cbz"] == ("issue", "issue")


def test_a_thick_book_without_a_number_is_a_collected_edition(db_session, library_factory):
    library, root = library_factory()
    _cbz(root / "Harbour Lights (2016)" / "Harbour Lights (2016) (Digital).cbz", pages=130)
    _cbz(root / "Lantern Keep (2016)" / "Lantern Keep (2016) (Digital).cbz", pages=36)  # a one-shot
    _cbz(root / "Quiet Coast" / "Quiet Coast Book 02 (2019).cbz", pages=220)
    _cbz(root / "Quiet Coast Damned" / "Quiet Coast Damned Book 01 (2019).cbz", pages=48)
    _scan(db_session, library)
    books = {Path(b.file_path).name: b for b in db_session.query(Book)}
    assert books["Harbour Lights (2016) (Digital).cbz"].format == "collected"
    assert books["Lantern Keep (2016) (Digital).cbz"].format == "issue"
    thick = books["Quiet Coast Book 02 (2019).cbz"]
    assert (thick.format, thick.volume_number, thick.series.title) == ("collected", "2", "Quiet Coast")
    prestige = books["Quiet Coast Damned Book 01 (2019).cbz"]  # "Book One" of a prestige mini is an issue
    assert (prestige.format, prestige.number_label) == ("issue", "1")


def test_annuals_and_specials_folder_stay_with_their_series(db_session, library_factory):
    library, root = library_factory()
    _cbz(root / "Batman (2016)" / "Batman 001 (2016).cbz")
    _cbz(root / "Batman (2016)" / "Specials" / "Batman Annual 001 (2017).cbz")
    _scan(db_session, library)
    assert _series_titles(db_session) == {"Batman": ["Batman 001 (2016).cbz", "Batman Annual 001 (2017).cbz"]}
    annual = db_session.query(Book).filter(Book.file_path.like("%Annual%")).one()
    assert annual.format == "annual"


def test_manga_volumes_and_chapters_share_a_series(db_session, library_factory):
    library, root = library_factory(LibraryType.MANGA)
    _cbz(root / "Hoshi no Uta" / "Hoshi no Uta v01.cbz")
    _cbz(root / "Hoshi no Uta" / "[Lumen Scans] Hoshi no Uta - c012 (v03) [Digital].cbz")
    _cbz(root / "Hoshi no Uta" / "Hoshi no Uta - c013.cbz")
    _scan(db_session, library)
    assert list(_series_titles(db_session)) == ["Hoshi no Uta"]
    chapter = db_session.query(Book).filter(Book.file_path.like("%c012%")).one()
    assert (chapter.format, chapter.chapter_number, chapter.volume_number, chapter.scan_group) == (
        "chapter", "12", "3", "Lumen Scans",
    )  # fmt: skip
    assert chapter.parsed["series"] == "Hoshi no Uta"


def test_ebooks_group_by_opf_series_and_author(db_session, library_factory):
    library, root = library_factory(LibraryType.EBOOKS)
    _epub(root / "Corey" / "1.epub", "Leviathan Wakes", "James S. A. Corey", "The Expanse")
    _epub(root / "Corey" / "2.epub", "Caliban's War", "James S. A. Corey", "The Expanse")
    _epub(root / "Austen" / "pp.epub", "Pride and Prejudice", "Jane Austen")
    _epub(root / "Other" / "pp.epub", "Pride and Prejudice", "Someone Else")
    _scan(db_session, library)
    groups = sorted((s.title, len(s.books)) for s in db_session.query(Series))
    assert groups == [("Pride and Prejudice", 1), ("Pride and Prejudice", 1), ("The Expanse", 2)]


def test_mixed_library_reads_kind_from_each_file(db_session, library_factory):
    library, root = library_factory(LibraryType.MIXED)
    _cbz(root / "x" / "Hoshi no Uta v01.cbz", _comicinfo("Hoshi no Uta", "1", manga=True))
    _cbz(root / "x" / "Batman 001.cbz")
    _scan(db_session, library)
    families = {s.title: s.format_family for s in db_session.query(Series)}
    assert families == {"Batman": "issue", "Hoshi no Uta": "manga"}


def test_folder_strategy_is_one_series_per_folder_like_v1(db_session, library_factory):
    library, root = library_factory(strategy="folder")
    _cbz(root / "Batman (2016)" / "Batman 001 (2016).cbz")
    _cbz(root / "Batman (2016)" / "Saga Vol. 01 (2012) (TPB).cbz")
    _cbz(root / "loose.cbz")
    _scan(db_session, library)
    assert _series_titles(db_session) == {"Batman (2016)": ["Batman 001 (2016).cbz", "Saga Vol. 01 (2012) (TPB).cbz"]}
    assert db_session.query(Book).filter(Book.file_path == "loose.cbz").one().series_id is None
    series = db_session.query(Series).one()
    assert (series.start_year, series.norm_title) == (2016, "batman")


def test_folder_strategy_adopts_a_v1_series_without_a_key(db_session, library_factory):
    library, root = library_factory(strategy="folder")
    v1 = Series(library_id=library.id, title="Batman (2016)", sort_title="Batman (2016)", path="Batman (2016)")
    db_session.add(v1)
    db_session.commit()
    _cbz(root / "Batman (2016)" / "Batman 001 (2016).cbz")
    _scan(db_session, library)
    assert db_session.query(Series).one().id == v1.id
    assert v1.group_key == "batman|folder:Batman (2016)|issue"


def test_changed_file_with_a_new_key_is_proposed_not_moved(db_session, library_factory):
    library, root = library_factory()
    path = _cbz(root / "in" / "a.cbz", _comicinfo("Saga", "1", "2012"))
    _scan(db_session, library)
    book = db_session.query(Book).one()
    original = book.series_id

    _cbz(path, _comicinfo("Saga", "1", "2018"), salt="retagged")  # retagged with another run
    _scan(db_session, library)

    db_session.refresh(book)
    assert book.series_id == original
    review = db_session.query(MatchReview).one()
    assert (review.kind, review.status, review.series_id, review.book_count) == ("regroup", "open", original, 1)
    assert list(review.parsed["moves"]) == ["saga|2018|issue"]

    accept_regroup(db_session, review)
    db_session.commit()
    db_session.refresh(book)
    assert book.series.group_key == "saga|2018|issue"
    assert book.series_locked is False
    assert db_session.get(Series, original) is None  # left empty, removed
    assert review.status == "resolved"


def test_rejecting_a_regroup_keeps_and_locks_the_books(db_session, library_factory):
    library, root = library_factory()
    path = _cbz(root / "in" / "a.cbz", _comicinfo("Saga", "1", "2012"))
    _scan(db_session, library)
    _cbz(path, _comicinfo("Saga", "1", "2018"), salt="retagged")
    _scan(db_session, library)
    review = db_session.query(MatchReview).one()
    reject_regroup(db_session, review)
    db_session.commit()
    _cbz(path, _comicinfo("Saga", "1", "2019"), salt="again")
    _scan(db_session, library)
    assert db_session.query(MatchReview).filter(MatchReview.status == "open").count() == 0
    assert db_session.query(Book).one().series_locked is True


def test_renamed_folder_keeps_the_book_and_its_progress(db_session, library_factory):
    """M-14: a renamed folder of a series with reading progress becomes a
    regroup proposal; the book keeps its id and progress."""
    library, root = library_factory(strategy="folder")
    _cbz(root / "Batman" / "Batman 001.cbz")
    _scan(db_session, library)
    book = db_session.query(Book).one()
    user = User(oidc_subject="u", username="u")
    db_session.add(user)
    db_session.flush()
    db_session.add(ReadingProgress(user_id=user.id, book_id=book.id, position="3", progress_percent=50.0))
    db_session.commit()
    book_id, series_id = book.id, book.series_id

    (root / "Batman").rename(root / "Batman (2016)")
    _scan(db_session, library)

    book = db_session.get(Book, book_id)
    assert book.file_path == "Batman (2016)/Batman 001.cbz"
    assert book.missing_since is None
    assert book.series_id == series_id
    assert db_session.query(ReadingProgress).filter(ReadingProgress.book_id == book_id).count() == 1
    review = db_session.query(MatchReview).one()
    assert review.kind == "regroup"


def test_merge_and_split(db_session, library_factory):
    library, root = library_factory()
    _cbz(root / "Batman (2011)" / "Batman 001 (2011).cbz")
    _cbz(root / "Batman (2016)" / "Batman 001 (2016).cbz")
    _scan(db_session, library)
    a, b = db_session.query(Series).order_by(Series.start_year).all()
    b.is_following = True
    merge_series(db_session, a, [b])
    db_session.commit()
    assert db_session.query(Series).count() == 1
    assert a.is_following is True
    assert len(a.books) == 2

    moved = [bk.id for bk in a.books if "2016" in bk.file_path]
    new = split_series(db_session, a, moved, "Batman (2016)")
    db_session.commit()
    assert [bk.id for bk in new.books] == moved
    assert all(bk.series_locked for bk in new.books)


def test_v1_books_get_parsed_and_keyed_on_the_next_scan(db_session, library_factory):
    """Books carried over from v1 have no parse and their series no key;
    the next scan fills both in without moving anything."""
    library, root = library_factory(strategy="folder")
    _cbz(root / "Batman (2016)" / "Batman 001 (2016).cbz")
    _scan(db_session, library)
    book = db_session.query(Book).one()
    series = book.series
    book.parsed, book.number_label, book.format = None, None, "issue"
    series.group_key = None
    db_session.commit()

    _scan(db_session, library)

    db_session.refresh(book)
    assert book.parsed["issue"] == "1" and book.number_label == "1"
    assert book.series_id == series.id
    assert series.group_key == "batman|folder:Batman (2016)|issue"
    assert db_session.query(MatchReview).count() == 0


def test_a_v1_merged_series_is_proposed_as_a_whole(db_session, library_factory):
    """v1 merged folder-per-issue series into one canonical series without
    a key; after a switch to metadata grouping every one of its books is in
    the one proposal."""
    library, root = library_factory(strategy="folder")
    for n in (1, 2, 3):
        _cbz(root / f"Absolute Corvid {n:03d} (2025)" / f"Absolute Corvid {n:03d} (2025).cbz")
    _scan(db_session, library)
    canonical = db_session.query(Series).order_by(Series.id).first()
    for book in db_session.query(Book):
        book.series_id, book.parsed = canonical.id, None
    for series in db_session.query(Series):
        series.group_key = None
    library.grouping_strategy = "metadata"
    db_session.commit()

    _scan(db_session, library)

    review = db_session.query(MatchReview).one()
    (move,) = review.parsed["moves"].values()
    assert len(move["book_ids"]) == 3 and review.book_count == 3


def test_series_left_without_books_are_removed(db_session, library_factory):
    library, root = library_factory(strategy="folder")
    _cbz(root / "Batman" / "Batman 001.cbz")
    _scan(db_session, library)
    db_session.add(Series(library_id=library.id, title="Leftover", sort_title="Leftover", path="Leftover"))
    db_session.commit()
    _scan(db_session, library)
    assert [s.title for s in db_session.query(Series)] == ["Batman"]

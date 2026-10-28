"""Automatic sorting of the intake library: kodex/acquire/sorting/classifier.py's
release-name heuristics, and scan_library_task classifying/moving new
arrivals before it scans the intake (app/workers/tasks.py). Same
SessionLocal-monkeypatch convention as test_download_tasks.py."""

from __future__ import annotations

import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

import app.scanning.scanner as scanner
import app.workers.tasks as tasks
from app.models.book import Book
from app.models.enums import LibraryType, SortingStatus
from app.models.library import Library
from app.models.sorting import SortingItem
from kodex.acquire.sorting.classifier import classify
from kodex.acquire.sorting.paths import DESTINATION_LIBRARY_PATHS
from tests.db import fresh_engine


def _cbz(path: Path, comicinfo: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("001.jpg", b"not-a-real-image")
        if comicinfo is not None:
            archive.writestr("ComicInfo.xml", comicinfo)
    return path


# --- classifier -----------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["Bramble c001", "One Piece - Ch. 1050", "Chainsaw Man Chapter 12", "[Group] Dandadan c120 (v2)"],
)
def test_manga_release_names_are_classified_as_manga(tmp_path, name):
    detected, reason = classify(_cbz(tmp_path / f"{name}.cbz"))
    assert detected == LibraryType.MANGA
    assert "manga" in reason


@pytest.mark.parametrize(
    "name",
    ["Absolute Corvid 001 (2024) (Digital) (Zone-Empire)", "Saga 054 (2018)", "Batman Annual 2023"],
)
def test_western_release_names_are_classified_as_comics(tmp_path, name):
    detected, _ = classify(_cbz(tmp_path / f"{name}.cbz"))
    assert detected == LibraryType.COMICS


def test_folder_is_classified_by_the_archives_inside_it(tmp_path):
    folder = tmp_path / "Kaiju No. 8"
    _cbz(folder / "Kaiju No. 8 c001.cbz")
    _cbz(folder / "Kaiju No. 8 c002.cbz")
    assert classify(folder)[0] == LibraryType.MANGA


@pytest.mark.parametrize("name", ["Saga Volume 1", "Something Random", "Batman c001 (2016) (Digital)"])
def test_ambiguous_names_stay_in_the_review_queue(tmp_path, name):
    # "Volume N" is used by western trades too; a name with both a manga
    # and a comics signal is no signal at all.
    assert classify(_cbz(tmp_path / f"{name}.cbz"))[0] is None


def test_comicinfo_manga_field_wins_over_the_name(tmp_path):
    comicinfo = "<ComicInfo><Manga>Yes</Manga></ComicInfo>"
    detected, reason = classify(_cbz(tmp_path / "Absolute Corvid 001 (2024).cbz", comicinfo))
    assert detected == LibraryType.MANGA
    assert "ComicInfo" in reason


def test_ebook_files_are_still_ebooks(tmp_path):
    epub = tmp_path / "A Novel.epub"
    epub.write_bytes(b"x")
    assert classify(epub)[0] == LibraryType.EBOOKS


# --- scan_library_task's automatic sorting --------------------------------


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = fresh_engine()
    factory = sessionmaker(bind=engine, future=True)

    root = tmp_path / "libraries"
    (root / "inkommande").mkdir(parents=True)
    for path in DESTINATION_LIBRARY_PATHS.values():
        (root / path).mkdir(parents=True)

    settings = SimpleNamespace(libraries_root=root, sorting_auto_apply=True)
    monkeypatch.setattr(tasks, "get_settings", lambda: settings)
    monkeypatch.setattr(scanner, "get_settings", lambda: settings)
    monkeypatch.setattr(tasks, "SessionLocal", factory)
    enqueued: list = []
    monkeypatch.setattr(tasks, "get_scan_queue", lambda: SimpleNamespace(enqueue=lambda *a, **k: enqueued.append(a)))

    db = factory()
    intake = Library(name="Inkommande", path="inkommande", library_type=LibraryType.MIXED)
    db.add(intake)
    destinations = {}
    for library_type, path in DESTINATION_LIBRARY_PATHS.items():
        destination = Library(name=f"Sorterat {library_type.value}", path=path, library_type=library_type)
        db.add(destination)
        destinations[library_type] = destination
    db.commit()
    ids = SimpleNamespace(
        intake=intake.id, **{library_type.value: lib.id for library_type, lib in destinations.items()}
    )
    db.close()
    return SimpleNamespace(root=root, factory=factory, settings=settings, enqueued=enqueued, ids=ids)


def _items(env) -> dict[str, SortingItem]:
    db = env.factory()
    try:
        return {item.source_path: (item.status, item.resolved_type) for item in db.query(SortingItem).all()}
    finally:
        db.close()


def _book_paths(env, library_id: int) -> list[str]:
    db = env.factory()
    try:
        return sorted(b.file_path for b in db.query(Book).filter(Book.library_id == library_id).all())
    finally:
        db.close()


def test_scanning_the_intake_moves_confident_items_and_queues_the_rest(env):
    _cbz(env.root / "inkommande" / "Bramble c001.cbz")
    _cbz(env.root / "inkommande" / "Saga 054 (2018).cbz")
    (env.root / "inkommande" / "A Novel.epub").write_bytes(b"x")
    _cbz(env.root / "inkommande" / "Something Random.cbz")

    result = tasks.scan_library_task(env.ids.intake)

    assert result["sorting"] == {"items_added": 4, "moved": 3, "failed": 0}
    assert (env.root / DESTINATION_LIBRARY_PATHS[LibraryType.MANGA] / "Bramble c001.cbz").exists()
    assert (env.root / DESTINATION_LIBRARY_PATHS[LibraryType.COMICS] / "Saga 054 (2018).cbz").exists()
    assert (env.root / DESTINATION_LIBRARY_PATHS[LibraryType.EBOOKS] / "A Novel.epub").exists()
    assert _items(env)["Something Random.cbz"] == (SortingStatus.PENDING, None)
    # Only the uncertain item is left to be scanned into the intake itself.
    assert _book_paths(env, env.ids.intake) == ["Something Random.cbz"]
    # Each destination that received something gets its own scan queued.
    scans = [args for args in env.enqueued if args[0].__name__ == "scan_library_task"]
    assert sorted(args[1] for args in scans) == sorted([env.ids.comics, env.ids.manga, env.ids.ebooks])


def test_auto_apply_off_only_classifies(env):
    env.settings.sorting_auto_apply = False
    _cbz(env.root / "inkommande" / "Bramble c001.cbz")

    result = tasks.scan_library_task(env.ids.intake)

    assert result["sorting"] == {"items_added": 1, "moved": 0, "failed": 0}
    assert _items(env)["Bramble c001.cbz"] == (SortingStatus.RESOLVED, LibraryType.MANGA)
    assert (env.root / "inkommande" / "Bramble c001.cbz").exists()


def test_other_mixed_libraries_are_never_sorted(env):
    db = env.factory()
    # Sorts after "Inkommande" by name, so it is not the intake.
    other = Library(name="Övrigt", path="ovrigt", library_type=LibraryType.MIXED)
    db.add(other)
    db.commit()
    other_id = other.id
    db.close()
    _cbz(env.root / "ovrigt" / "Bramble c001.cbz")

    result = tasks.scan_library_task(other_id)

    assert "sorting" not in result
    assert (env.root / "ovrigt" / "Bramble c001.cbz").exists()
    assert _items(env) == {}


def test_missing_destination_library_does_not_stop_the_scan(env):
    db = env.factory()
    db.query(Library).filter(Library.id == env.ids.manga).delete()
    db.commit()
    db.close()
    _cbz(env.root / "inkommande" / "Bramble c001.cbz")

    result = tasks.scan_library_task(env.ids.intake)

    assert "error" in result["sorting"]
    assert _book_paths(env, env.ids.intake) == ["Bramble c001.cbz"]


def test_other_libraries_folders_under_an_intake_at_the_root_are_left_alone(env):
    db = env.factory()
    intake = db.get(Library, env.ids.intake)
    intake.path = "."
    db.add(Library(name="Serier", path="serier", library_type=LibraryType.COMICS))
    db.commit()
    db.close()
    (env.root / "inkommande").rmdir()  # the fixture's own intake folder, unused here
    _cbz(env.root / "serier" / "Saga 054 (2018).cbz")
    _cbz(env.root / "Bramble c001.cbz")

    result = tasks.scan_library_task(env.ids.intake)

    assert result["sorting"]["moved"] == 1
    assert (env.root / "serier" / "Saga 054 (2018).cbz").exists()
    assert set(_items(env)) == {"Bramble c001.cbz"}

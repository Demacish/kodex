"""tools/fixtures/generate_library.py: a small synthetic library is
deterministic, matches its manifest, and scans cleanly."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from app.config import Settings
from app.models.enums import LibraryType
from app.models.library import Library
from app.scanning import scanner

_GENERATOR = Path(__file__).resolve().parents[2] / "tools" / "fixtures" / "generate_library.py"


@pytest.fixture(scope="module")
def generated(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("synthetic")
    subprocess.run([sys.executable, str(_GENERATOR), "--out", str(out), "--files", "120", "--seed", "7"], check=True)
    return out


def _manifest(path: Path) -> dict:
    return json.loads((path / "manifest.json").read_text())


def test_manifest_matches_the_files_on_disk(generated):
    manifest = _manifest(generated)
    assert manifest["files"] == len(manifest["entries"]) == 120
    for entry in manifest["entries"]:
        target = generated / entry["path"]
        if entry["file_format"] == "image_folder":
            assert len(list(target.glob("*.jpg"))) == entry["pages"]
        else:
            assert target.is_file()
        if entry["file_format"] == "cbz":
            with zipfile.ZipFile(target) as zf:
                assert ("ComicInfo.xml" in zf.namelist()) == entry["has_comicinfo"]


def test_every_library_type_and_edge_case_is_present(generated):
    entries = _manifest(generated)["entries"]
    kinds = {(e["library"], e["format"]) for e in entries}
    assert {("comics", "issue"), ("manga", "chapter"), ("ebooks", "book")} <= kinds
    assert any(e["file_format"] == "epub" and e["isbn"] for e in entries)


def test_same_seed_gives_the_same_plan():
    spec = importlib.util.spec_from_file_location("generate_library", _GENERATOR)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    first = [job.entry for job in module.plan_library(200, seed=3, pages=3)]
    second = [job.entry for job in module.plan_library(200, seed=3, pages=3)]
    assert first == second
    assert len({entry.path for entry in first}) == 200


@pytest.mark.parametrize(
    ("folder", "library_type"),
    [("serier", LibraryType.COMICS), ("manga", LibraryType.MANGA), ("bocker", LibraryType.EBOOKS)],
)
def test_scanner_reads_every_generated_book(db_session, generated, monkeypatch, folder, library_type):
    monkeypatch.setattr(scanner, "get_settings", lambda: Settings(libraries_root=generated))
    library = Library(name=folder, path=folder, library_type=library_type)
    db_session.add(library)
    db_session.commit()

    stats = scanner.scan_library(db_session, library)

    expected = sum(1 for e in _manifest(generated)["entries"] if e["path"].startswith(f"{folder}/"))
    assert stats.errors == []
    assert stats.books_added == expected

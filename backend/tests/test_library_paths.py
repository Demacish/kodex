"""kodex.library.paths: library paths and book paths stay inside the
libraries root."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.enums import LibraryType
from app.schemas.library import LibraryCreate
from kodex.library.paths import OutsideLibraries, clean_relative, within


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("comics", "comics"),
        ("/comics/", "comics"),
        ("sorted\\manga", "sorted/manga"),
        ("./a/./b", "a/b"),
        ("a//b", "a/b"),
    ],
)
def test_clean_relative(value, expected):
    if expected is None:
        with pytest.raises(OutsideLibraries):
            clean_relative(value)
    else:
        assert clean_relative(value) == expected


@pytest.mark.parametrize("value", ["../etc", "a/../../b", "", ".", "/", "C:/books", "/../etc"])
def test_paths_leading_outside_are_refused(value):
    with pytest.raises(OutsideLibraries):
        clean_relative(value)


def test_within_allows_the_inside_and_refuses_the_outside(tmp_path):
    root = tmp_path / "libraries"
    assert within(root, "comics", "Saga/Saga 001.cbz") == root / "comics" / "Saga" / "Saga 001.cbz"
    assert within(root, "comics", "a/../b.cbz") == root / "comics" / "b.cbz"
    for parts in (("..", "x"), ("comics", "../../etc/passwd"), ("comics", "/etc/passwd")):
        with pytest.raises(OutsideLibraries):
            within(root, *parts)


def test_a_symlinked_library_folder_still_works(tmp_path):
    other_disk = tmp_path / "nas" / "comics"
    other_disk.mkdir(parents=True)
    root = tmp_path / "libraries"
    root.mkdir()
    (root / "comics").symlink_to(other_disk)
    assert within(root, "comics", "x.cbz") == root / "comics" / "x.cbz"


def test_library_create_validates_its_path():
    assert LibraryCreate(name="C", path="/comics/", library_type=LibraryType.COMICS).path == "comics"
    with pytest.raises(ValidationError):
        LibraryCreate(name="C", path="../../etc", library_type=LibraryType.COMICS)

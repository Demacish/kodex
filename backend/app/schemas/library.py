from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import LibraryType
from kodex.library.paths import OutsideLibraries, clean_relative


class LibraryCreate(BaseModel):
    name: str
    path: str
    library_type: LibraryType

    @field_validator("path")
    @classmethod
    def _inside_the_libraries_root(cls, value: str) -> str:
        try:
            return clean_relative(value)
        except OutsideLibraries as exc:
            raise ValueError(str(exc)) from exc


class LibraryUpdate(BaseModel):
    """PATCH /libraries/{id}. Every field is optional; only the ones sent
    are changed. `path` is deliberately not editable here — moving a
    library's root means a full rescan, not a metadata edit.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    library_type: LibraryType | None = None
    read_only: bool | None = None
    write_back: bool | None = None


class LibraryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    path: str
    library_type: LibraryType
    read_only: bool = False
    write_back: bool = False
    last_scanned_at: dt.datetime | None
    last_fulltext_indexed_at: dt.datetime | None


class ScanResult(BaseModel):
    books_added: int
    books_updated: int
    books_unchanged: int
    errors: list[str]


class LibraryBrowseEntryOut(BaseModel):
    """One child of the folder GET /libraries/{id}/browse?path= is
    listing — see that endpoint. `book_count` is a recursive count of
    importable files (see _UPLOAD_EXTENSIONS) under a directory entry;
    always null for a file entry.
    """

    name: str
    is_dir: bool
    book_count: int | None = None


class LibraryBrowseOut(BaseModel):
    path: str
    breadcrumbs: list[str]
    entries: list[LibraryBrowseEntryOut]

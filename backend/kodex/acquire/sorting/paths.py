"""Shared path conventions for the sorting feature — where each detected
type's destination Library lives, relative to settings.libraries_root.
Used both when seeding those Library rows and when actually moving files
in app/workers/tasks.py's sorting_apply_task.
"""

from __future__ import annotations

from app.models.enums import LibraryType

DESTINATION_LIBRARY_PATHS: dict[LibraryType, str] = {
    LibraryType.COMICS: "_sorterat/serier",
    LibraryType.MANGA: "_sorterat/manga",
    LibraryType.EBOOKS: "_sorterat/bocker",
}

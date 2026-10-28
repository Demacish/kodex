"""Comic archives and image folders behind one interface: CBZ (zip), CBR
(RAR), CB7 (7z) and a folder of images.

The container is recognised by its first bytes, not its extension: many
".cbr" files are zips and some ".cbz" files are RARs. RAR archives are
listed in-process by ``rarfile`` and decompressed through ``unar`` or
``bsdtar`` (never the proprietary ``unrar``), 7z by ``py7zr``.

Pages are the image entries in natural order ("2.jpg" before "10.jpg"),
without macOS resource forks (``__MACOSX/``, ``._name``). Nothing is ever
extracted under an entry's own name, so an entry called ``../../x`` can't
escape anywhere (zip-slip), and every read is bounded: an entry declaring
more than ``MAX_ENTRY_BYTES``, compressing better than ``MAX_RATIO`` (an
image barely compresses; a decompression bomb compresses enormously), or
an archive with more than ``MAX_ENTRIES`` entries is refused.
"""

from __future__ import annotations

import io
import logging
import re
import subprocess
import threading
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO, Any

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".jxl"}
MAX_ENTRIES = 20_000
MAX_ENTRY_BYTES = 256 * 1024 * 1024
MAX_RATIO = 100
_RATIO_FLOOR = 1024 * 1024  # small entries (XML) may compress as well as they like

_SIGNATURES = (
    (b"PK\x03\x04", "zip"),
    (b"PK\x05\x06", "zip"),  # an empty zip
    (b"Rar!\x1a\x07", "rar"),
    (b"7z\xbc\xaf\x27\x1c", "7z"),
    (b"%PDF", "pdf"),
)


class ArchiveError(RuntimeError):
    """The archive can't be read."""


class UnsafeArchive(ArchiveError):
    """The archive exceeds a safety limit (a likely decompression bomb)."""


class PageOutOfRange(ArchiveError, IndexError):
    """No page with that index."""


@dataclass(frozen=True)
class Entry:
    name: str
    size: int  # uncompressed bytes
    compressed: int | None = None
    crc: int | None = None  # CRC-32, when the format records one


def sniff(path: Path) -> str | None:
    """``zip``, ``rar``, ``7z``, ``pdf`` or None, from the file's first bytes."""
    with path.open("rb") as handle:
        head = handle.read(8)
    return next((kind for signature, kind in _SIGNATURES if head.startswith(signature)), None)


def natural_key(name: str) -> tuple[Any, ...]:
    """Sort key that puts "page 2" before "page 10", folder by folder."""
    parts = re.split(r"(\d+)", name.casefold())
    return tuple((0, int(p)) if p.isdigit() else (1, p) for p in parts)


def is_page(name: str) -> bool:
    path = PurePosixPath(name.replace("\\", "/"))
    if path.name.startswith("._") or "__MACOSX" in path.parts:
        return False
    return path.suffix.lower() in IMAGE_EXTENSIONS


def _check(entry: Entry) -> None:
    if entry.size > MAX_ENTRY_BYTES:
        raise UnsafeArchive(f"{entry.name} would unpack to {entry.size} bytes")
    if entry.compressed and entry.size > _RATIO_FLOOR and entry.size > entry.compressed * MAX_RATIO:
        raise UnsafeArchive(f"{entry.name} compresses {entry.size // entry.compressed}:1")


class Archive:
    """A book's container. Use as a context manager; entries() lists every
    file, pages() the images in reading order."""

    def __enter__(self) -> Archive:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        pass

    def entries(self) -> list[Entry]:
        raise NotImplementedError

    def _read(self, entry: Entry) -> bytes:
        raise NotImplementedError

    def pages(self) -> list[Entry]:
        return sorted((e for e in self.entries() if is_page(e.name)), key=lambda e: natural_key(e.name))

    def read(self, name: str) -> bytes:
        entry = next((e for e in self.entries() if e.name == name), None)
        if entry is None:
            raise ArchiveError(f"No entry {name!r}")
        _check(entry)
        return self._read(entry)

    def open(self, name: str) -> IO[bytes]:
        return io.BytesIO(self.read(name))

    def sidecar(self, filename: str) -> bytes | None:
        """The shallowest entry with this file name (``ComicInfo.xml``),
        compared case-insensitively."""
        wanted = filename.casefold()
        matches = [e for e in self.entries() if PurePosixPath(e.name.replace("\\", "/")).name.casefold() == wanted]
        if not matches:
            return None
        return self.read(min(matches, key=lambda e: e.name.count("/")).name)


class ZipArchive(Archive):
    def __init__(self, path: Path) -> None:
        try:
            self._zip = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError) as exc:
            raise ArchiveError(f"Could not open {path}: {exc}") from exc
        infos = [i for i in self._zip.infolist() if not i.is_dir()]
        if len(infos) > MAX_ENTRIES:
            self._zip.close()
            raise UnsafeArchive(f"{path} has {len(infos)} entries")
        self._entries = [Entry(i.filename, i.file_size, i.compress_size, i.CRC) for i in infos]

    def close(self) -> None:
        self._zip.close()

    def entries(self) -> list[Entry]:
        return self._entries

    def _read(self, entry: Entry) -> bytes:
        try:
            with self._zip.open(entry.name) as handle:
                data = handle.read(MAX_ENTRY_BYTES + 1)  # zipfile checks the size and CRC as it goes
        except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
            raise ArchiveError(f"Could not read {entry.name}: {exc}") from exc
        if len(data) > MAX_ENTRY_BYTES:
            raise UnsafeArchive(f"{entry.name} unpacks to more than {MAX_ENTRY_BYTES} bytes")
        return data

    def open(self, name: str) -> IO[bytes]:
        entry = next((e for e in self._entries if e.name == name), None)
        if entry is None:
            raise ArchiveError(f"No entry {name!r}")
        _check(entry)
        return self._zip.open(name)  # seekable, so image headers are read lazily


_rar_lock = threading.Lock()
_rar_ready = threading.Event()
RAR_TOOLS = {"unar": "unar", "bsdtar": "bsdtar"}


def configure_rar_tools(unar: str, bsdtar: str) -> None:
    """Points rarfile at these binaries (the settings), before first use."""
    with _rar_lock:
        RAR_TOOLS.update(unar=unar, bsdtar=bsdtar)
        _rar_ready.clear()


def _ensure_rar_tools() -> None:
    if _rar_ready.is_set():
        return
    import rarfile

    with _rar_lock:
        if _rar_ready.is_set():
            return
        rarfile.UNAR_TOOL = RAR_TOOLS["unar"]
        rarfile.BSDTAR_TOOL = RAR_TOOLS["bsdtar"]
        try:
            rarfile.tool_setup(unrar=False, unar=True, bsdtar=True, sevenzip=False, sevenzip2=False, force=True)
        except rarfile.RarCannotExec:
            # Listing works without a tool; only decompression needs one.
            logger.warning(
                "Neither %s nor %s found: RAR pages can't be extracted", RAR_TOOLS["unar"], RAR_TOOLS["bsdtar"]
            )
        _rar_ready.set()


# RAR and 7z keep their directory in headers spread through the file, and a
# reader turning pages would otherwise read them again for every page. The
# listing is cached per (path, mtime, size), so a replaced file invalidates
# itself; bounded for a long-running process.
_LISTING_CACHE_MAX = 64
_listing_cache: dict[tuple[str, int, int], list[Entry]] = {}
_listing_lock = threading.Lock()


def _cached_listing(path: Path, lister: Any) -> list[Entry]:
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    with _listing_lock:
        cached = _listing_cache.get(key)
    if cached is not None:
        return cached
    entries: list[Entry] = lister(path)
    with _listing_lock:
        if len(_listing_cache) >= _LISTING_CACHE_MAX:
            _listing_cache.pop(next(iter(_listing_cache)))
        _listing_cache[key] = entries
    return entries


def clear_listing_cache() -> None:
    with _listing_lock:
        _listing_cache.clear()


def _list_rar(path: Path) -> list[Entry]:
    import rarfile

    try:
        with rarfile.RarFile(str(path)) as rf:
            infos = [i for i in rf.infolist() if not i.is_dir()]
    except (rarfile.Error, OSError) as exc:
        raise ArchiveError(f"Could not list {path}: {exc}") from exc
    if len(infos) > MAX_ENTRIES:
        raise UnsafeArchive(f"{path} has {len(infos)} entries")
    return [Entry(i.filename, i.file_size, i.compress_size, i.CRC if i.CRC else None) for i in infos]


def _list_7z(path: Path) -> list[Entry]:
    import py7zr

    try:
        with py7zr.SevenZipFile(path) as archive:
            if archive.needs_password():
                raise ArchiveError(f"{path} is encrypted")
            infos = [i for i in archive.list() if not i.is_directory]
    except (py7zr.Bad7zFile, OSError, ValueError) as exc:
        raise ArchiveError(f"Could not list {path}: {exc}") from exc
    if len(infos) > MAX_ENTRIES:
        raise UnsafeArchive(f"{path} has {len(infos)} entries")
    # Solid archives compress entries together, so a per-entry compressed
    # size isn't known and the ratio check can't apply.
    return [Entry(i.filename, i.uncompressed, i.compressed, i.crc32) for i in infos]


class RarArchive(Archive):
    def __init__(self, path: Path) -> None:
        _ensure_rar_tools()
        self._path = path
        self._entries = _cached_listing(path, _list_rar)

    def entries(self) -> list[Entry]:
        return self._entries

    def _read(self, entry: Entry) -> bytes:
        import rarfile

        try:
            with rarfile.RarFile(str(self._path)) as rf:
                data: bytes = rf.read(entry.name)
            if data:
                return data
            raise ArchiveError(f"{entry.name} decompressed to 0 bytes")
        except (rarfile.Error, ArchiveError, OSError) as exc:
            logger.warning("rarfile failed on %s in %s (%s), trying bsdtar", entry.name, self._path, exc)
        try:
            result = subprocess.run(
                [RAR_TOOLS["bsdtar"], "-x", "-O", "-f", str(self._path), entry.name],
                check=True, capture_output=True, timeout=60,
            )  # fmt: skip
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise ArchiveError(f"Could not extract {entry.name} from {self._path}: {exc}") from exc
        if not result.stdout or len(result.stdout) > MAX_ENTRY_BYTES:
            raise ArchiveError(f"bsdtar gave {len(result.stdout)} bytes for {entry.name}")
        return result.stdout


class SevenZipArchive(Archive):
    def __init__(self, path: Path) -> None:
        self._path = path
        self._entries = _cached_listing(path, _list_7z)

    def entries(self) -> list[Entry]:
        return self._entries

    def _read(self, entry: Entry) -> bytes:
        import py7zr
        from py7zr.io import BytesIOFactory

        factory = BytesIOFactory(MAX_ENTRY_BYTES)
        try:
            with py7zr.SevenZipFile(self._path) as archive:
                archive.extract(targets=[entry.name], factory=factory)
        except (py7zr.Bad7zFile, OSError, ValueError) as exc:
            raise ArchiveError(f"Could not extract {entry.name} from {self._path}: {exc}") from exc
        product = factory.products.get(entry.name)
        if product is None:
            raise ArchiveError(f"{entry.name} missing from {self._path}")
        product.seek(0)
        data: bytes = product.read()
        return data


class FolderArchive(Archive):
    """A folder of page images (and maybe a ComicInfo.xml): only its direct
    children count, and they are read straight from disk."""

    def __init__(self, path: Path) -> None:
        self._path = path
        children = [p for p in path.iterdir() if p.is_file()]
        if len(children) > MAX_ENTRIES:
            raise UnsafeArchive(f"{path} has {len(children)} files")
        self._entries = [Entry(p.name, p.stat().st_size) for p in children]

    def entries(self) -> list[Entry]:
        return self._entries

    def _read(self, entry: Entry) -> bytes:
        return (self._path / entry.name).read_bytes()

    def open(self, name: str) -> IO[bytes]:
        entry = next((e for e in self._entries if e.name == name), None)
        if entry is None:
            raise ArchiveError(f"No entry {name!r}")
        _check(entry)
        return (self._path / entry.name).open("rb")

    def page_paths(self) -> list[Path]:
        return [self._path / e.name for e in self.pages()]


def open_archive(path: Path) -> Archive:
    """The archive at ``path`` (a folder of images, or a zip, RAR or 7z
    file whatever its extension says)."""
    if path.is_dir():
        return FolderArchive(path)
    kind = sniff(path)
    if kind == "zip":
        return ZipArchive(path)
    if kind == "rar":
        return RarArchive(path)
    if kind == "7z":
        return SevenZipArchive(path)
    raise ArchiveError(f"{path} is not a zip, RAR or 7z archive")


def iter_pages(path: Path) -> Iterator[tuple[int, Entry, bytes]]:
    """Every page of a book in order, with its bytes."""
    with open_archive(path) as archive:
        for index, entry in enumerate(archive.pages()):
            yield index, entry, archive.read(entry.name)

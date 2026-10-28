"""Two identities per book file.

``content_id`` is Kodex's own: what the book *is*, unchanged by edits to
its metadata. For an archive or image folder it is a SHA-256 over the
pages' names, sizes and CRC-32s as the archive's directory records them,
read without decompressing anything. ComicInfo.xml and other metadata
files don't take part, so writing ComicInfo back into a CBZ keeps the id,
and so does converting a CBR to a CBZ (CRC-32 is over the uncompressed
data). An EPUB hashes its entries the same way, without the package
document (.opf) where its metadata lives; a PDF, with nothing like it,
gets a partial hash: its size and the same twelve 1 KiB samples as below.

``koreader_partial_md5`` is KOReader's document id, which its progress
sync (and Kobo's) sends: an MD5 over twelve 1 KiB samples at offsets 0,
1 KiB, 4 KiB, 16 KiB, ... 1 GiB, never reading the whole file. It must
match KOReader's util.partialMD5 byte for byte: its first offset is
bit.lshift(1024, -2), which LuaJIT masks to a shift of 30 and overflows to
0 (the reading Komga and calibre-web's ports use too). It changes whenever
the file does, so the ids a book has had are kept as aliases
(kodex.library.models.BookFileHash).
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

from app.models.enums import BookFormat
from kodex.formats import archive

_STEP = 1024
_SAMPLE_SIZE = 1024
_VERSION = b"kodex-content-1\n"


def _samples(path: Path) -> list[bytes]:
    found = []
    with path.open("rb") as handle:
        for i in range(-1, 11):
            handle.seek(0 if i == -1 else _STEP << (2 * i))
            sample = handle.read(_SAMPLE_SIZE)
            if not sample:
                break
            found.append(sample)
    return found


def koreader_partial_md5(path: Path) -> str:
    digest = hashlib.md5()
    for sample in _samples(path):
        digest.update(sample)
    return digest.hexdigest()


def image_folder_fingerprint(path: Path) -> str:
    """An image folder has no single file and KOReader can't open one: an
    MD5 over its sorted page names and sizes, identical for the same folder
    on two servers, just not a KOReader document id."""
    digest = hashlib.md5()
    for page in archive.FolderArchive(path).page_paths():
        digest.update(f"{page.name}:{page.stat().st_size}\n".encode())
    return digest.hexdigest()


def koreader_id(path: Path, file_format: BookFormat) -> str:
    if file_format == BookFormat.IMAGE_FOLDER:
        return image_folder_fingerprint(path)
    return koreader_partial_md5(path)


def _entries_digest(entries: list[archive.Entry], kind: bytes) -> str:
    digest = hashlib.sha256(_VERSION + kind)
    for entry in sorted(entries, key=lambda e: e.name):
        crc = "" if entry.crc is None else f"{entry.crc:08x}"
        digest.update(f"{entry.name}\0{entry.size}\0{crc}\n".encode())
    return digest.hexdigest()


def _epub_content(path: Path) -> list[archive.Entry]:
    with zipfile.ZipFile(path) as zf:
        return [
            archive.Entry(i.filename, i.file_size, i.compress_size, i.CRC)
            for i in zf.infolist()
            if not i.is_dir() and not i.filename.lower().endswith(".opf") and i.filename != "mimetype"
        ]


def content_id(path: Path, file_format: BookFormat) -> str:
    """Kodex's id for what the book is (see the module docstring)."""
    if file_format == BookFormat.EPUB and archive.sniff(path) == "zip":
        return _entries_digest(_epub_content(path), b"epub\n")
    if file_format in (BookFormat.CBZ, BookFormat.CBR, BookFormat.CB7, BookFormat.IMAGE_FOLDER):
        with archive.open_archive(path) as book:
            pages = book.pages()
        if pages:
            # Folders record no CRC, archives do; the kind keeps the two
            # from ever colliding while a CBR and its CBZ conversion agree.
            return _entries_digest(pages, b"folder\n" if file_format == BookFormat.IMAGE_FOLDER else b"pages\n")
    digest = hashlib.sha256(_VERSION + b"file\n")
    digest.update(str(path.stat().st_size).encode() + b"\n")
    for sample in _samples(path):
        digest.update(sample)
    return digest.hexdigest()

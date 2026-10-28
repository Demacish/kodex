"""Send to Kindle: a book mailed to the user's Kindle address. EPUB and PDF
go as they are, since Kindle reads both. Comics (CBZ, CBR, CB7, folders of
images) become a PDF first, one page per image and each page the image's
own size. JPEG pages are embedded unchanged, the others losslessly.

Runs as a job (send_to_kindle_task): building a long PDF and talking to an
SMTP server both take a while.
"""

from __future__ import annotations

import io
import smtplib
import tempfile
import zlib
from email.message import EmailMessage
from pathlib import Path
from typing import TYPE_CHECKING

from app.models.enums import BookFormat
from kodex.formats.archive import open_archive

if TYPE_CHECKING:
    import pikepdf

    from app.config import Settings
    from app.models.book import Book

# Kindle's own formats, sent unconverted.
_NATIVE = {BookFormat.EPUB: ("application", "epub+zip"), BookFormat.PDF: ("application", "pdf")}


class DeliveryError(RuntimeError):
    """A problem that won't go away by trying again (no SMTP server set up,
    a book without a known page count), as opposed to the mail server
    failing this once, which is left to raise as it is."""


def _require_smtp(settings: Settings) -> None:
    if not settings.smtp_host or not settings.smtp_from_address:
        raise DeliveryError(
            "SMTP är inte konfigurerat (SMTP_HOST/SMTP_FROM_ADDRESS); skicka till Kindle kan inte fungera förrän det är gjort"
        )


def build_pdf_from_pages(path: Path, file_format: BookFormat, page_count: int, dest_path: Path) -> Path:
    """A PDF of a comic's first ``page_count`` pages, each page the size of its image."""
    import pikepdf  # lazily: only conversions need it

    with open_archive(path) as archive, pikepdf.new() as pdf:
        for entry in archive.pages()[:page_count]:
            _add_image_page(pdf, archive.read(entry.name))
        pdf.save(str(dest_path))
    return dest_path


def _add_image_page(pdf: pikepdf.Pdf, data: bytes) -> None:
    """Appends one page exactly the size of the image (1 px = 1 pt)."""
    import pikepdf
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        width, height = image.size
        if image.format == "JPEG" and image.mode in ("RGB", "L"):
            mode = image.mode
            pdf_filter = pikepdf.Name.DCTDecode
        else:
            converted = image.convert("L" if image.mode in ("1", "L", "LA", "I", "I;16") else "RGB")
            mode = converted.mode
            data = zlib.compress(converted.tobytes())
            pdf_filter = pikepdf.Name.FlateDecode

    xobject = pikepdf.Stream(pdf, data)
    xobject.Type = pikepdf.Name.XObject
    xobject.Subtype = pikepdf.Name.Image
    xobject.Width = width
    xobject.Height = height
    xobject.ColorSpace = pikepdf.Name.DeviceGray if mode == "L" else pikepdf.Name.DeviceRGB
    xobject.BitsPerComponent = 8
    xobject.Filter = pdf_filter

    content = pikepdf.Stream(pdf, f"q {width} 0 0 {height} 0 0 cm /Im0 Do Q".encode())
    page = pikepdf.Dictionary(
        Type=pikepdf.Name.Page,
        MediaBox=[0, 0, width, height],
        Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im0=xobject)),
        Contents=content,
    )
    pdf.pages.append(pikepdf.Page(page))


def send_book_to_kindle(book: Book, absolute_path: Path, kindle_email: str, *, settings: Settings) -> None:
    """Mails the book (a comic converted to PDF first) to ``kindle_email``.
    DeliveryError for what needs fixing first; SMTP errors raise as they are,
    so the job is recorded as failed."""
    _require_smtp(settings)

    message = EmailMessage()
    message["From"] = settings.smtp_from_address
    message["To"] = kindle_email
    # Kindle reads only the attachment; the text is for a bounce.
    message["Subject"] = "Kodex"
    message.set_content("Skickat från Kodex.")

    native = _NATIVE.get(book.file_format)
    if native is not None:
        message.add_attachment(
            absolute_path.read_bytes(), maintype=native[0], subtype=native[1], filename=absolute_path.name
        )
    else:
        if not book.page_count:
            raise DeliveryError("Boken saknar känt sidantal; prova att skanna om biblioteket först")
        with tempfile.TemporaryDirectory(prefix="kodex-kindle-") as tmp_dir:
            pdf_path = Path(tmp_dir) / "book.pdf"
            build_pdf_from_pages(absolute_path, book.file_format, book.page_count, pdf_path)
            message.add_attachment(pdf_path.read_bytes(), maintype="application", subtype="pdf",
                                   filename=f"{absolute_path.stem}.pdf")  # fmt: skip

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=60) as smtp:
        smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)

from __future__ import annotations

import zipfile
from pathlib import Path

from app.enrichment.text import best_match, strip_html
from app.scanning.parsers.epub_meta import parse_epub_metadata

_CONTAINER_XML = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def _opf_with_identifier(identifier_xml: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" xmlns:opf="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>ISBN Test Book</dc:title>
    {identifier_xml}
  </metadata>
  <manifest/>
  <spine/>
</package>
"""


def _write_epub(path: Path, opf: str) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", _CONTAINER_XML)
        zf.writestr("content.opf", opf)


def test_parse_isbn_from_opf_scheme_attribute(tmp_path):
    opf = _opf_with_identifier('<dc:identifier opf:scheme="ISBN">978-91-1-234567-8</dc:identifier>')
    epub_path = tmp_path / "book.epub"
    _write_epub(epub_path, opf)

    result = parse_epub_metadata(epub_path)
    assert result["isbn"] == "9789112345678"


def test_parse_isbn_from_urn_identifier_without_scheme(tmp_path):
    opf = _opf_with_identifier("<dc:identifier>urn:isbn:9780306406157</dc:identifier>")
    epub_path = tmp_path / "book.epub"
    _write_epub(epub_path, opf)

    result = parse_epub_metadata(epub_path)
    assert result["isbn"] == "9780306406157"


def test_no_isbn_present_is_omitted(tmp_path):
    opf = _opf_with_identifier('<dc:identifier opf:scheme="calibre">some-internal-uuid</dc:identifier>')
    epub_path = tmp_path / "book.epub"
    _write_epub(epub_path, opf)

    result = parse_epub_metadata(epub_path)
    assert "isbn" not in result


def test_strip_html_removes_tags_and_collapses_whitespace():
    html = "<p>Hello <b>world</b>.</p><p>Second paragraph.</p>"
    assert strip_html(html) == "Hello world.\nSecond paragraph."
    assert strip_html(None) is None
    assert strip_html("") is None


def test_best_match_prefers_exact_then_substring_then_first():
    assert best_match("One Piece", ["One Piece", "One Piece Party"]) == 0
    assert best_match("One Piece", ["One Piece Party", "Something Else"]) == 0
    assert best_match("Naruto", ["Boruto", "Bleach"]) == 0
    assert best_match("Anything", []) is None


def test_parse_pdf_metadata_reads_docinfo(tmp_path):
    from app.scanning.parsers.pdf_meta import parse_pdf_metadata
    from tests.pdf_helpers import write_text_pdf

    path = write_text_pdf(tmp_path / "book.pdf", ["one", "two"], title=" A Title ", author="Ann Author, Bo Writer")
    assert parse_pdf_metadata(path) == {"page_count": 2, "title": "A Title", "authors": ["Ann Author", "Bo Writer"]}


def test_parse_pdf_metadata_without_docinfo_only_counts_pages(tmp_path):
    from app.scanning.parsers.pdf_meta import parse_pdf_metadata
    from tests.pdf_helpers import write_text_pdf

    path = write_text_pdf(tmp_path / "bare.pdf", ["only page"])
    assert parse_pdf_metadata(path) == {"page_count": 1}

"""kodex.formats: ComicInfo v2.1, MetronInfo, OPF readers and the
per-book embedded-metadata reader."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest

from app.models.enums import BookFormat
from kodex.formats.comicinfo import front_cover_index, parse_comicinfo_xml, parse_metroninfo_xml
from kodex.formats.embedded import read_embedded
from kodex.formats.opf import isbn13, parse_opf

COMICINFO = """<?xml version="1.0" encoding="utf-8"?>
<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="https://anansi-project.github.io/comicinfo">
  <Title>The Court of Owls</Title>
  <Series>Batman</Series>
  <Number>1</Number>
  <Count>52</Count>
  <Volume>2011</Volume>
  <Year>2011</Year>
  <Month>11</Month>
  <Publisher>DC Comics</Publisher>
  <Web>https://comicvine.gamespot.com/batman-1-the-court-of-owls/4000-290425/</Web>
  <Notes>Tagged with ComicTagger 1.6.0 using info from Comic Vine. [Issue ID 290425]</Notes>
  <Format>Series</Format>
  <Manga>No</Manga>
  <GTIN>76194130593600111</GTIN>
  <LocalizedSeries>Batman (svensk utgåva)</LocalizedSeries>
  <PageCount>3</PageCount>
  <Pages>
    <Page Image="0" Type="FrontCover" ImageWidth="1988" ImageHeight="3056" />
    <Page Image="1" />
    <Page Image="2" Type="Story" />
  </Pages>
</ComicInfo>
""".encode()

METRONINFO = b"""<?xml version="1.0" encoding="UTF-8"?>
<MetronInfo>
  <IDS>
    <ID source="Metron" primary="true">12345</ID>
    <ID source="Comic Vine">290425</ID>
    <ID source="Grand Comics Database">1234567</ID>
  </IDS>
  <Publisher id="2"><Name>DC Comics</Name></Publisher>
  <Series lang="en" id="789">
    <Name>Batman</Name>
    <SortName>Batman</SortName>
    <Volume>2</Volume>
    <Format>Single Issue</Format>
    <StartYear>2011</StartYear>
  </Series>
  <Number>1</Number>
  <CoverDate>2011-11-01</CoverDate>
  <GTIN><ISBN>9781401235413</ISBN><UPC>76194130593600111</UPC></GTIN>
</MetronInfo>
"""

OPF = b"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:identifier id="id">urn:isbn:0-316-12908-9</dc:identifier>
    <dc:identifier opf:scheme="GOODREADS">8855321</dc:identifier>
    <dc:title>Leviathan Wakes</dc:title>
    <dc:creator>James S. A. Corey</dc:creator>
    <dc:language>en</dc:language>
    <meta name="calibre:series" content="The Expanse"/>
    <meta name="calibre:series_index" content="1.0"/>
  </metadata>
</package>
"""


def test_comicinfo_reads_v21_fields():
    info = parse_comicinfo_xml(COMICINFO)
    assert info["series"] == "Batman"
    assert info["volume"] == "2011"
    assert info["count"] == 52
    assert info["year"] == 2011
    assert info["gtin"] == "76194130593600111"
    assert info["localized_series"] == "Batman (svensk utgåva)"
    assert info["pages"][0] == {"image": "0", "type": "FrontCover", "image_width": "1988", "image_height": "3056"}
    assert front_cover_index(info) == 0


def test_comicinfo_without_namespace_or_pages():
    info = parse_comicinfo_xml(b"<ComicInfo><Series> Saga </Series><Year>bad</Year></ComicInfo>")
    assert info == {"series": "Saga"}
    assert front_cover_index(info) is None


def test_metroninfo_ids_and_series():
    info = parse_metroninfo_xml(METRONINFO)
    assert info["ids"][0] == {"source": "Metron", "id": "12345", "primary": True}
    assert {i["source"] for i in info["ids"]} == {"Metron", "Comic Vine", "Grand Comics Database"}
    assert info["series"] == {
        "name": "Batman", "sort_name": "Batman", "format": "Single Issue", "volume": "2", "start_year": 2011,
        "language": "en", "id": "789",
    }  # fmt: skip
    assert info["publisher"] == "DC Comics"
    assert info["gtin"] == {"isbn": "9781401235413", "upc": "76194130593600111"}


def test_opf_calibre_series_and_isbn():
    opf = parse_opf(OPF)
    assert opf["title"] == "Leviathan Wakes"
    assert opf["authors"] == ["James S. A. Corey"]
    assert opf["identifiers"] == {"isbn": "9780316129084", "goodreads": "8855321"}
    assert (opf["series"], opf["series_index"]) == ("The Expanse", "1.0")


def test_opf_epub3_collection():
    opf = parse_opf(b"""<package xmlns="http://www.idpf.org/2007/opf"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
      <dc:title>Caliban's War</dc:title>
      <meta property="belongs-to-collection" id="c01">The Expanse</meta>
      <meta refines="#c01" property="collection-type">series</meta>
      <meta refines="#c01" property="group-position">2</meta>
    </metadata></package>""")
    assert (opf["series"], opf["series_index"]) == ("The Expanse", "2")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0-306-40615-2", "9780306406157"),
        ("978-0-306-40615-7", "9780306406157"),
        ("urn:isbn:9780306406157", "9780306406157"),
        ("080442957X", "9780804429573"),
        ("0-306-40615-3", None),
        ("978-0-306-40615-8", None),
        ("12345", None),
    ],
)
def test_isbn13(raw, expected):
    assert isbn13(raw) == expected


def test_read_embedded_from_cbz_cbr_folder_and_epub(tmp_path):
    cbz = tmp_path / "a.cbz"
    with zipfile.ZipFile(cbz, "w") as zf:
        zf.writestr("001.jpg", b"x")
        zf.writestr("ComicInfo.xml", COMICINFO)
        zf.writestr("MetronInfo.xml", METRONINFO)
    embedded = read_embedded(cbz, BookFormat.CBZ)
    assert embedded["comicinfo"]["series"] == "Batman"
    assert embedded["metroninfo"]["series"]["id"] == "789"

    cbr = tmp_path / "b.cbr"
    shutil.copyfile(Path(__file__).parent / "fixtures" / "cbr" / "comicinfo_number_2.rar5.cbr", cbr)
    assert read_embedded(cbr, BookFormat.CBR)["comicinfo"]["number"] == "2"

    folder = tmp_path / "loose"
    folder.mkdir()
    (folder / "ComicInfo.xml").write_bytes(COMICINFO)
    assert read_embedded(folder, BookFormat.IMAGE_FOLDER)["comicinfo"]["count"] == 52

    epub = tmp_path / "c.epub"
    with zipfile.ZipFile(epub, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
            '<rootfile full-path="OEBPS/content.opf"/></rootfiles></container>',
        )
        zf.writestr("OEBPS/content.opf", OPF)
    assert read_embedded(epub, BookFormat.EPUB)["opf"]["series"] == "The Expanse"


def test_read_embedded_survives_broken_files(tmp_path):
    cbz = tmp_path / "broken.cbz"
    with zipfile.ZipFile(cbz, "w") as zf:
        zf.writestr("ComicInfo.xml", b"<ComicInfo><Series>unclosed")
    assert read_embedded(cbz, BookFormat.CBZ) == {}
    not_a_zip = tmp_path / "garbage.cbz"
    not_a_zip.write_bytes(b"nope")
    assert read_embedded(not_a_zip, BookFormat.CBZ) == {}

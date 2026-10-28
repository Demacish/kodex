"""Builds small real PDFs for tests with pikepdf (text in the standard
Helvetica font, so no font file has to be embedded)."""

from __future__ import annotations

from pathlib import Path

import pikepdf


def write_text_pdf(path: Path, page_texts: list[str], *, title: str | None = None, author: str | None = None) -> Path:
    with pikepdf.new() as pdf:
        font = pdf.make_indirect(
            pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica)
        )
        for text in page_texts:
            escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            content = pikepdf.Stream(pdf, f"BT /F1 24 Tf 72 720 Td ({escaped}) Tj ET".encode())
            page = pikepdf.Dictionary(
                Type=pikepdf.Name.Page,
                MediaBox=[0, 0, 612, 792],
                Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font)),
                Contents=content,
            )
            pdf.pages.append(pikepdf.Page(page))
        if title is not None:
            pdf.docinfo["/Title"] = title
        if author is not None:
            pdf.docinfo["/Author"] = author
        pdf.save(path)
    return path


def page_sizes(path: Path) -> list[tuple[float, float]]:
    with pikepdf.open(path) as pdf:
        return [(float(p.mediabox[2]), float(p.mediabox[3])) for p in pdf.pages]

# 0001. MIT license

Status: Accepted (2026-10-25)

## Context

Kodex should be easy to adopt, package and build on. The license decides which
dependencies are allowed: AGPL libraries (PyMuPDF, EbookLib) and the
proprietary `unrar` cannot ship in an MIT server.

## Decision

MIT. PyMuPDF is replaced by pypdfium2 (rendering, text) and pikepdf (metadata,
PDF assembly); EPUB/OPF parsing stays on our own lxml/ElementTree code; RAR
goes through rarfile with `unar` or `bsdtar`.

## Consequences

Every new dependency is checked for compatibility; copyleft libraries are fine
only when used unmodified as libraries (LGPL, MPL) and are listed in `NOTICE`.
GPL/AGPL code is not copied, only ideas.

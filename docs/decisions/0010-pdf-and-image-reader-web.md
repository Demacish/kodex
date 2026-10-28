# 0010. pdf.js and our own image reader on the web

Status: Accepted (implemented in phase 3)

## Context

PDF needs a mature renderer; comics need fast paging.

## Decision

pdfjs-dist 6 (legacy build for older browsers) for PDF. Our own image reader
with preloading, reading pages re-encoded to WebP by the server with a
`{maxWidth}` parameter (the same one OPDS-PSE uses).

## Consequences

Page re-encoding is server work (pyvips, ADR 0015).

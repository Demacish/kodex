# 0014. Own OPDS 1.2/2.0 and Kobo sync implementations

Status: Accepted (written in phase 4, 2026-10-26; waiting for real clients)

## Context

No maintained OPDS 2.0 generator exists on PyPI, and `opds` is 1.2 only and
AGPL.

## Decision

Own Pydantic models for OPDS 2.0 JSON (RWPM, publications, navigation, facets,
groups) and Atom for OPDS 1.2 + PSE 1.2, validated in tests with `palace-
webpub-manifest-parser`. Kobo sync follows Komga's and Calibre-Web's pattern:
`v1/initialization`, `v1/library/sync` with `x-kobo-synctoken`,
`v1/library/{id}/state`, store proxy, KEPUB on the fly via kepubify.

As built (`kodex.delivery.opds`, `kodex.reading.kobo`):

- **OPDS 1.2** at `/opds`: reading now, newest, followed series, libraries,
  series, an OpenSearch title search, pages of 50 with first/previous/next/
  last links. Covers and streamed pages are JPEG (e-ink readers and older
  apps don't all show WebP); `{maxWidth}` narrows a page, and an unfilled
  template is ignored. Book ids are `urn:kodex:book:<id>`.
- **PSE progress**: PSE clients don't report progress, so the page they
  fetch is where they are, but only after the client has stayed on the
  previous one for two seconds: prefetching and downloading a whole book
  page by page don't count as reading.
- **OPDS 2.0** at `/opds/v2` with absolute links, and Readium's Progression
  draft at a book's `http://www.cantook.com/api/progression` link (as Cantook
  and Komga use it): GET and PUT of a locator with `position` and
  `totalProgression`.
- **Kobo**: the device is pointed at `/kobo/<Kobo key>` and syncs the EPUBs of
  one collection (by default the user's "Kobo" collection, chosen per key in
  Inställningar); removing a book on the device takes it out of the
  collection. Book ids are UUIDs made from the book id. Reading states go
  both ways through the journal: the device's own positions are `kobo`
  locators it gets back exactly, others reach it as a progression. With the
  store proxy on (the default), the store's library is synced too, with its
  own token inside ours, and every other request goes on to
  storeapi.kobo.com only; covers of store books are redirected to Kobo's
  image server. kepubify 4.0.4 is in the image, checked by checksum; without
  it the device gets the EPUB.
- Every client's progress lands in the reading journal, named after its key.

## Consequences

Verified against at least three real clients before it counts as done; the
tests use the clients' request shapes, not the clients. Kobo syncs EPUBs
only (comics go through OPDS or KOReader). The Kobo key is in the URL the
device calls, so it is in a reverse proxy's access log; revoking the key
stops the device.

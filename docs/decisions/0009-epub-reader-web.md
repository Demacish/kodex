# 0009. EPUB reader for the web

Status: Superseded by [0019](0019-epub-reader-foliate.md) (2026-10-26)

## Context

epub.js (v1) has been unmaintained since 2022. Candidates:
`@readium/navigator` (ts-toolkit 2.x, BSD-3) and foliate-js (MIT, active, no
releases).

## Decision

First choice `@readium/navigator`: released, has a roadmap, and uses the same
Locator model as Readium Kotlin on Android, so positions are shared without
conversion. It needs a Readium Web Publication manifest from the backend.
foliate-js is the fallback, vendored at a pinned commit.

## Consequences

The spike result is recorded by superseding this ADR.

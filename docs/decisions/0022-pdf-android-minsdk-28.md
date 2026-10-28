# 0022. androidx.pdf only, and minSdk 28

Status: Accepted (2026-10-26, phase 5). Supersedes [0012](0012-pdf-android.md).

## Context

ADR 0012 chose androidx.pdf (minSdk 28) with a Pdfium library for Android 8
(API 26 and 27). Android 8 is a small share of the devices still in use, and
the Pdfium libraries are native code the app would carry for them alone.

## Decision

The app's minSdk is 28. PDFs are read with androidx.pdf's Compose viewer
(`pdf-compose`, 1.0.0-beta01), which renders in a sandboxed service with the
platform's PDF renderer. There is no Pdfium fallback.

## Consequences

- Android 8 can't install the app; it can still read through the web
  client, OPDS or KOReader.
- androidx.pdf is a beta: the version is pinned and the catalog says so.
  Move to the stable release when it ships.

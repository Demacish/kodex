# 0012. androidx.pdf with a Pdfium fallback on Android

Status: Superseded by [0022](0022-pdf-android-minsdk-28.md) (2026-10-26)

## Context

AOSP `PdfRenderer` is bitmap-only and not thread-safe; barteksc PdfiumAndroid
is dormant without 16 KB page support.

## Decision

androidx.pdf 1.0 (beta, minSdk 28) for rendering, search and outline;
PdfiumAndroidKt or AhmerPdfium for minSdk 26.

## Consequences

Swap to stable androidx.pdf when it ships.

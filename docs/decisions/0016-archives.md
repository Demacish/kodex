# 0016. rarfile with unar/bsdtar, py7zr and puremagic

Status: Accepted

## Context

v1 shelled out to `unar` with the proprietary `unrar` as fallback, and used
`python-magic` (no release since 2022) for type detection.

## Decision

`rarfile` 4.5 (ISC) lists RAR4/RAR5 archives in-process and decompresses
through `unar`, falling back to `bsdtar` (phase 0, done). `py7zr` 1.1 (LGPL,
pure Python) reads CB7 (phase 2, done). The container is recognised by its
first bytes (zip, RAR, 7z, PDF signatures) in `kodex.formats.archive`; for
the handful of formats Kodex reads that is enough, so `puremagic` was not
added after all.

## Consequences

Creating RAR files is not possible without proprietary tools, so tests use
prebuilt RAR fixtures.

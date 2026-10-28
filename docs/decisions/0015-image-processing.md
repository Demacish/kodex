# 0015. pyvips for images, pypdfium2 for PDF pages

Status: Accepted (covers implemented in phase 2; page re-encoding follows with the readers)

## Context

Pillow loads whole images into memory; NAS-class machines have about 2 GB.

## Decision

pyvips 3.2 (`pyvips[binary]`) for covers, thumbnails and page re-encoding
(about 10x lower peak memory, 2x faster on large images); pypdfium2 for PDF
rasterisation (the pyvips wheels have no PDF loader); Pillow 13 for perceptual
hashing with `MAX_IMAGE_PIXELS` set.

## Consequences

libvips ships in the image (ADR 0018).

"""Panel-boundary detection for CBZ/CBR/image-folder pages — powers
"Guided View" (see app/models/panel.py and app/panels/service.py).

Runs OpenCV directly rather than depending on a third-party comic-panel
library: the obvious candidate, "kumiko", is not published to PyPI under a
name that's actually the comic-panel project — the "kumiko" package on
PyPI is an unrelated Discord-bot placeholder (confirmed 2026-09-20, installs
a 1KB stub with a different author and purpose entirely). Pulling the real
project in as a git/vendored dependency for an experimental,
kill-switchable feature wasn't worth the supply-chain risk when the
underlying algorithm is straightforward to implement directly against
OpenCV, which this project didn't previously depend on but ships as
opencv-python-headless (no GUI bindings needed in a server container).

Algorithm: recursive X-Y cut (aka "recursive gutter splitting"), the same
family of algorithm real panel segmentation tools use — not a flat
contour/blob scan. That distinction mattered in practice: an earlier
contour-based version of this module was tried against a real page from
this library (a modern full-bleed digital comic, art running edge-to-edge
with no white page margin, only ~10px gutters *between* panels) and failed
outright — a thin, edge-hugging dark artifact (compression ringing / a
subtle vignette a few px from the page border) bridged every panel into
one single blob via the page's own perimeter, regardless of the real
internal gutters. See _find_gutter below for how the margin exclusion
added to fix that works, and scripts/verify_panel_detection.py for the
page this was caught on.

This is a best-effort heuristic, not a guarantee. MIN_PANEL_AREA_RATIO and
MAX_SPLASH_AREA_RATIO are the two ways a page (or a leaf region within
one) is judged "not confidently panel-able" and left out of the result,
which is the signal callers use to fall back to showing the whole page
instead of a bad crop.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2

# A pixel darker than this (0-255 grayscale) counts as "content" rather
# than "gutter/background" when scanning for a cut. Comic gutters and page
# backgrounds are near-white paper in the vast majority of digital
# releases; a fixed threshold near white is far more robust here than an
# adaptive one (e.g. Otsu) — Otsu picks its split based on the whole
# region's brightness histogram, which a page dominated by a dark
# full-bleed panel skews badly (tried first, see module docstring).
_GUTTER_BRIGHTNESS_THRESHOLD = 235

# When scanning a row (or column) band as a gutter candidate, this fraction
# of the band's own outer width (or height) is excluded from the "is it
# dark" check on each side — see the module docstring's account of the
# edge-hugging artifact this works around. Applied at every recursion
# level using the ORIGINAL page's dimensions (not the current region's),
# since the artifact it compensates for is a property of the source scan,
# not of any one sub-region.
_EDGE_MARGIN_RATIO = 0.03

# Max fraction of dark pixels tolerated in a candidate gutter band's
# central (margin-excluded) portion — allows for JPEG noise, a stray
# speech-bubble tail, or antialiasing without disqualifying a real gutter.
# Horizontal (row) gutters get a looser tolerance than vertical (column)
# ones: verified against a real page in this library where a genuine
# inter-panel gutter measured ~3.2% dark (border-corner antialiasing
# bleeding into the margin-excluded zone) — tightening this to catch it
# would have made no difference for vertical cuts, since the false
# positives found there (see module docstring) were themselves *cleaner*
# (0% dark) than real gutters, being genuine blank negative space in the
# art rather than ink bleed. Column cuts are guarded by
# _MAX_PANEL_ASPECT_RATIO instead — see detect_panels.
_GUTTER_DARK_TOLERANCE_HORIZONTAL = 0.04
_GUTTER_DARK_TOLERANCE_VERTICAL = 0.02

# Minimum thickness of a gutter band, as a fraction of the ORIGINAL page's
# shorter dimension — rejects single-pixel-noise "gaps" that aren't a real
# gutter between panels.
_MIN_GUTTER_THICKNESS_RATIO = 0.003

# A region smaller than this fraction of the total page area is never
# split further and never kept as a leaf — see MIN_PANEL_AREA_RATIO below,
# same constant, named for its two uses (recursion base case + leaf
# filter).
MIN_PANEL_AREA_RATIO = 0.02

# A single leaf region covering more than this fraction of the page is
# treated as a splash/full-page image, not a panel — Guided View has
# nothing useful to zoom into on those, so a page that cuts down to just
# one such region is left with zero detected panels (same as a page where
# no cut was found at all).
MAX_SPLASH_AREA_RATIO = 0.85

# A leaf whose long side is more than this many times its short side is
# rejected as a sliver, not a panel — real comic panels are essentially
# never this elongated. This is what actually catches the naturalistic-
# negative-space false positive described in the module docstring (a
# vertical "gutter" found between two illustrated tree trunks): it's not
# distinguishable from a real gutter by cleanliness or thickness alone
# (verified — some false positives measured *cleaner* than real gutters),
# but the resulting sliver shape is.
MAX_PANEL_ASPECT_RATIO = 6.0

# The surviving leaves (after the area/aspect filters above) must together
# cover at least this fraction of the page, or the whole page is rejected
# — returned as zero panels, same as "no cut found at all" — rather than
# handed back as a partial set. Filtering leaves individually (area/aspect
# above) can legitimately drop a handful of small sliver fragments, but if
# enough got dropped that real page content isn't covered by anything
# left, the danger is silently *missing* content in Guided View (someone
# stepping panel-by-panel would skip over a chunk of the page) rather than
# just a wrong crop — worse than falling back to the ordinary full-page
# view. Verified against a real page in this library where naturalistic
# negative space (see MAX_PANEL_ASPECT_RATIO's docstring) over-split one
# wide panel into several pieces, three of which were individually too
# small/sliver-shaped to keep: total coverage came out to ~88%, below this
# threshold — correctly rejects that page instead of returning a Guided
# View with a hole in it.
MIN_TOTAL_COVERAGE_RATIO = 0.9

# Recursion safety net — real panel grids are never this deep; hitting
# this means the gutter-detection parameters above are misbehaving on a
# given page, not that there's a genuine 8-level-deep layout to find.
_MAX_RECURSION_DEPTH = 8


@dataclass
class Panel:
    """Normalized (0..1) bounding box, in canonical top-to-bottom,
    left-to-right reading order (a horizontal cut orders its two halves
    top-then-bottom, a vertical cut orders its two halves left-then-right
    — see _cut below). Reversing that order for right-to-left (manga)
    reading is left to the reader frontend, same as it already reverses
    spread-pair order — see ImageReader.tsx's orderedSpreadIndexes.
    """

    x: float
    y: float
    w: float
    h: float


def detect_panels(image_path: Path) -> list[Panel]:
    """Best-effort panel segmentation for one comic page. Returns an empty
    list if the page doesn't look confidently panel-able (see the module
    docstring) — callers should treat that the same as "no panel data",
    not as an error.
    """
    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"OpenCV could not read {image_path}")

    height, width = img.shape[:2]
    if height == 0 or width == 0:
        return []

    is_dark = img < _GUTTER_BRIGHTNESS_THRESHOLD
    margin_x = max(1, int(width * _EDGE_MARGIN_RATIO))
    margin_y = max(1, int(height * _EDGE_MARGIN_RATIO))
    min_gutter_px = max(4, int(min(width, height) * _MIN_GUTTER_THICKNESS_RATIO))
    page_area = width * height

    leaves = _cut(is_dark, 0, 0, width, height, margin_x, margin_y, min_gutter_px, depth=0)

    boxes = []
    for x0, y0, x1, y1 in leaves:
        box_w, box_h = x1 - x0, y1 - y0
        area_ratio = (box_w * box_h) / page_area
        if area_ratio < MIN_PANEL_AREA_RATIO or area_ratio > MAX_SPLASH_AREA_RATIO:
            continue
        if max(box_w, box_h) / max(1, min(box_w, box_h)) > MAX_PANEL_ASPECT_RATIO:
            continue
        boxes.append((x0, y0, x1, y1))

    if len(boxes) < 2:
        # Zero panels (nothing left after filtering) or a single panel (no
        # real grid to guide through) — both are "not panel-able", see the
        # module docstring.
        return []

    covered = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in boxes)
    if covered / page_area < MIN_TOTAL_COVERAGE_RATIO:
        # See MIN_TOTAL_COVERAGE_RATIO's docstring — a partial set that
        # leaves out real page content is worse than no set at all.
        return []

    return [Panel(x=x0 / width, y=y0 / height, w=(x1 - x0) / width, h=(y1 - y0) / height) for (x0, y0, x1, y1) in boxes]


def _cut(
    is_dark,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    margin_x: int,
    margin_y: int,
    min_gutter_px: int,
    depth: int,
) -> list[tuple[int, int, int, int]]:
    """Recursively splits (x0,y0,x1,y1) on the first qualifying gutter band
    it finds — horizontal cuts (splitting top/bottom) tried before vertical
    ones (splitting left/right), matching how most comic layouts are
    primarily row-based with occasional column splits within a row.
    Returns the leaf regions in reading order (see Panel's docstring).
    """
    if depth >= _MAX_RECURSION_DEPTH or x1 - x0 < min_gutter_px or y1 - y0 < min_gutter_px:
        return [(x0, y0, x1, y1)]

    cut_y = _find_gutter(is_dark, x0, y0, x1, y1, margin_x, min_gutter_px, horizontal=True)
    if cut_y is not None:
        top = _cut(is_dark, x0, y0, x1, cut_y, margin_x, margin_y, min_gutter_px, depth + 1)
        bottom = _cut(is_dark, x0, cut_y, x1, y1, margin_x, margin_y, min_gutter_px, depth + 1)
        return top + bottom

    cut_x = _find_gutter(is_dark, x0, y0, x1, y1, margin_y, min_gutter_px, horizontal=False)
    if cut_x is not None:
        left = _cut(is_dark, x0, y0, cut_x, y1, margin_x, margin_y, min_gutter_px, depth + 1)
        right = _cut(is_dark, cut_x, y0, x1, y1, margin_x, margin_y, min_gutter_px, depth + 1)
        return left + right

    return [(x0, y0, x1, y1)]


def _find_gutter(
    is_dark, x0: int, y0: int, x1: int, y1: int, cross_margin: int, min_gutter_px: int, *, horizontal: bool
) -> int | None:
    """Looks for the first (topmost, or leftmost) contiguous band of
    rows/columns within (x0,y0,x1,y1) that's clean enough to be a gutter,
    ignoring cross_margin pixels on each side of the band when judging
    "clean" (see _EDGE_MARGIN_RATIO's docstring). Returns the pixel
    coordinate to cut at (the middle of the qualifying band) along the
    scanned axis, or None if no band in this region qualifies.
    """
    if horizontal:
        lo, hi = x0 + cross_margin, x1 - cross_margin
        if hi <= lo:
            lo, hi = x0, x1  # region too narrow for a margin — fall back to using it all
        region = is_dark[y0:y1, lo:hi]
        dark_frac = region.mean(axis=1) if region.size else region
        span = y1 - y0
        coord0 = y0
        tolerance = _GUTTER_DARK_TOLERANCE_HORIZONTAL
    else:
        lo, hi = y0 + cross_margin, y1 - cross_margin
        if hi <= lo:
            lo, hi = y0, y1
        region = is_dark[lo:hi, x0:x1]
        dark_frac = region.mean(axis=0) if region.size else region
        span = x1 - x0
        coord0 = x0
        tolerance = _GUTTER_DARK_TOLERANCE_VERTICAL

    # A qualifying band must close before the far edge of the region (a
    # band still "open" when the scan ends is a blank margin running to
    # the true edge, not a gutter between two panels — cutting there would
    # just produce an empty leftover region on one side).
    band_start = None
    for i in range(span):
        clean = i < len(dark_frac) and dark_frac[i] <= tolerance
        if clean and band_start is None:
            band_start = i
        elif not clean and band_start is not None:
            if i - band_start >= min_gutter_px and band_start > 0:
                return coord0 + (band_start + i) // 2
            band_start = None
    return None

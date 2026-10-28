"""Tests for app/panels/detector.py's recursive gutter-cut panel
segmentation. Uses synthetic pages (drawn rectangles on a white canvas)
rather than real comic art for two reasons: real page art can't be
committed to this repo (copyright, and it's the user's own library, not a
test fixture), and synthetic pages give exact, known-correct panel
boundaries to assert against — a real page can only be spot-checked by
eye (see scripts/verify_panel_detection.py for that).
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.panels import detector


def _blank_page(width: int = 1200, height: int = 1800) -> np.ndarray:
    return np.full((height, width), 255, dtype=np.uint8)


def _draw_panel(img: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> None:
    """Fills a rectangle with mid-gray "art" and an inset near-black
    border stroke — mimicking a real bordered panel closely enough for the
    detector's brightness-based gutter scan (see detector.py's own
    docstring for why it works on brightness, not literal edge/line
    detection).
    """
    cv2.rectangle(img, (x0, y0), (x1 - 1, y1 - 1), color=120, thickness=-1)
    cv2.rectangle(img, (x0 + 4, y0 + 4), (x1 - 5, y1 - 5), color=10, thickness=6)


def _save(tmp_path: Path, name: str, img: np.ndarray) -> Path:
    path = tmp_path / name
    cv2.imwrite(str(path), img)
    return path


def test_two_row_layout_detected_in_reading_order(tmp_path):
    img = _blank_page()
    h, w = img.shape
    gutter = 40
    _draw_panel(img, 0, 0, w, h // 2 - gutter // 2)
    _draw_panel(img, 0, h // 2 + gutter // 2, w, h)
    path = _save(tmp_path, "two-row.png", img)

    panels = detector.detect_panels(path)

    assert len(panels) == 2
    assert panels[0].y < panels[1].y  # top panel first


def test_two_by_two_grid_reading_order(tmp_path):
    img = _blank_page()
    h, w = img.shape
    gutter = 40
    mid_x, mid_y = w // 2, h // 2
    _draw_panel(img, 0, 0, mid_x - gutter // 2, mid_y - gutter // 2)
    _draw_panel(img, mid_x + gutter // 2, 0, w, mid_y - gutter // 2)
    _draw_panel(img, 0, mid_y + gutter // 2, mid_x - gutter // 2, h)
    _draw_panel(img, mid_x + gutter // 2, mid_y + gutter // 2, w, h)
    path = _save(tmp_path, "grid.png", img)

    panels = detector.detect_panels(path)

    assert len(panels) == 4
    # Row-major: top-left, top-right, bottom-left, bottom-right.
    assert panels[0].x < panels[1].x and panels[0].y < panels[2].y
    assert panels[2].x < panels[3].x
    assert panels[0].y == pytest.approx(panels[1].y, abs=0.01)
    assert panels[2].y == pytest.approx(panels[3].y, abs=0.01)


def test_single_splash_page_returns_no_panels(tmp_path):
    img = _blank_page()
    h, w = img.shape
    _draw_panel(img, 0, 0, w, h)
    path = _save(tmp_path, "splash.png", img)

    assert detector.detect_panels(path) == []


def test_blank_page_returns_no_panels(tmp_path):
    path = _save(tmp_path, "blank.png", _blank_page())

    assert detector.detect_panels(path) == []


def test_edge_bleeding_content_does_not_merge_into_one_blob(tmp_path):
    """Regression test for the failure mode described in detector.py's
    module docstring: panel art that runs to the page's own edges (no
    white page margin, only gutters *between* panels) used to get bridged
    into one giant blob by a thin dark artifact along the page perimeter.
    Here the "artifact" is simulated directly: a 2px near-black frame
    around the whole page, with two real bordered panels stacked inside
    it and nothing else touching the edges in between.
    """
    img = _blank_page()
    h, w = img.shape
    cv2.rectangle(img, (0, 0), (w - 1, h - 1), color=15, thickness=2)
    gutter = 40
    _draw_panel(img, 20, 20, w - 20, h // 2 - gutter // 2)
    _draw_panel(img, 20, h // 2 + gutter // 2, w - 20, h - 20)
    path = _save(tmp_path, "edge-bleed.png", img)

    panels = detector.detect_panels(path)

    assert len(panels) == 2
    assert panels[0].y < panels[1].y


def test_thin_sliver_gap_is_not_treated_as_a_panel(tmp_path):
    """A vertical gap that's clean but too narrow/tall to plausibly be a
    real panel (see MAX_PANEL_ASPECT_RATIO) must not end up as its own
    detected panel — regression test for the naturalistic-negative-space
    false positive described in the module docstring.
    """
    img = _blank_page()
    h, w = img.shape
    # A real panel, plus a thin (20px) clean vertical strip right beside
    # it that a naive gutter scan could mistake for a second, sliver-shaped
    # panel rather than dead space.
    _draw_panel(img, 0, 0, w - 200, h)
    path = _save(tmp_path, "sliver.png", img)

    panels = detector.detect_panels(path)

    # Only one real panel exists on this page — the blank strip must not
    # surface as a second one, and a single real panel alone means "not
    # panel-able" (see detect_panels' own docstring), so this must be [].
    assert panels == []

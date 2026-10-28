"""Tests for kodex/acquire/clients/manager.py's map_download_path."""

from __future__ import annotations

from kodex.acquire.clients.manager import map_download_path


def test_map_download_path_rewrites_matching_prefix():
    result = map_download_path("/downloads/complete/Comic.cbz", "/downloads:/data/downloads")
    assert result == "/data/downloads/complete/Comic.cbz"


def test_map_download_path_no_mapping_is_a_noop():
    assert map_download_path("/downloads/x.cbz", "") == "/downloads/x.cbz"


def test_map_download_path_malformed_mapping_is_a_noop():
    assert map_download_path("/downloads/x.cbz", "no-colon-here") == "/downloads/x.cbz"


def test_map_download_path_non_matching_prefix_is_unchanged():
    result = map_download_path("/other/path/x.cbz", "/downloads:/data/downloads")
    assert result == "/other/path/x.cbz"

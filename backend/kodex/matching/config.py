"""Matching configuration: the defaults in matching.toml, overridden by the
file KODEX_MATCHING_CONFIG names (only the keys it sets)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

_DEFAULTS = Path(__file__).with_name("matching.toml")


@dataclass(frozen=True)
class MatchingConfig:
    weights: dict[str, float]
    auto_min: float
    auto_margin: float
    auto_single: float
    review_min: float
    min_positive_signals: int
    title_gate: float
    prefilter_ratio_min: float
    cover_strong: int
    cover_weak: int
    cover_top_n: int
    cover_min_title: float
    search_ttl_days: int
    id_ttl_days: int
    max_candidates: int
    issue_lists: int
    providers: dict[str, list[str]] = field(default_factory=dict)
    grouping_strategy: str = "metadata"
    write_back: dict[str, bool] = field(default_factory=dict)
    llm_enabled: bool = False
    llm_max_calls_per_day: int = 50
    comics_language: str | None = None
    publisher_languages: dict[str, str] = field(default_factory=dict)
    publisher_language_words: dict[str, str] = field(default_factory=dict)


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        merged[key] = (
            _merge(merged[key], value) if isinstance(value, dict) and isinstance(merged.get(key), dict) else value
        )
    return merged


def load_config(override: Path | None = None) -> MatchingConfig:
    data = tomllib.loads(_DEFAULTS.read_text())
    path = override or (Path(os.environ["KODEX_MATCHING_CONFIG"]) if os.environ.get("KODEX_MATCHING_CONFIG") else None)
    if path is not None:
        data = _merge(data, tomllib.loads(path.read_text()))
    return MatchingConfig(
        weights={k: float(v) for k, v in data["weights"].items()},
        auto_min=data["auto_min"],
        auto_margin=data["auto_margin"],
        auto_single=data["auto_single"],
        review_min=data["review_min"],
        min_positive_signals=data["min_positive_signals"],
        title_gate=data["title_gate"],
        prefilter_ratio_min=data["prefilter"]["ratio_min"],
        cover_strong=data["cover"]["strong"],
        cover_weak=data["cover"]["weak"],
        cover_top_n=data["cover"]["top_n"],
        cover_min_title=data["cover"]["min_title"],
        search_ttl_days=data["cache"]["search_ttl_days"],
        id_ttl_days=data["cache"]["id_ttl_days"],
        max_candidates=data["search"]["max_candidates"],
        issue_lists=data["search"]["issue_lists"],
        providers={k: list(v["order"]) for k, v in data["providers"].items()},
        grouping_strategy=data["grouping"]["strategy"],
        write_back={k: bool(v) for k, v in data["write_back"].items()},
        llm_enabled=data["llm"]["enabled"],
        llm_max_calls_per_day=data["llm"]["max_calls_per_day"],
        comics_language=(data.get("language") or {}).get("comics_default") or None,
        publisher_languages=dict(data.get("publisher_languages") or {}),
        publisher_language_words=dict(data.get("publisher_language_words") or {}),
    )


@lru_cache
def get_config() -> MatchingConfig:
    return load_config()

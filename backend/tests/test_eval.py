"""The matching engine's evaluation as a gate (docs/plan.sv.md, phase 1):
precision of automatic decisions at least 0.98, at most 25 % to review
in total and 10 % for dated US issues, never an automatic match when the
right run isn't at the provider, and no stratum worse than the committed
baseline (tests/golden/eval_baseline.json)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kodex.matching.config import load_config
from kodex.matching.eval import build_corpus, evaluate, totals

BASELINE = json.loads((Path(__file__).parent / "golden" / "eval_baseline.json").read_text())


@pytest.fixture(scope="module")
def reports():
    cases, providers, books = build_corpus(BASELINE["seed"])
    return evaluate(cases, providers, books, load_config())


def test_corpus_is_big_and_stratified(reports):
    assert sum(r.n for r in reports.values()) >= 500
    assert {"us_dated", "us_undated", "tpb", "annual", "manga_romaji", "manga_english", "manga_cjk", "manga_volumes", "translated", "tpb_unlinked", "ebook_isbn",
            "ebook_title", "no_true_match"} <= set(reports)  # fmt: skip


def test_plan_gates(reports):
    total = totals(reports)
    assert total.precision is not None and total.precision >= 0.98, total.wrong[:5]
    assert total.review_share <= 0.25
    assert reports["us_dated"].review_share <= 0.10
    assert reports["no_true_match"].auto == 0, reports["no_true_match"].wrong


@pytest.mark.parametrize("stratum", sorted(BASELINE["strata"]))
def test_no_regression_against_the_baseline(reports, stratum):
    base, now = BASELINE["strata"][stratum], reports[stratum]
    if base["precision"] is not None:
        assert now.precision is not None and now.precision >= base["precision"] - 0.01, now.wrong[:5]
    if base["recall"] is not None:
        assert now.recall is not None and now.recall >= base["recall"] - 0.05
    assert now.review_share <= base["review_share"] + 0.05

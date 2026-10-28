from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class CsvImportRowOut(BaseModel):
    row_index: int
    raw_title: str
    raw_author: str | None
    raw_issue_number: str | None
    bucket: Literal["matched", "needs_review", "unmatched"]
    score: float
    matched_series_id: int | None
    matched_series_title: str | None
    book_ids: list[int]


class CsvImportPreviewOut(BaseModel):
    matched: list[CsvImportRowOut]
    needs_review: list[CsvImportRowOut]
    unmatched: list[CsvImportRowOut]


class CsvImportConfirmIn(BaseModel):
    name: str
    book_ids: list[int]

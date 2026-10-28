"""Tiny text-cleanup helpers shared by enrichment providers, all of which
return HTML-ish description fields.
"""

from __future__ import annotations

import difflib
import re

# Comic Vine descriptions are real HTML, not just <p>/<br> — headings
# (section titles like "Collected Editions"), <figure> (an embedded
# image, no useful text — just markup/attributes, which _TAG_RE already
# safely eats), and lists all show up in practice. Only closing </p> and
# <br> used to get a line break; every other block boundary had NO
# break at all, so e.g. "<h2>The Broken Bat</h2><figure>...</figure><p>
# Following Bane's...` rendered as the glued-together "Broken Bat
# Following Bane's..." with zero separation — found 2026-09-11 looking
# at a real synopsis (see cbl.py's link() route, the first place this
# app started showing these descriptions to a user instead of just
# using them internally). Both the opening AND closing tag of every
# block-level element now force a break, not just </p>.
_BLOCK_TAG_RE = re.compile(r"</?(?:p|h[1-6]|li|div|figure|ul|ol|table|tr|td)\b[^>]*>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"[ \t]+")
_ALNUM_RE = re.compile(r"[^a-z0-9]")

# Under this, a fallback (no exact/substring hit) candidate is rejected
# rather than guessed. Picked 2026-09-17 against real e-book filenames:
# confirmed-wrong matches scored 0.20/0.46 (a run-together file name
# against an unrelated title, or another book on the same subject),
# confirmed-right matches scored 0.63-1.0 (messy filename vs the real,
# properly formatted title) - see best_match()'s docstring.
_FALLBACK_SIMILARITY_THRESHOLD = 0.5


def _similarity(a: str, b: str) -> float:
    """Rough alphanumeric-only similarity, robust to the spacing/case/
    punctuation differences between a filename-derived query and a
    properly formatted real title (e.g. "cplusplusgardenreference" vs
    "C++ Garden Reference")."""
    return difflib.SequenceMatcher(None, _ALNUM_RE.sub("", a.lower()), _ALNUM_RE.sub("", b.lower())).ratio()


def strip_html(text: str | None) -> str | None:
    if not text:
        return None
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = _BLOCK_TAG_RE.sub("\n\n", text)
    text = _TAG_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text)
    lines = [line.strip() for line in text.splitlines()]
    cleaned = "\n".join(line for line in lines if line)
    return cleaned.strip() or None


def best_match(query: str, candidates: list[str], weights: list[float] | None = None) -> int | None:
    """Return the index of the candidate that best matches `query`, using a
    simple case-insensitive exact/substring heuristic — good enough for
    picking a series/volume out of a small search result list without
    pulling in a fuzzy-matching dependency. Returns None if candidates is
    empty.

    `weights` (same length as `candidates`, higher is better) only breaks
    ties *within* the exact-match or substring-match tier — it never lets
    a lower tier win over a higher one. Needed because a provider can
    legitimately return several candidates with the identical name (e.g.
    Comic Vine listing both an ongoing series and its own collected-
    editions line as two different volumes both literally named "Absolute
    Batman") — without a secondary signal the first one in provider-
    relevance order wins, which is arbitrary and was observed to pick a
    3-issue trade-collection volume over the actual 23-issue series.
    """
    if not candidates:
        return None

    def best_of(indices: list[int]) -> int:
        if not weights:
            return indices[0]
        return max(indices, key=lambda i: weights[i])

    normalized_query = query.strip().lower()
    exact = [i for i, candidate in enumerate(candidates) if candidate.strip().lower() == normalized_query]
    if exact:
        return best_of(exact)
    substring = [i for i, candidate in enumerate(candidates) if normalized_query in candidate.strip().lower()]
    if substring:
        return best_of(substring)

    # No exact/substring hit - used to unconditionally return 0 (blindly
    # trust the provider's top relevance result), which produced confident
    # wrong matches for messy filename-derived queries (see the threshold's
    # own docstring above for real examples). Only accept the best-scoring
    # candidate now if it's actually similar enough; otherwise no match is
    # better than a wrong one.
    ranked = max(range(len(candidates)), key=lambda i: _similarity(normalized_query, candidates[i].strip().lower()))
    if _similarity(normalized_query, candidates[ranked].strip().lower()) >= _FALLBACK_SIMILARITY_THRESHOLD:
        return ranked
    return None

"""Filename and folder-name parser for comics, manga and e-books.

Turns a name like ``[Group] Title - c012 (v03) [Digital].cbz`` or
``Batman v2 #012 (of 12) (2016) (Digital).cbz`` into a :class:`ParsedName`.
The vocabulary follows the plan's glossary: *volume* is a manga or
collected-edition book (``v03``, ``Vol. 3``, ``第3巻``) and never an issue,
*issue* is a single comic issue (``#12``, ``012``), *chapter* a manga
chapter (``c012``, ``Ch. 12``, ``第12话``).

How a name is read, in order:

1. The extension is dropped, everything after ``--`` or ``__`` is ignored,
   and underscores (or dots, in names without spaces) become spaces.
2. Text in ``[]``, ``()`` and ``{}`` is lifted out as tags, unless the
   brackets are glued to words on both sides (``rent-a-(really shy)-
   girlfriend``). Tags are classified: years, ``(of N)``, volume tags such
   as ``(v03)``, format words (``TPB``), languages, a leading ``[Group]``
   as the scan group, and everything else as an extra tag.
3. The rest is tokenised and the numbers are assigned by priority:

   ========  ===========================================================
   priority  rule
   ========  ===========================================================
   1         ``#N`` is the issue
   2         volume and chapter markers (``v03``, ``c012``, ``第3巻``,
             ``Глава 12`` …) give volume and chapter, never issue; a
             second marker of the same kind is dropped unless it is a range
   3         ``SP01`` is special number 1; ``Annual``/``Special``/
             ``One-Shot``/``TPB``/``Omnibus``/``HC`` set the format; a
             year-like number right before or after ``Annual``/``Special``
             is its year
   4         ``N of M`` and ``(of M)`` give the issue count
   5         the last bare number before a `` - Title`` part is the issue
             (comics) or the chapter (manga); numbers before it belong to
             the series name (``100 Bullets``, ``2000 AD``, ``Batman Beyond
             2.0``)
   6         a year-like last number with no other number is a year and
             the name is marked ``ambiguous`` (``Batman 1989``)
   ========  ===========================================================

4. A ``(YYYY)`` directly after the series name is the series' start year,
   one after the number is the issue's year.

``series_hint`` (the series folder's name) settles names whose series
itself ends in a number: when the name starts with it, that prefix is the
series and only the rest is searched for numbers.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, replace
from typing import Literal

# Bumped whenever a change makes stored parse results (Book.parsed) stale,
# which rereads each book's name and embedded metadata once.
# 2: PDFs' own title, authors and ISBNs are read.
# 3: a comic without a number and with more than 100 pages is collected.
# 4: "Book N" leaves the series name; download sites are dropped.
PARSER_VERSION = 4

Kind = Literal["comic", "manga", "book"]
Format = Literal["issue", "collected", "annual", "special", "one_shot", "chapter", "volume", "book"]

_EXTENSIONS = {"cbz", "cbr", "cb7", "cbt", "zip", "rar", "7z", "tar", "pdf", "epub", "kepub", "mobi", "azw3"}
_YEAR_MIN, _YEAR_MAX = 1930, 2030

_FRACTIONS = {"½": ".5", "¼": ".25", "¾": ".75", "⅓": ".33", "⅔": ".67"}
_NUMBER = r"-?\d+(?:\.\d+)?(?:[½¼¾⅓⅔]|[a-z](?![a-z]))?"
_NUMBER_RE = re.compile(rf"^(?:{_NUMBER}|[½¼¾⅓⅔])$", re.IGNORECASE)
_SUFFIXED_ISSUE_RE = re.compile(r"^(\d+)\.([A-Z]{1,4})$")  # 1.MU, 1.NOW
_RANGE_RE = re.compile(rf"^({_NUMBER})-({_NUMBER})$", re.IGNORECASE)

# Markers glued to their number ("v03", "c012", "#12", "第3巻") or followed
# by it as the next token ("Vol. 3", "Chapter 12", "Том 3").
_VOLUME_GLUED = re.compile(r"^(?:v|vol\.?|volume|t|tome|s)(\d+(?:\.\d+)?)$", re.IGNORECASE)
_VOLUME_GLUED_RANGE = re.compile(r"^(?:v|vol\.?)(\d+)-(?:v)?(\d+)$", re.IGNORECASE)
_VOLUME_WORDS = {"v", "v.", "vol", "vol.", "volume", "tome", "tom", "том", "т.", "book"}
_CHAPTER_GLUED = re.compile(rf"^(?:c|ch\.?|chp\.?|chapter|ep\.?|episode)({_NUMBER})(?:-({_NUMBER}))?$", re.IGNORECASE)
_CHAPTER_WORDS = {"c", "ch", "ch.", "chp", "chp.", "chapter", "ep", "ep.", "episode", "глава", "гл."}
_CJK_VOLUME = re.compile(r"^第?(\d+)[巻卷]$|^제?(\d+)권$")
_CJK_CHAPTER = re.compile(r"^第?(\d+(?:\.\d+)?)[话話回]$|^제?(\d+(?:\.\d+)?)화$")
_HASH = re.compile(rf"^#({_NUMBER}|\d+\.[A-Z]{{1,4}})$", re.IGNORECASE)
_SPECIAL_CODE = re.compile(r"^sp(\d+)$", re.IGNORECASE)

_FORMAT_WORDS: dict[str, tuple[Format, str | None]] = {
    "annual": ("annual", None),
    "special": ("special", None),
    "fcbd": ("special", "FCBD"),
    "one-shot": ("one_shot", None),
    "oneshot": ("one_shot", None),
    "tpb": ("collected", "TPB"),
    "omnibus": ("collected", "Omnibus"),
    "hc": ("collected", "HC"),
    "hardcover": ("collected", "HC"),
    "compendium": ("collected", "Compendium"),
    "gn": ("collected", "GN"),
    "ogn": ("collected", "GN"),
}
# Only recognised inside a tag, because they also start real series names
# ("Absolute Corvid", "Deluxe ...", "Special Forces").
_TAG_ONLY_FORMATS: dict[str, tuple[Format, str | None]] = {
    "absolute": ("collected", "Absolute"),
    "absolute edition": ("collected", "Absolute"),
    "deluxe": ("collected", "Deluxe"),
    "deluxe edition": ("collected", "Deluxe"),
    "graphic novel": ("collected", "GN"),
    "trade paperback": ("collected", "TPB"),
    "one shot": ("one_shot", None),
    "special": ("special", None),
    "annual": ("annual", None),
}
_LANGUAGES = {
    "en": "en",
    "eng": "en",
    "english": "en",
    "sv": "sv",
    "swe": "sv",
    "swedish": "sv",
    "svenska": "sv",
    "fr": "fr",
    "fre": "fr",
    "french": "fr",
    "de": "de",
    "ger": "de",
    "german": "de",
    "es": "es",
    "spa": "es",
    "spanish": "es",
    "it": "it",
    "ita": "it",
    "italian": "it",
    "ja": "ja",
    "jp": "ja",
    "jpn": "ja",
    "japanese": "ja",
    "raw": "ja",
    "ko": "ko",
    "kor": "ko",
    "korean": "ko",
    "zh": "zh",
    "chi": "zh",
    "chinese": "zh",
    "pt-br": "pt",
    "pt": "pt",
    "portuguese": "pt",
    "ru": "ru",
    "rus": "ru",
    "russian": "ru",
}
_SEPARATORS = {"-", "–", "—", ":", "~", "|"}
# "(The Expanse #1)", "(The Expanse, Book 1)" on e-books.
_BOOK_SERIES_TAG = re.compile(
    r"^(.+?)(?:,\s*|\s+)(?:#|book\s+|bok\s+|vol\.?\s*|no\.?\s*)(\d+(?:\.\d+)?)$", re.IGNORECASE
)
# Edition phrases written out at the end of the series part.
_EDITION_PHRASES = {
    "deluxe edition": "Deluxe",
    "absolute edition": "Absolute",
    "library edition": "Library",
    "omnibus edition": "Omnibus",
    "collector's edition": "Collector's",
}


@dataclass(frozen=True)
class ParsedName:
    series: str = ""
    title: str | None = None
    volume: str | None = None
    volume_end: str | None = None
    issue: str | None = None
    issue_count: int | None = None
    chapter: str | None = None
    chapter_end: str | None = None
    year: int | None = None
    series_year: int | None = None
    format: Format = "issue"
    edition: str | None = None
    scan_group: str | None = None
    language: str | None = None
    extra_tags: tuple[str, ...] = ()
    ambiguous: bool = False
    notes: tuple[str, ...] = field(default=(), compare=False)


def normalize_number(raw: str) -> str:
    """``"001"`` → ``"1"``, ``"13½"`` → ``"13.5"``, ``"153b"`` → ``"153.5"``,
    ``"-001"`` → ``"-1"``; ``"1.MU"`` stays as it is."""
    text = raw.strip().lstrip("#")
    if _SUFFIXED_ISSUE_RE.match(text):
        whole, suffix = text.split(".")
        return f"{int(whole)}.{suffix}"
    for glyph, decimal in _FRACTIONS.items():
        if text.endswith(glyph):
            whole = text[: -len(glyph)] or "0"
            text = whole + decimal
    negative = text.startswith("-")
    text = text.lstrip("-")
    letter = ""
    if text and text[-1].isalpha():
        text, letter = text[:-1], text[-1].lower()
    if "." in text:
        whole, _, decimals = text.partition(".")
        text = f"{int(whole or 0)}.{decimals}"
    elif text:
        text = str(int(text))
    if letter == "b":
        text = f"{text}.5"
    elif letter:
        text = f"{text}{letter}"
    return f"-{text}" if negative and text != "0" else text


def _is_year(text: str) -> bool:
    return text.isdigit() and len(text) == 4 and _YEAR_MIN <= int(text) <= _YEAR_MAX


def _strip_extension(name: str) -> str:
    stem, dot, ext = name.rpartition(".")
    if dot and ext.lower() in _EXTENSIONS:
        return stem
    return name


# A download site's name left in a file name ("Batman 001 GetComics.INFO").
_SITE = re.compile(r"(?<![\w.])[\w-]+\.(?:info|com|net|org|to|cc|ws)(?![\w.])", re.IGNORECASE)


def _prepare(name: str) -> str:
    text = unicodedata.normalize("NFC", _strip_extension(name.strip()))
    # Control characters never belong in a name (and \x00 marks tags below).
    text = "".join(" " if unicodedata.category(char) == "Cc" else char for char in text)
    text = _SITE.sub(" ", text)
    for cut in ("--", "__"):
        index = text.find(cut)
        if index > 0:
            text = text[:index]
    if " " not in text and "_" in text:
        text = text.replace("_", " ")
    elif " " not in text and "." in text:
        # Scene names with dots for spaces; a one-digit decimal ("2.0",
        # "13.5") keeps its dot, "v2.012" does not.
        text = re.sub(r"\.(?!(?<=\d\.)\d(?!\d))", " ", text)
    text = text.replace("_", " ")
    return re.sub(r"\s+", " ", text).strip()


_BRACKETS = {"(": ")", "[": "]", "{": "}"}
_TAG_TOKEN = "\x00{}\x00"


def _lift_tags(text: str) -> tuple[str, list[str]]:
    """Replaces bracketed tags with placeholders and returns them in order.
    Brackets glued to words on both sides are kept as text."""
    tags: list[str] = []
    out: list[str] = []
    i = 0
    while i < len(text):
        char = text[i]
        close = _BRACKETS.get(char)
        if close is None:
            out.append(char)
            i += 1
            continue
        end = text.find(close, i + 1)
        if end == -1:
            out.append(char)
            i += 1
            continue
        before = text[i - 1] if i > 0 else " "
        after = text[end + 1] if end + 1 < len(text) else " "
        glued = not before.isspace() and before not in ")]}" and not after.isspace() and after not in "([{"
        if glued:
            out.append(text[i : end + 1])
        else:
            out.append(f" {_TAG_TOKEN.format(len(tags))} ")
            tags.append(text[i + 1 : end].strip())
        i = end + 1
    return re.sub(r"\s+", " ", "".join(out)).strip(), tags


@dataclass
class _State:
    kind: Kind | None
    volume: str | None = None
    volume_end: str | None = None
    issue: str | None = None
    issue_count: int | None = None
    chapter: str | None = None
    chapter_end: str | None = None
    year: int | None = None
    series_year: int | None = None
    format: Format | None = None
    edition: str | None = None
    scan_group: str | None = None
    language: str | None = None
    extra_tags: list[str] = field(default_factory=list)
    ambiguous: bool = False
    notes: list[str] = field(default_factory=list)
    book_series: str | None = None
    year_from_tag: bool = False

    def set_format(self, fmt: Format, edition: str | None = None) -> None:
        if self.format in (None, "issue") or (self.format == "collected" and fmt == "collected"):
            self.format = fmt
        if edition and not self.edition:
            self.edition = edition

    def set_volume(self, value: str, end: str | None = None) -> None:
        if self.volume is None:
            self.volume, self.volume_end = normalize_number(value), normalize_number(end) if end else None
        else:
            self.notes.append(f"second volume marker {value} ignored")

    def set_chapter(self, value: str, end: str | None = None) -> None:
        if self.chapter is None:
            self.chapter, self.chapter_end = normalize_number(value), normalize_number(end) if end else None
        else:
            self.notes.append(f"second chapter marker {value} ignored")


def _classify_tag(tag: str, index: int, state: _State, *, after_number: bool) -> None:
    lowered = tag.lower().strip()
    if not lowered:
        return
    year_match = re.fullmatch(r"(?:\w+\.? )?(\d{4})(?:[-–/]\d{2,4})?", lowered)
    if year_match and _is_year(year_match.group(1)):
        year = int(year_match.group(1))
        state.year_from_tag = True
        if after_number or state.series_year is not None or state.kind == "book":
            state.year = state.year or year
        else:
            state.series_year = year
        return
    of_match = re.fullmatch(r"of (\d+)", lowered)
    if of_match:
        state.issue_count = int(of_match.group(1))
        return
    volume_match = _VOLUME_GLUED.fullmatch(lowered.replace(" ", "")) or re.fullmatch(r"vol\.? (\d+)", lowered)
    if volume_match and lowered[0] in "vt":
        state.set_volume(volume_match.group(1))
        return
    if lowered in _TAG_ONLY_FORMATS:
        state.set_format(*_TAG_ONLY_FORMATS[lowered])
        return
    if lowered in _FORMAT_WORDS:
        state.set_format(*_FORMAT_WORDS[lowered])
        return
    if lowered in _LANGUAGES:
        state.language = _LANGUAGES[lowered]
        return
    if state.kind == "book" and (book_match := _BOOK_SERIES_TAG.match(tag)):
        state.book_series = book_match.group(1).strip()
        state.issue = state.issue or normalize_number(book_match.group(2))
        return
    if index == 0 and state.scan_group is None and not after_number:
        state.scan_group = tag
        return
    state.extra_tags.append(tag)


def _tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in text.split(" "):
        if not raw:
            continue
        # "#12" stays one token; "Ch.12" and "Vol.3" split into marker and number.
        split = re.fullmatch(r"(vol\.|ch\.|chp\.|ep\.)(\d.*)", raw, re.IGNORECASE)
        if split:
            tokens.extend(split.groups())
        elif raw == "#":
            tokens.append(raw)
        else:
            tokens.append(raw)
    # "# 12" -> "#12"
    merged: list[str] = []
    for token in tokens:
        if merged and merged[-1] == "#" and _NUMBER_RE.match(token):
            merged[-1] = "#" + token
        else:
            merged.append(token)
    return merged


def _is_number(token: str) -> bool:
    return bool(_NUMBER_RE.match(token) or _SUFFIXED_ISSUE_RE.match(token))


def parse_filename(name: str, *, kind: Kind | None = None, series_hint: str | None = None) -> ParsedName:
    """Parses one file or folder name. ``kind`` says how a bare number is
    read (an issue for comics, a chapter for manga)."""
    state = _State(kind=kind)
    text, tags = _lift_tags(_prepare(name))

    hint_words: list[str] = []
    if series_hint:
        hint_text, _ = _lift_tags(_prepare(series_hint))
        hint_words = [t for t in _tokens(hint_text) if not t.startswith("\x00")]

    tokens = _tokens(text)
    # Leading "[Group]" before anything else is the scan group.
    if tokens and tokens[0] == _TAG_TOKEN.format(0) and tags and not re.fullmatch(r"\d{4}", tags[0]):
        state.scan_group = tags[0]
        tokens = tokens[1:]
        tags_consumed = {0}
    else:
        tags_consumed = set()

    roles: list[str | None] = [None] * len(tokens)  # "series" | "title" | a marker role
    protected = 0
    if hint_words and [t.casefold() for t in tokens[: len(hint_words)]] == [w.casefold() for w in hint_words]:
        protected = len(hint_words)

    i = protected
    while i < len(tokens):
        token = tokens[i]
        lower = token.lower()
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if token.startswith("\x00"):
            roles[i] = "tag"
        elif match := _HASH.match(token):
            if state.issue is None:
                state.issue = normalize_number(match.group(1))
                roles[i] = "issue"
            else:
                roles[i] = "dropped"
                state.notes.append(f"second issue marker {token} ignored")
        elif match := _VOLUME_GLUED_RANGE.match(token):
            state.set_volume(match.group(1), match.group(2))
            roles[i] = "volume"
        elif (
            (match := _VOLUME_GLUED.match(token))
            and (lower[0] != "s" or state.kind == "manga")
            and (lower[0] != "t" or len(lower) <= 4 or lower.startswith("tome"))
        ):
            state.set_volume(match.group(1))
            roles[i] = "volume"
        elif lower in _VOLUME_WORDS and nxt is not None and (_is_number(nxt) or _RANGE_RE.match(nxt)) and i > 0:
            if lower == "book" and state.kind == "comic":
                # A prestige mini's 48-page "Book 1" is an issue, a 300-page "Book 1" a
                # collected volume: the page count decides at scan time
                # (group.collected_by_size). "Book" isn't part of the name.
                roles[i] = "dropped"
                state.notes.append("numbered as a book")
            else:
                if range_match := _RANGE_RE.match(nxt):
                    state.set_volume(range_match.group(1), range_match.group(2))
                else:
                    state.set_volume(nxt)
                roles[i] = roles[i + 1] = "volume"
                i += 1
        elif match := _CHAPTER_GLUED.match(token):
            state.set_chapter(match.group(1), match.group(2))
            roles[i] = "chapter"
        elif lower in _CHAPTER_WORDS and nxt is not None and (_is_number(nxt) or _RANGE_RE.match(nxt)) and i > 0:
            if range_match := _RANGE_RE.match(nxt):
                state.set_chapter(range_match.group(1), range_match.group(2))
            else:
                state.set_chapter(nxt)
            roles[i] = roles[i + 1] = "chapter"
            i += 1
        elif match := _CJK_VOLUME.match(token):
            state.set_volume(match.group(1) or match.group(2))
            roles[i] = "volume"
        elif match := _CJK_CHAPTER.match(token):
            state.set_chapter(match.group(1) or match.group(2))
            roles[i] = "chapter"
        elif match := _SPECIAL_CODE.match(token):
            state.set_format("special")
            state.issue = state.issue or normalize_number(match.group(1))
            roles[i] = "issue"
        elif lower in _FORMAT_WORDS and i > 0:
            state.set_format(*_FORMAT_WORDS[lower])
            roles[i] = "format"
        elif lower == "one" and nxt is not None and nxt.lower() == "shot" and i > 0:
            state.set_format("one_shot")
            roles[i] = roles[i + 1] = "format"
            i += 1
        elif lower == "of" and nxt is not None and nxt.isdigit() and i > 0 and _is_number(tokens[i - 1]):
            state.issue_count = int(nxt)
            roles[i] = roles[i + 1] = "count"
            i += 1
        i += 1

    _assign_bare_numbers(tokens, roles, protected, state)

    # Tags: years before the first number marker are the series year.
    first_number = next(
        (j for j, role in enumerate(roles) if role in ("issue", "volume", "chapter", "count", "format")), len(tokens)
    )
    for j, token in enumerate(tokens):
        if token.startswith("\x00"):
            index = int(token.strip("\x00"))
            if index in tags_consumed:
                continue
            _classify_tag(tags[index], index, state, after_number=j > first_number)

    series_tokens, title_tokens = _split_series_and_title(tokens, roles)
    series = _clean(" ".join(series_tokens))
    title = _clean(" ".join(title_tokens)) or None

    if not series and not title and roles and roles[protected] in ("issue", "year"):
        # The name is only a number ("52", "1984"): that is the name.
        series, state.issue = tokens[protected], None
        if roles[protected] == "year":
            state.year = None
        state.ambiguous = True
        state.notes.append("the name is only a number")

    lowered_series = series.casefold()
    for phrase, edition in _EDITION_PHRASES.items():
        if lowered_series.endswith(" " + phrase):
            series = _clean(series[: -len(phrase)])
            state.set_format("collected", edition)
            break

    if state.issue is None and state.volume is None and state.chapter is None and kind != "book":
        # A comic or manga with no number (a one-shot, a single collected
        # edition): the year in its tag is both its own and the series'.
        if state.year_from_tag:
            state.year = state.year or state.series_year
            state.series_year = state.series_year or state.year

    if kind == "book":
        if state.book_series:
            title, series = series or title, state.book_series
        elif state.issue is None:
            title, series = series, ""

    fmt = state.format
    if fmt is None or fmt == "issue":
        if state.chapter is not None:
            fmt = "chapter"
        elif kind == "manga":
            fmt = "volume"
        elif state.volume is not None and state.issue is None:
            fmt = "collected"
        elif kind == "book":
            fmt = "book"
        else:
            fmt = "issue"
    issue = state.issue
    if fmt == "one_shot" and issue is None:
        issue = "1"

    return ParsedName(
        series=series,
        title=title,
        volume=state.volume,
        volume_end=state.volume_end,
        issue=issue,
        issue_count=state.issue_count,
        chapter=state.chapter,
        chapter_end=state.chapter_end,
        year=state.year,
        series_year=state.series_year,
        format=fmt,
        edition=state.edition,
        scan_group=state.scan_group,
        language=state.language,
        extra_tags=tuple(state.extra_tags),
        ambiguous=state.ambiguous,
        notes=tuple(state.notes),
    )


def _assign_bare_numbers(tokens: list[str], roles: list[str | None], protected: int, state: _State) -> None:
    """Rules 3, 5 and 6 of the priority table: bare numbers that no marker
    claimed become the issue (or chapter), an annual's year, or stay part
    of the series name."""
    # Only numbers before a " - Title" part count; "Batman 001 - 2099 Unlimited"
    # keeps 2099 in the title.
    limit = len(tokens)
    for j in range(protected, len(tokens)):
        if tokens[j] in _SEPARATORS and any(roles[k] in ("issue", "chapter", "volume") for k in range(j)):
            limit = j
            break
        if tokens[j] in _SEPARATORS:
            # A bare number right before the separator ends the series part.
            if j > protected and _is_number(tokens[j - 1]) and roles[j - 1] is None:
                limit = j
                break
    # With a volume or chapter marker, numbers before it are part of the
    # series name ("Mob Psycho 100 v01", "Batman v2 012").
    first_marker = next((j for j in range(protected, limit) if roles[j] in ("volume", "chapter")), None)
    start = first_marker if first_marker is not None else protected
    candidates = [
        j for j in range(start, limit) if roles[j] is None and (_is_number(tokens[j]) or _RANGE_RE.match(tokens[j]))
    ]
    if not candidates:
        return

    # Annual/Special/FCBD: an adjacent year-like number is the year.
    for j in list(candidates):
        neighbours = {tokens[k].lower() for k in (j - 1, j + 1) if 0 <= k < len(tokens)}
        if _is_year(tokens[j]) and neighbours & {"annual", "special", "fcbd"}:
            state.year = int(tokens[j])
            roles[j] = "year"
            candidates.remove(j)

    # A number right after TPB/Omnibus/Compendium/HC is the volume.
    for j in list(candidates):
        previous = tokens[j - 1].lower() if j > 0 else ""
        if previous in _FORMAT_WORDS and _FORMAT_WORDS[previous][0] == "collected" and state.volume is None:
            state.set_volume(tokens[j])
            roles[j] = "volume"
            candidates.remove(j)

    # A number directly after "Annual"/"Special" is that annual's number.
    for j in list(candidates):
        if j > 0 and tokens[j - 1].lower() in ("annual", "special") and state.issue is None:
            state.issue = normalize_number(tokens[j])
            roles[j] = "issue"
            candidates.remove(j)

    already_numbered = state.issue is not None or state.chapter is not None
    if not candidates or (already_numbered and state.kind != "manga"):
        return

    # "Batman 012 2016": a trailing year-like number after another number
    # is the year.
    if len(candidates) >= 2 and _is_year(tokens[candidates[-1]]) and candidates[-2] == candidates[-1] - 1:
        state.year = state.year or int(tokens[candidates[-1]])
        roles[candidates[-1]] = "year"
        candidates.pop()
    # "Avengers 2018 001": the year-like number could be the series' year or
    # part of its name ("Blade Runner 2019"); it stays in the name, flagged.
    if len(candidates) >= 2 and _is_year(tokens[candidates[-2]]) and candidates[-2] == candidates[-1] - 1:
        state.ambiguous = True
        state.notes.append(f"{tokens[candidates[-2]]} could be the series' year or part of its name")

    last = candidates[-1]
    token = tokens[last]
    if last == protected and last == 0:
        # The whole name starts with this number ("100 Bullets", "52"):
        # only a number if nothing else follows.
        if any(roles[k] is None and not _is_number(tokens[k]) for k in range(last + 1, limit)):
            return
    if range_match := _RANGE_RE.match(token):
        if state.kind == "manga":
            state.set_chapter(range_match.group(1), range_match.group(2))
            roles[last] = "chapter"
        else:
            state.issue = normalize_number(range_match.group(1))
            roles[last] = "issue"
            state.ambiguous = True
            state.notes.append(f"issue range {token}: several issues in one file")
        return
    if _is_year(token) and len(candidates) == 1 and not already_numbered:
        state.year = int(token)
        state.ambiguous = True
        state.notes.append(f"{token} could be a year or an issue number")
        roles[last] = "year"
        return
    if state.kind == "manga":
        if state.chapter is None:
            state.set_chapter(token)
            roles[last] = "chapter"
        return
    if state.issue is None:
        state.issue = normalize_number(token)
        roles[last] = "issue"


def _split_series_and_title(tokens: list[str], roles: list[str | None]) -> tuple[list[str], list[str]]:
    """Series is the text before the first number/marker; the title is text
    after the numbers, normally behind a separator."""
    series: list[str] = []
    title: list[str] = []
    seen_marker = False
    for token, role in zip(tokens, roles, strict=True):
        if role == "tag" or token.startswith("\x00"):
            continue
        if role is not None:
            seen_marker = True
            continue
        (title if seen_marker else series).append(token)
    return series, title


def _clean(text: str) -> str:
    text = text.strip()
    while text and text[-1] in "-–—:~|,.":
        text = text[:-1].rstrip()
    while text and text[0] in "-–—:~|,":
        text = text[1:].lstrip()
    return text


_ISSUE_IN_FOLDER = re.compile(r"(?:^|\s)(?:#\s*\d|0\d+(?:\.\d+)?(?:\s|$))")


def parse_folder(name: str, *, kind: Kind | None = None) -> ParsedName:
    """A series folder (``Batman (2016)``, ``One Piece``): a number in it is
    part of the name (``Spider-Man 2099``), unless it is written like an
    issue (``#4``, ``004``), which marks a folder per issue."""
    parsed = parse_filename(name, kind=kind)
    if parsed.issue is None and parsed.chapter is None and parsed.volume is None:
        return parsed
    text, _tags = _lift_tags(_prepare(name))
    if _ISSUE_IN_FOLDER.search(text) or parsed.volume is not None:
        return parsed
    series = _clean(" ".join(t for t in _tokens(text) if not t.startswith("\x00")))
    return replace(parsed, series=series, issue=None, chapter=None, chapter_end=None, format="issue", ambiguous=False)

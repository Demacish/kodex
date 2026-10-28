"""Title normalisation for grouping and candidate comparison.

``norm_unicode`` keeps every script: Latin diacritics are folded (``é`` →
``e``, ``æ`` → ``ae``, ``ø`` → ``o``, ``ß`` → ``ss``) but CJK, Hangul and
Cyrillic text stays as it is, so ``ワンピース`` does not collapse to an empty
string the way v1's alphanumeric-only regex made it. ``norm_ascii`` is the
same title reduced to ASCII letters and digits, for comparing romanised
names; it is empty for a title with no Latin characters.

Steps: Unicode compatibility decomposition, Latin folding, casefold, ``&``
and ``+`` become ``and``, apostrophes are dropped (``Caliban's`` →
``calibans``), other punctuation becomes a space, leading articles are
dropped (English, Swedish, German, French, Spanish, Italian), as are the
stop words ComicTagger ignores (``of``, ``or``, ``is``, ``issue``) and a
trailing sort-form article (``Amazing Spider-Man, The``). Roman
numerals become numbers only as the last word or after ``vol``/``book``/
``part``, and a single letter never does at the end (``X-Men``,
``Malcolm X`` and ``V for Vendetta`` keep their letters).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_LATIN_SPECIAL = str.maketrans(
    {"æ": "ae", "Æ": "AE", "ø": "o", "Ø": "O", "ß": "ss", "œ": "oe", "Œ": "OE", "đ": "d", "Đ": "D", "ł": "l", "Ł": "L",
     "þ": "th", "Þ": "Th", "ð": "d", "Ð": "D", "ı": "i"}
)  # fmt: skip
_APOSTROPHES = "'’‘`´ʼ"
_ARTICLES = {
    "the",
    "a",
    "an",
    "le",
    "la",
    "les",
    "l",
    "der",
    "die",
    "das",
    "den",
    "det",
    "el",
    "los",
    "las",
    "il",
    "lo",
}
_STOP_WORDS = {"of", "or", "is", "issue"}
_ROMAN_CONTEXT = {"vol", "volume", "book", "part", "bok", "del"}
_ROMAN_RE = re.compile(r"^(?=[mdclxvi]+$)m{0,3}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$")
_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
_PUBLISHER_NOISE = {
    "inc",
    "comics",
    "comic",
    "publishing",
    "publications",
    "press",
    "entertainment",
    "ltd",
    "llc",
    "co",
}


@dataclass(frozen=True)
class NormalizedTitle:
    unicode: str
    ascii: str


def _is_latin(char: str) -> bool:
    return char.isascii() or "LATIN" in unicodedata.name(char, "")


def _fold(text: str) -> str:
    """Compatibility-decomposes, folds Latin diacritics and keeps the
    marks of every other script (Japanese dakuten, Cyrillic breves)."""
    decomposed = unicodedata.normalize("NFKD", text.translate(_LATIN_SPECIAL))
    out: list[str] = []
    for char in decomposed:
        if unicodedata.combining(char) and out and _is_latin(out[-1]):
            continue
        out.append(char)
    return unicodedata.normalize("NFC", "".join(out))


def _roman_to_int(numeral: str) -> int:
    total = 0
    for current, following in zip(numeral, numeral[1:] + " ", strict=True):
        value = _ROMAN_VALUES[current]
        total += -value if following != " " and _ROMAN_VALUES[following] > value else value
    return total


def _words(text: str) -> list[str]:
    text = _fold(text).casefold()
    for apostrophe in _APOSTROPHES:
        text = text.replace(apostrophe, "")
    text = re.sub(r"\s*[&+]\s*", " and ", text)
    # Anything that isn't a letter or digit in any script is a separator.
    text = "".join(char if char.isalnum() else " " for char in text)
    return text.split()


def _convert_numerals(words: list[str]) -> list[str]:
    out = list(words)
    for index, word in enumerate(words):
        if not _ROMAN_RE.match(word):
            continue
        after_context = index > 0 and words[index - 1] in _ROMAN_CONTEXT
        last_and_long = index == len(words) - 1 and len(word) >= 2 and index > 0
        if after_context or last_and_long:
            out[index] = str(_roman_to_int(word))
    return out


_TRAILING_ARTICLE = re.compile(r",\s*(the|a|an)\s*$", re.IGNORECASE)


def normalize_words(text: str) -> list[str]:
    # "Amazing Spider-Man, The" is a sort form of "The Amazing Spider-Man".
    words = _words(_TRAILING_ARTICLE.sub("", text))
    words = [w for w in words if w not in _STOP_WORDS] or words
    while len(words) > 1 and words[0] in _ARTICLES:
        words = words[1:]
    return _convert_numerals(words)


def normalize_title(text: str) -> NormalizedTitle:
    words = normalize_words(text)
    unicode_form = " ".join(words)
    ascii_form = " ".join(w for w in (re.sub(r"[^a-z0-9]", "", w) for w in words) if w)
    return NormalizedTitle(unicode=unicode_form, ascii=ascii_form)


def norm(text: str) -> str:
    """The Unicode-preserving normalised form, the usual comparison key."""
    return normalize_title(text).unicode


def normalize_publisher(text: str) -> str:
    """``DC Comics, Inc.`` → ``dc``: publisher names without the corporate
    words that differ between providers."""
    words = [w for w in _words(text) if w not in _PUBLISHER_NOISE]
    return " ".join(words)

"""kodex.matching.normalize: folding, articles, stop words, roman numerals,
and that non-Latin scripts survive."""

from __future__ import annotations

import string

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kodex.matching.normalize import norm, normalize_publisher, normalize_title


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("The Amazing Spider-Man", "amazing spider man"),
        ("Amazing Spider-Man, The", "amazing spider man"),
        ("Batman & Robin", "batman and robin"),
        ("Batman and Robin", "batman and robin"),
        ("Wicked + The Divine", "wicked and the divine"),
        ("Caliban's War", "calibans war"),
        ("X-Men '92", "x men 92"),
        ("Pokémon Adventures", "pokemon adventures"),
        ("Æon Flux", "aeon flux"),
        ("Søren", "soren"),
        ("Straße", "strasse"),
        ("Fullmetal Alchemist: Brotherhood", "fullmetal alchemist brotherhood"),
        ("Tales of the Unexpected", "tales the unexpected"),
        ("Of Mice and Men", "mice and men"),
        ("Kill or Be Killed", "kill be killed"),
        ("Rocky II", "rocky 2"),
        ("Final Fantasy XV", "final fantasy 15"),
        ("Saga Vol. IV", "saga vol 4"),
        ("Part I", "part 1"),
        ("X-Men", "x men"),
        ("Malcolm X", "malcolm x"),
        ("V for Vendetta", "v for vendetta"),
        ("Civil War II", "civil war 2"),
        ("Mix", "mix"),
        ("Den svarta pilen", "svarta pilen"),
        ("Die Verwandlung", "verwandlung"),
        ("Le Petit Prince", "petit prince"),
        ("The", "the"),
        ("ＡＢＣ", "abc"),
        ("SPY×FAMILY", "spy family"),
        ("ワンピース", "ワンピース"),
        ("進撃の巨人", "進撃の巨人"),
        ("나 혼자만 레벨업", "나 혼자만 레벨업"),
        ("Берсерк", "берсерк"),
        ("Йотунхейм", "йотунхейм"),
        ("ガンダム", "ガンダム"),
    ],
)
def test_norm(raw, expected):
    assert norm(raw) == expected


def test_ascii_form_drops_non_latin_scripts():
    assert normalize_title("ワンピース").ascii == ""
    assert normalize_title("Pokémon: ポケモン").ascii == "pokemon"
    assert normalize_title("Æon Flux").ascii == "aeon flux"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("DC Comics", "dc"),
        ("DC Comics, Inc.", "dc"),
        ("Marvel", "marvel"),
        ("Image Comics", "image"),
        ("Viz Media", "viz media"),
    ],
)
def test_normalize_publisher(raw, expected):
    assert normalize_publisher(raw) == expected


@given(st.text())
def test_norm_never_raises_and_is_idempotent(text):
    once = norm(text)
    assert norm(once) == once


@given(st.text(alphabet=string.ascii_letters + string.digits + " -'.,:&!?", min_size=1))
def test_case_and_punctuation_do_not_matter(text):
    assert norm(text.upper()) == norm(text.lower())
    assert norm(text.replace("-", " ").replace(":", " ")) == norm(text)

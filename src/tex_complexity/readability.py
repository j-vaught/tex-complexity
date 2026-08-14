"""Deterministic English syllable and readability calculations."""

from __future__ import annotations

import re
from functools import lru_cache

import cmudict
import pyphen

_NON_LETTERS = re.compile(r"[^a-z]")
_VOWEL_GROUPS = re.compile(r"[aeiouy]+")
_HYPHENATOR = pyphen.Pyphen(lang="en_US")


@lru_cache(maxsize=1)
def _pronunciations() -> dict[str, list[list[str]]]:
    return cmudict.dict()


@lru_cache(maxsize=16_384)
def syllable_count(word: str) -> int:
    """Estimate the syllables in one English word without network access."""
    normalized = _NON_LETTERS.sub("", word.lower())
    if not normalized:
        return 0

    pronunciations = _pronunciations().get(normalized)
    if pronunciations:
        return sum(phoneme[-1:].isdigit() for phoneme in pronunciations[0])

    hyphenated = _HYPHENATOR.inserted(normalized)
    if "-" in hyphenated:
        return len(hyphenated.split("-"))

    count = len(_VOWEL_GROUPS.findall(normalized))
    if normalized.endswith("e") and not normalized.endswith(("le", "ye")) and count > 1:
        count -= 1
    return max(1, count)


def flesch_reading_ease(words: int, sentences: int, syllables: int) -> float:
    """Calculate Flesch reading ease from aggregate counts."""
    return 206.835 - 1.015 * words / sentences - 84.6 * syllables / words


def flesch_kincaid_grade(words: int, sentences: int, syllables: int) -> float:
    """Calculate the Flesch-Kincaid grade level from aggregate counts."""
    return 0.39 * words / sentences + 11.8 * syllables / words - 15.59


def gunning_fog(words: int, sentences: int, complex_words: int) -> float:
    """Calculate the Gunning fog index from aggregate counts."""
    return 0.4 * (words / sentences + 100 * complex_words / words)

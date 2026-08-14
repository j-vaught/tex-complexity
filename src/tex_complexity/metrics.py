"""Per-sentence metric definitions shared by the report and the highlighter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class SentenceStats:
    text: str
    n_words: int
    n_syllables: int
    n_polysyllables: int
    n_rare_words: int
    n_complex_words: int
    max_subj_verb_dist: int
    has_subject_verb_pair: bool
    n_subordinate_clauses: int
    tree_depth: int
    referential_score: int
    referential_hits: list[str] = field(default_factory=list)
    seg: int = 0  # index into the document's section list
    # (token text incl. trailing space, per-word complexity 0..1) for the
    # word-metric view, which highlights words rather than sentences.
    word_scores: list[tuple[str, float]] = field(default_factory=list)


def _word_complexity(s: SentenceStats) -> float:
    return s.n_complex_words / max(s.n_words, 1)


def _nesting(s: SentenceStats) -> float:
    return s.n_subordinate_clauses + max(0, s.tree_depth - 4) / 2


# key -> (title, description, score fn, green value, red value, format spec)
METRICS: dict[str, tuple[str, str, Callable[[SentenceStats], float], float, float, str]] = {
    "sentence": (
        "Sentence length",
        "Words per sentence. White at 10 words, garnet at 40.",
        lambda s: float(s.n_words),
        10,
        40,
        ".0f",
    ),
    "word": (
        "Word complexity",
        "Share of words that are polysyllabic (3+ syllables) or rare (Zipf < 3.5).",
        _word_complexity,
        0.10,
        0.50,
        ".2f",
    ),
    "svgap": (
        "Subject-verb separation",
        "Widest gap in words between a subject and its governing verb.",
        lambda s: float(s.max_subj_verb_dist),
        0,
        15,
        ".0f",
    ),
    "nesting": (
        "Nesting",
        "Subordinate clauses plus half a point per parse-tree level beyond 4.",
        _nesting,
        0,
        5,
        ".1f",
    ),
    "referential": (
        "Referential load",
        "Backward references the reader must resolve: vague definite phrases, "
        "bare demonstratives, pronouns or mentions whose antecedent is sentences away.",
        lambda s: float(s.referential_score),
        0,
        4,
        ".0f",
    ),
}

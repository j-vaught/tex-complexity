from __future__ import annotations

import pytest
from spacy.language import Language

from tex_complexity.cli import analyze_sentence, report
from tex_complexity.metrics import METRICS, SentenceStats
from tex_complexity.readability import (
    flesch_kincaid_grade,
    flesch_reading_ease,
    gunning_fog,
    syllable_count,
)


def make_stats(
    *,
    n_words: int = 7,
    n_syllables: int = 15,
    n_polysyllables: int = 3,
    n_rare_words: int = 2,
    n_complex_words: int = 4,
) -> SentenceStats:
    return SentenceStats(
        text="A representative sentence contains several technical expressions.",
        n_words=n_words,
        n_syllables=n_syllables,
        n_polysyllables=n_polysyllables,
        n_rare_words=n_rare_words,
        n_complex_words=n_complex_words,
        max_subj_verb_dist=2,
        n_subordinate_clauses=1,
        tree_depth=4,
        referential_score=0,
    )


def test_word_complexity_uses_union_and_never_double_counts() -> None:
    stats = make_stats(n_words=4, n_polysyllables=2, n_rare_words=2, n_complex_words=3)
    score = METRICS["word"][2](stats)

    assert score == pytest.approx(0.75)
    assert score <= 1


def test_readability_formulas_and_dictionary_are_deterministic() -> None:
    assert syllable_count("complexity") == 4
    assert syllable_count("strengths") == 1
    assert flesch_reading_ease(100, 5, 150) == pytest.approx(59.635)
    assert flesch_kincaid_grade(100, 5, 150) == pytest.approx(9.91)
    assert gunning_fog(100, 5, 20) == pytest.approx(16.0)


def test_demonstrative_with_modifiers_is_not_bare(nlp: Language) -> None:
    sent = next(nlp("This carefully designed method works reliably.").sents)

    stats = analyze_sentence(sent)

    assert not any(hit.startswith("bare") for hit in stats.referential_hits)


def test_anaphoric_matching_uses_word_boundaries(nlp: Language) -> None:
    formerly = analyze_sentence(next(nlp("The formerly active method remains useful.").sents))
    such_analysis = analyze_sentence(next(nlp("Such analysis improves the final result.").sents))

    assert "the former" not in formerly.referential_hits
    assert not ({"such a", "such an"} <= set(such_analysis.referential_hits))


def test_all_third_person_pronouns_contribute(nlp: Language) -> None:
    stats = analyze_sentence(next(nlp("They said he thanked her because she helped them.").sents))

    assert "5 pronoun(s)" in stats.referential_hits


def test_subject_verb_gap_ignores_punctuation(nlp: Language) -> None:
    punctuated = analyze_sentence(
        next(nlp("The apparatus, after many extensive trials, performs reliably.").sents)
    )
    plain = analyze_sentence(
        next(nlp("The apparatus after many extensive trials performs reliably.").sents)
    )

    assert punctuated.max_subj_verb_dist == plain.max_subj_verb_dist == 4


def test_word_scores_cover_both_polysyllabic_and_rare_words(nlp: Language) -> None:
    stats = analyze_sentence(next(nlp("Information supports communication about quarks.").sents))
    scores = {token.strip(". "): score for token, score in stats.word_scores if token.strip(". ")}

    assert stats.n_complex_words == 3
    assert scores["Information"] > 0
    assert scores["communication"] > 0
    assert scores["quarks"] > 0


def test_report_contains_all_metric_families_and_ranked_words() -> None:
    output = report([make_stats()], top=1, show_all=True)

    assert "SENTENCE COMPLEXITY" in output
    assert "Most complex 1" in output
    assert "SUBJECT-VERB SEPARATION" in output
    assert "NESTING" in output
    assert "REFERENTIAL LOAD" in output
    assert "PER-SENTENCE TABLE" in output


def test_report_handles_no_eligible_sentences() -> None:
    assert report([make_stats(n_words=2)], top=1, show_all=False) == "No prose sentences found."

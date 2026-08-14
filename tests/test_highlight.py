from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tex_complexity.highlight import (
    RenderError,
    _color,
    _esc,
    _ink,
    _word_color,
    _word_run,
    render_metric_pdf,
)
from tex_complexity.metrics import SentenceStats


def sample_stats(
    text: str = "A short sentence demonstrates the highlighted output.",
) -> SentenceStats:
    return SentenceStats(
        text=text,
        n_words=7,
        n_syllables=12,
        n_polysyllables=2,
        n_rare_words=1,
        n_complex_words=3,
        max_subj_verb_dist=2,
        n_subordinate_clauses=0,
        tree_depth=3,
        referential_score=0,
        word_scores=[(f"{word} ", 0.4) for word in text.split()],
    )


@pytest.mark.parametrize(
    ("value", "color", "ink"),
    [
        (0.0, "#ffffff", "#000000"),
        (0.25, "#ececec", "#000000"),
        (0.5, "#fff2e3", "#000000"),
        (0.75, "#cc2e40", "#ffffff"),
        (1.0, "#73000a", "#ffffff"),
    ],
)
def test_palette_is_quantized_and_high_contrast(value: float, color: str, ink: str) -> None:
    assert _color(value) == color
    assert _ink(value) == ink


def test_typst_escaping_covers_line_markup() -> None:
    escaped = _esc("= heading / term - item + item")

    assert escaped == r"\= heading \/ term \- item \+ item"


def test_word_palette_has_three_distinct_levels() -> None:
    assert len({_word_color(0.3), _word_color(0.6), _word_color(1.0)}) == 3


def test_word_renderer_falls_back_to_sentence_text() -> None:
    stats = sample_stats("Fallback text remains visible.")
    stats.word_scores = []

    assert "Fallback text remains visible." in _word_run([stats])


@pytest.mark.skipif(shutil.which("typst") is None, reason="Typst is not installed")
@pytest.mark.parametrize("metric", ["sentence", "word"])
def test_render_metric_pdf_compiles_utf8_and_markup(tmp_path: Path, metric: str) -> None:
    output = tmp_path / f"highlight-{metric}.pdf"
    stats = [sample_stats("= Résumé / result - reliable + clear.")]

    render_metric_pdf(stats, [(0, "")], metric, "résumé.tex", output)

    assert output.read_bytes().startswith(b"%PDF-")


def test_render_metric_pdf_wraps_typst_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, "typst", stderr="bad markup")

    monkeypatch.setattr(subprocess, "run", fail)

    with pytest.raises(RenderError, match="bad markup"):
        render_metric_pdf(
            [sample_stats()],
            [(0, "")],
            "sentence",
            "sample.tex",
            tmp_path / "sample.pdf",
        )


def test_render_metric_pdf_rejects_invalid_section_index(tmp_path: Path) -> None:
    stats = sample_stats()
    stats.seg = 2

    with pytest.raises(RenderError, match="section index"):
        render_metric_pdf([stats], [(0, "")], "sentence", "sample.tex", tmp_path / "x.pdf")

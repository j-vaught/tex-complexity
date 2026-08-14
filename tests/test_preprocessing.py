from __future__ import annotations

from pathlib import Path

import pytest
from spacy.language import Language

from tex_complexity import cli


def test_strip_comments_preserves_escaped_percent_and_literal_content() -> None:
    source = (
        "Visible \\% value. % hidden \\input{secret}\n"
        "\\begin{verbatim}\n"
        "100% literal \\input{also-secret}\n"
        "\\end{verbatim} % trailing comment\n"
        "Still visible.\n"
    )

    cleaned = cli.strip_comments(source)

    assert "Visible \\% value." in cleaned
    assert "hidden" not in cleaned
    assert "100% literal" in cleaned
    assert "trailing comment" not in cleaned
    assert "Still visible." in cleaned


def test_remove_non_prose_environments_drops_bibliography_and_truncated_float() -> None:
    source = (
        "Opening prose.\n"
        "\\begin{thebibliography}{1} Reference title. \\end{thebibliography}\n"
        "Middle prose.\n"
        "\\begin{figure} Hidden caption and trailing material."
    )

    cleaned = cli.remove_non_prose_environments(source)

    assert "Opening prose." in cleaned
    assert "Middle prose." in cleaned
    assert "Reference title" not in cleaned
    assert "Hidden caption" not in cleaned


def test_literal_environment_commands_do_not_consume_later_prose() -> None:
    source = r"""
    Before sentence.
    \begin{verbatim}
    \begin{figure}
    \end{verbatim}
    \begin{figure}
    Real figure content.
    \end{figure}
    After sentence.
    """

    cleaned = cli.remove_non_prose_environments(cli.strip_comments(source))

    assert "Before sentence." in cleaned
    assert "After sentence." in cleaned
    assert "Real figure content." not in cleaned
    assert "\\begin{figure}" not in cleaned


def test_inline_verbatim_commands_are_not_interpreted(tmp_path: Path, nlp: Language) -> None:
    tex = tmp_path / "inline-verbatim.tex"
    tex.write_text(
        r"""
        \begin{document}
        \section{Examples}
        The first complete sentence remains available for analysis.
        Inline examples \verb|95% \input{missing}| and
        \verb*+\end{document}+ are treated as literal code.
        The final complete sentence remains visible after every example.
        \end{document}
        """,
        encoding="utf-8",
    )

    text, stats, _ = cli.analyze_file(tex, nlp)

    assert "final complete sentence" in text
    assert "input{missing}" not in text
    assert len([stat for stat in stats if stat.n_words >= 3]) == 3


def test_inline_inputs_use_main_document_root(tmp_path: Path) -> None:
    chapter_dir = tmp_path / "chapters"
    chapter_dir.mkdir()
    (chapter_dir / "one.tex").write_text("Chapter opening. \\input{shared}", encoding="utf-8")
    (chapter_dir / "shared.tex").write_text("Wrong nested file.", encoding="utf-8")
    (tmp_path / "shared.tex").write_text("Correct root file.", encoding="utf-8")

    expanded = cli.inline_inputs(r"\input{chapters/one}", tmp_path)

    assert "Chapter opening." in expanded
    assert "Correct root file." in expanded
    assert "Wrong nested file." not in expanded


def test_inline_inputs_reject_missing_cycle_and_outside_paths(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "cycle.tex").write_text(r"\input{cycle}", encoding="utf-8")
    outside = tmp_path / "outside.tex"
    outside.write_text("Outside prose.", encoding="utf-8")

    with pytest.raises(cli.IncludeError, match="not found"):
        cli.inline_inputs(r"\input{missing}", project)
    with pytest.raises(cli.IncludeError, match="cyclic"):
        cli.inline_inputs(r"\input{cycle}", project)
    with pytest.raises(cli.UnsafeIncludeError, match="escapes"):
        cli.inline_inputs(r"\input{../outside}", project)

    assert "Outside prose." in cli.inline_inputs(r"\input{../outside}", project, allow_outside=True)


def test_load_aux_follows_child_files_without_leaving_root(tmp_path: Path) -> None:
    (tmp_path / "main.aux").write_text(
        r"\bibcite{main}{2}\newlabel{sec:main}{{I}{1}}\@input{chapter.aux}",
        encoding="utf-8",
    )
    (tmp_path / "chapter.aux").write_text(
        r"\bibcite{child}{7}\newlabel{sec:child}{{II}{2}}", encoding="utf-8"
    )

    cites, labels = cli.load_aux(tmp_path / "main.aux")

    assert cites == {"main": 2, "child": 7}
    assert labels == {"sec:main": "I", "sec:child": "II"}


def test_resolve_refs_avoids_sparse_collisions_and_accepts_two_notes() -> None:
    source = r"\citep[see][p. 4]{known,unknown}; Eq. \eqref{eq:a}."

    resolved = cli.resolve_refs(source, {"known": 2}, {"eq:a": "4"})

    assert resolved == "[2, 3]; Eq. (4)."


def test_section_numbering_extends_past_twelve_and_twenty_six() -> None:
    sections = "".join(rf"\section{{Section {index}}}" for index in range(1, 14))
    subsections = "".join(rf"\subsection{{Part {index}}}" for index in range(1, 28))

    section_segments = cli.split_sections(sections)
    subsection_segments = cli.split_sections(r"\section{Root}" + subsections)

    assert section_segments[-1][1] == "XIII. Section 13"
    assert subsection_segments[-1][1] == "AA. Part 27"


def test_analyze_file_accepts_sectionless_tex(tmp_path: Path, nlp: Language) -> None:
    tex = tmp_path / "sectionless.tex"
    tex.write_text(
        r"""
        \documentclass{article}
        \begin{document}
        A complete sectionless document remains valid for analysis.
        Another full sentence confirms the prose is preserved.
        \end{document}
        """,
        encoding="utf-8",
    )

    text, stats, titles = cli.analyze_file(tex, nlp)

    assert "sectionless document" in text
    assert titles == [(0, "")]
    assert {stat.seg for stat in stats} == {0}


def test_analyze_file_removes_comments_and_non_prose(tmp_path: Path, nlp: Language) -> None:
    tex = tmp_path / "paper.tex"
    tex.write_text(
        """
        \\documentclass{article}
        \\begin{document}
        % \\end{document}
        \\section{Introduction}
        The tested method produces reliable measurements for each sample.
        \\begin{thebibliography}{1}
        \\bibitem{x} Hidden reference title and author names.
        \\end{thebibliography}
        \\end{document}
        """,
        encoding="utf-8",
    )

    text, stats, titles = cli.analyze_file(tex, nlp)

    assert "reliable measurements" in text
    assert "Hidden reference" not in text
    assert stats
    assert (1, "I. Introduction") in titles


def test_analyze_file_keeps_unpunctuated_sections_separate(tmp_path: Path, nlp: Language) -> None:
    tex = tmp_path / "sections.tex"
    tex.write_text(
        """
        \\begin{document}
        \\section{First}
        This section ends without punctuation
        \\section{Second}
        Another complete section starts with separate prose.
        \\end{document}
        """,
        encoding="utf-8",
    )

    _, stats, titles = cli.analyze_file(tex, nlp)

    assert titles == [(1, "I. First"), (1, "II. Second")]
    assert {stat.seg for stat in stats if stat.n_words} == {0, 1}
    assert all("separate prose" not in stat.text for stat in stats if stat.seg == 0)


def test_plain_text_percentages_are_not_treated_as_tex_comments(
    tmp_path: Path, nlp: Language
) -> None:
    source = tmp_path / "results.txt"
    source.write_text(
        "Accuracy reached 95% in the first experiment. Recall remained stable afterward.",
        encoding="utf-8",
    )

    text, stats, _ = cli.analyze_file(source, nlp)

    assert "95% in the first experiment" in text
    assert len([stat for stat in stats if stat.n_words >= 3]) == 2


def test_analyze_file_rejects_short_and_oversized_input(
    tmp_path: Path, nlp: Language, monkeypatch: pytest.MonkeyPatch
) -> None:
    short = tmp_path / "short.txt"
    short.write_text("Two words.", encoding="utf-8")
    with pytest.raises(cli.NoProseError, match="three words"):
        cli.analyze_file(short, nlp)

    long = tmp_path / "long.txt"
    long.write_text("Several valid words appear here.", encoding="utf-8")
    monkeypatch.setattr(cli, "MAX_DOCUMENT_CHARS", 10)
    with pytest.raises(cli.DocumentTooLargeError, match="limit"):
        cli.analyze_file(long, nlp)

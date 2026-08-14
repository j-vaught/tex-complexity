from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tex_complexity import cli


def run_cli(*arguments: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tex_complexity", *(str(argument) for argument in arguments)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_help_and_version_are_available() -> None:
    help_result = run_cli("--help")
    version_result = run_cli("--version")

    assert help_result.returncode == 0
    assert "usage: texstats" in help_result.stdout
    assert version_result.returncode == 0
    assert version_result.stdout.startswith("texstats 0.1.0")


def test_cli_analyzes_plain_text(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_text(
        "The compact instrument records each measurement. "
        "These results support the proposed method.",
        encoding="utf-8",
    )

    result = run_cli(source, "--top", 1, "--all")

    assert result.returncode == 0
    assert "SENTENCE COMPLEXITY" in result.stdout
    assert "PER-SENTENCE TABLE" in result.stdout
    assert result.stderr == ""


def test_cli_processes_valid_siblings_when_one_path_is_missing(tmp_path: Path) -> None:
    valid = tmp_path / "valid.txt"
    valid.write_text("Several valid words form a complete sentence.", encoding="utf-8")

    result = run_cli(tmp_path / "missing.txt", valid, "--top", 1)

    assert result.returncode == 1
    assert "SENTENCE COMPLEXITY" in result.stdout
    assert "input file not found" in result.stderr


def test_cli_rejects_invalid_top_and_short_input(tmp_path: Path) -> None:
    short = tmp_path / "short.txt"
    short.write_text("Two words.", encoding="utf-8")

    invalid_top = run_cli(short, "--top", 0)
    short_result = run_cli(short)

    assert invalid_top.returncode == 2
    assert "must be at least 1" in invalid_top.stderr
    assert short_result.returncode == 1
    assert "three words" in short_result.stderr


def test_cli_rejects_outside_include_by_default(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "outside.tex").write_text("Outside material appears here.", encoding="utf-8")
    main = project / "main.tex"
    main.write_text(r"\begin{document}\input{../outside}\end{document}", encoding="utf-8")

    result = run_cli(main)

    assert result.returncode == 1
    assert "include escapes the document directory" in result.stderr


def test_highlight_output_names_preserve_complete_input_filename(tmp_path: Path) -> None:
    text_output = cli._highlight_output_path(tmp_path / "collision.txt", "sentence")
    tex_output = cli._highlight_output_path(tmp_path / "collision_txt.tex", "sentence")

    assert text_output.name == "collision.txt_sentence.pdf"
    assert tex_output.name == "collision_txt.tex_sentence.pdf"
    assert text_output != tex_output


@pytest.mark.skipif(shutil.which("typst") is None, reason="Typst is not installed")
def test_cli_preflights_duplicate_highlight_outputs(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_text("Several valid words form a complete sentence.", encoding="utf-8")
    output = cli._highlight_output_path(source, "sentence")

    result = run_cli(source, source, "--highlight", "sentence", "--force")

    assert result.returncode == 1
    assert "multiple requested highlights target the same PDF" in result.stderr
    assert not output.exists()

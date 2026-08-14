from __future__ import annotations

import io
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import spacy
from spacy.language import Language

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
    assert version_result.stdout.startswith("texstats 0.1.1")


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
def test_cli_preflights_duplicate_highlight_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "sample.txt"
    source.write_text("Several valid words form a complete sentence.", encoding="utf-8")
    output = cli._highlight_output_path(source, "sentence")
    monkeypatch.setattr(
        sys,
        "argv",
        ["texstats", str(source), str(source), "--highlight", "sentence", "--force"],
    )

    with pytest.raises(SystemExit) as exit_info:
        cli._run()
    captured = capsys.readouterr()

    assert exit_info.value.code == 1
    assert "multiple requested highlights target the same PDF" in captured.err
    assert not output.exists()


@pytest.mark.skipif(shutil.which("typst") is None, reason="Typst is not installed")
def test_cli_never_overwrites_an_input_with_a_highlight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "manuscript.txt"
    source.write_text("Several valid words form a complete sentence.", encoding="utf-8")
    protected_input = cli._highlight_output_path(source, "sentence")
    original = b"Another valid input sentence must remain unchanged."
    protected_input.write_bytes(original)
    later_output = cli._highlight_output_path(protected_input, "sentence")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "texstats",
            str(source),
            str(protected_input),
            "--highlight",
            "sentence",
            "--force",
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        cli._run()
    captured = capsys.readouterr()

    assert exit_info.value.code == 1
    assert "highlighted PDF would overwrite requested input" in captured.err
    assert protected_input.read_bytes() == original
    assert not later_output.exists()


@pytest.mark.skipif(shutil.which("typst") is None, reason="Typst is not installed")
def test_cli_rejects_hard_linked_output_aliases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "manuscript.txt"
    source.write_text("Several valid words form a complete sentence.", encoding="utf-8")
    protected_input = tmp_path / "protected.txt"
    original = b"Another requested input sentence must remain unchanged."
    protected_input.write_bytes(original)
    output = cli._highlight_output_path(source, "sentence")
    output.hardlink_to(protected_input)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "texstats",
            str(source),
            str(protected_input),
            "--highlight",
            "sentence",
            "--force",
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        cli._run()
    captured = capsys.readouterr()

    assert exit_info.value.code == 1
    assert "highlighted PDF would overwrite requested input" in captured.err
    assert protected_input.read_bytes() == original
    assert output.read_bytes() == original


def test_cli_continues_after_input_inspection_error(
    tmp_path: Path,
    nlp: Language,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inaccessible = tmp_path / "inaccessible.txt"
    valid = tmp_path / "valid.txt"
    valid.write_text("Several valid words form a complete sentence.", encoding="utf-8")
    original_is_file = Path.is_file

    def guarded_is_file(path: Path) -> bool:
        if path == inaccessible:
            raise PermissionError("access denied")
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", guarded_is_file)
    monkeypatch.setattr(spacy, "load", lambda _: nlp)
    monkeypatch.setattr(sys, "argv", ["texstats", str(inaccessible), str(valid), "--top", "1"])

    with pytest.raises(SystemExit) as exit_info:
        cli._run()
    captured = capsys.readouterr()

    assert exit_info.value.code == 1
    assert "could not inspect input: access denied" in captured.err
    assert "SENTENCE COMPLEXITY" in captured.out


@pytest.mark.skipif(shutil.which("typst") is None, reason="Typst is not installed")
def test_cli_finishes_batch_work_after_stdout_closes(
    tmp_path: Path,
    nlp: Language,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenStdout:
        closed = False

        def write(self, value: str) -> int:
            return len(value)

        def flush(self) -> None:
            raise BrokenPipeError

        def close(self) -> None:
            self.closed = True

    missing = tmp_path / "missing.txt"
    valid = tmp_path / "valid.txt"
    valid.write_text("Several valid words form a complete sentence.", encoding="utf-8")
    output = cli._highlight_output_path(valid, "sentence")
    broken_stdout = BrokenStdout()
    stderr = io.StringIO()
    monkeypatch.setattr(spacy, "load", lambda _: nlp)
    monkeypatch.setattr(sys, "stdout", broken_stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setattr(
        sys,
        "argv",
        ["texstats", str(missing), str(valid), "--highlight", "sentence"],
    )

    with pytest.raises(SystemExit) as exit_info:
        cli._run()

    assert exit_info.value.code == 1
    assert broken_stdout.closed
    assert "input file not found" in stderr.getvalue()
    assert output.read_bytes().startswith(b"%PDF-")

# tex-complexity

[![CI](https://github.com/j-vaught/tex-complexity/actions/workflows/ci.yml/badge.svg)](https://github.com/j-vaught/tex-complexity/actions/workflows/ci.yml)
[![Python 3.11–3.12](https://img.shields.io/badge/python-3.11–3.12-466A9F)](https://www.python.org/)
[![MIT License](https://img.shields.io/badge/license-MIT-73000A)](LICENSE)

`texstats` finds prose in English-language LaTeX documents and reports concrete places where the writing may be difficult to read. It measures sentence length, word complexity, subject–verb separation, syntactic nesting, and references that make readers search backward for context. Optional highlighted PDFs make the most complex passages visible without modifying the source document.

The tool is a revision aid, not a universal score of writing quality. Its thresholds are prompts for editorial judgment, and its parser is tuned for English technical prose.

## Quick start

The supported runtime is Python 3.11 or 3.12. The recommended installer is [uv](https://docs.astral.sh/uv/). A one-off analysis from the tagged GitHub release uses the following command.

```shell
uvx --from "tex-complexity @ git+https://github.com/j-vaught/tex-complexity.git@v0.1.0" \
  texstats paper.tex
```

A persistent installation uses the same release.

```shell
uv tool install "tex-complexity @ git+https://github.com/j-vaught/tex-complexity.git@v0.1.0"
texstats paper.tex
```

The first installation downloads the pinned spaCy English model. Normal analysis is local and does not make network requests.

To try the repository example from a source checkout, run the following commands.

```shell
git clone https://github.com/j-vaught/tex-complexity.git
cd tex-complexity
uv sync --locked
uv run texstats examples/sample.tex --top 3
```

The terminal report begins with aggregate measures and then names the worst sentences in each category. An abbreviated run contains sections like these.

```text
SENTENCE COMPLEXITY
  Sentences                                     ...
  Mean length (words)                          ...

WORD COMPLEXITY
  Polysyllabic (3+ syl)                        ...
  Rare words (zipf < 3.5)                      ...

SUBJECT-VERB SEPARATION
NESTING (SUBORDINATE CLAUSES / PARSE DEPTH)
REFERENTIAL LOAD (BACKWARD REFERENCES)
```

## Metrics

The report uses five metric families. A sentence must contain at least three alphabetic words to enter the aggregate report.

| Family | What is measured | Interpretation |
| --- | --- | --- |
| Sentence complexity | Length distribution, the share over 30 words, Flesch reading ease, Flesch-Kincaid grade, and Gunning fog. | Long sentences and consistently high grades deserve review, especially when several signals agree. |
| Word complexity | Polysyllabic words, rare words, their union, and average syllables per word. | A word is rare below Zipf 3.5, approximately less frequent than once per 316,000 words in a reference corpus. |
| Subject–verb separation | The largest number of alphabetic words between a grammatical subject and its governing verb. | Wide gaps can increase working-memory load. Punctuation does not inflate the count. |
| Nesting | Subordinate-clause count and dependency-tree depth. | Several clauses or a deep parse can indicate embedded structure that is worth simplifying. |
| Referential load | Bare demonstratives, anaphoric phrases, third-person pronouns, vague definite noun phrases, and distant shell-noun referents. | A high score marks places where a reader may need to recover an earlier referent. It is a surface heuristic, not full coreference resolution. |

The parser treats a shell noun such as “method,” “metric,” or “result” as anchored when its noun phrase names something concrete. “The accuracy of BERT” is anchored. “The main target metric of this paper” is flagged because the phrase does not identify the metric. Naming constructions such as “we define tracking error as the evaluation criterion” are treated as introductions rather than backward references.

## Command reference

Multiple input files can be supplied in one invocation. A bad file is reported without preventing valid siblings from being analyzed, and the command returns a nonzero status if any input fails.

| Argument | Behavior |
| --- | --- |
| `files` | Analyze one or more `.tex` or plain-text files. |
| `--top N` | Show the top $N$ sentences in each ranked category. The default is five. |
| `--all` | Append a compact table for every eligible sentence. |
| `--highlight METRIC` | Write a highlighted PDF for `sentence`, `word`, `svgap`, `nesting`, `referential`, or `all`. |
| `--allow-outside-includes` | Permit `\input` and `\include` to read outside the main document directory. |
| `--force` | Replace an existing highlighted PDF. Existing files are protected by default. |
| `--version` | Print the installed version. |

The following examples cover common review tasks.

```shell
texstats paper.tex --top 10
texstats paper.tex --all
texstats introduction.tex methods.tex results.tex
```

## Highlighted PDFs

PDF rendering requires [Typst](https://typst.app/open-source/) 0.15 or newer on `PATH`. Sentence-based views use a high-contrast white, neutral, Sandstorm, Rose, and Garnet scale. The `word` view instead highlights individual words that are polysyllabic or rare, with stronger color for greater syllable count or rarity.

```shell
texstats paper.tex --highlight referential
texstats paper.tex --highlight all
```

A TeX input named `paper.tex` produces files such as `paper.tex_referential.pdf`. A plain-text input named `paper.txt` produces `paper.txt_referential.pdf`. Keeping the complete source filename prevents different input types from targeting the same output. Every destination is checked before analysis begins, and `--force` permits replacement only when each requested output remains unique. Re-run with `--force` when replacement is intentional.

## LaTeX handling

The analyzer expands literal `\input{...}` and `\include{...}` commands relative to the main document directory. Nested paths follow standard main-root TeX behavior. Missing files, cycles, and more than 20 include levels produce clear errors. Includes that resolve outside the document directory are blocked unless `--allow-outside-includes` is present.

Comments are removed before includes are expanded. Math, floats, tables, algorithms, listings, inline `\verb` spans, verbatim blocks, TikZ pictures, bibliographies, and the preamble are excluded from prose. When a sibling `.aux` file exists, citation numbers and cross-reference labels are recovered from it and its `\@input` children. Unresolved citations receive stable fallback numbers, and unresolved references appear as `?`.

The preprocessing layer intentionally supports common LaTeX forms rather than executing TeX. Macro-generated filenames, conditional includes, and custom environments may need a simplified analysis copy.

## Privacy and input trust

Analysis and PDF generation run locally. The command does not upload manuscripts or telemetry. The installer must contact package sources, and Typst may access its own package cache if a future template imports packages. The current renderer uses no remote Typst packages.

Treat documents obtained from other people as untrusted input. The default include boundary prevents a document from reading unrelated local files. Use `--allow-outside-includes` only when the project deliberately shares trusted files outside its root. Do not attach confidential manuscripts to public bug reports. A minimal synthetic reproducer is preferable.

## Limitations

The metrics are meaningful only for English prose. spaCy parsing errors, unconventional TeX, domain-specific terminology, abbreviations, and sentence fragments can affect results. Zipf frequency measures general-English rarity, so legitimate names and technical terms may be highlighted. Readability formulas do not measure correctness, novelty, or scientific value.

The current release does not execute arbitrary macros, resolve semantic coreference, analyze equations, or judge whether a complex sentence is necessary. Review the quoted source sentence before editing it.

## Development

The repository locks development tools with uv. The complete local quality gate uses the following commands.

```shell
uv sync --locked
uv run ruff format .
uv run ruff check . --fix
uv run ty check
uv run pytest --cov --cov-fail-under=80
uv build
```

Python 3.11 and 3.12 are tested in continuous integration, including real Typst PDF compilation. Contribution guidance is available in [CONTRIBUTING.md](CONTRIBUTING.md), and release history is recorded in [CHANGELOG.md](CHANGELOG.md).

## License and citation

The source code is available under the [MIT License](LICENSE). Academic work may cite the metadata in [CITATION.cff](CITATION.cff).

Copyright © 2026 J.C. Vaught.

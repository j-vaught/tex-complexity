# Changelog

All notable changes to this project are recorded here. The project follows [Semantic Versioning](https://semver.org/).

## Unreleased

No changes have been recorded since version 0.1.1.

## 0.1.1 — 2026-08-14

Highlight generation now checks every destination against every requested input before analysis begins. This prevents `--force` from replacing a source file when its name matches another input's generated PDF name.

## 0.1.0 — 2026-08-14

The initial public release analyzes English prose in LaTeX and plain-text files across five metric families. It expands bounded TeX includes, recovers common citation and cross-reference values from auxiliary files, produces ranked terminal reports, and renders optional Typst PDFs with per-sentence or per-word highlighting.

The release includes deterministic offline readability calculations, safe include boundaries, explicit output-overwrite protection, Python 3.11 and 3.12 support, an automated test suite, and continuous integration for formatting, linting, type checking, coverage, package builds, and real PDF rendering.

[Unreleased]: https://github.com/j-vaught/tex-complexity/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/j-vaught/tex-complexity/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/j-vaught/tex-complexity/tree/v0.1.0

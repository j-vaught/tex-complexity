# Changelog

All notable changes to this project are recorded here. The project follows [Semantic Versioning](https://semver.org/).

## Unreleased

No changes have been recorded since version 0.1.1.

## 0.1.1 — 2026-08-14

Highlight generation now checks resolved paths and filesystem identities before analysis begins, then installs completed PDFs with an atomic replacement. This prevents `--force`, symlinks, or hard links from mutating a requested input or an unrelated linked file.

TeX preprocessing now bounds include expansion by both size and operation count while it is constructed, preserves standard and multiline hyperlink labels, and reports conversion problems without aborting valid batch siblings. Batch processing also continues after inaccessible inputs or a closed output pipe while preserving the correct failure status.

## 0.1.0 — 2026-08-14

The initial public release analyzes English prose in LaTeX and plain-text files across five metric families. It expands bounded TeX includes, recovers common citation and cross-reference values from auxiliary files, produces ranked terminal reports, and renders optional Typst PDFs with per-sentence or per-word highlighting.

The release includes deterministic offline readability calculations, safe include boundaries, explicit output-overwrite protection, Python 3.11 and 3.12 support, an automated test suite, and continuous integration for formatting, linting, type checking, coverage, package builds, and real PDF rendering.

[Unreleased]: https://github.com/j-vaught/tex-complexity/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/j-vaught/tex-complexity/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/j-vaught/tex-complexity/tree/v0.1.0

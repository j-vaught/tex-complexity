# Contributing

Contributions that improve correctness, TeX compatibility, editorial usefulness, documentation, or platform support are welcome. Open an issue before a large behavioral change so the intended metric and compatibility contract can be agreed upon first.

## Development setup

Fork and clone the repository, then create a focused branch. uv manages the supported Python runtime, environment, dependencies, and lock file.

```shell
uv sync --locked
```

The complete local quality gate matches continuous integration.

```shell
uv run ruff format .
uv run ruff check . --fix
uv run ty check
uv run pytest --cov --cov-fail-under=80
uv build
```

Typst 0.15 or newer is required to run the PDF integration tests. Tests that cannot find Typst are skipped locally, while continuous integration always installs and exercises it.

## Changes and tests

Keep changes narrow enough to review and add a regression test for each corrected behavior. Metric changes should state the mathematical or linguistic interpretation, provide contrasting examples, and keep the terminal report and highlighted PDF semantics aligned.

TeX fixtures must be synthetic and free of confidential or third-party manuscript text. Cover both the intended input and nearby counterexamples, especially for comment handling, include resolution, parser boundaries, and referential heuristics.

Update the README and changelog when a user-facing command, output format, threshold, dependency, or limitation changes. Use `J.C. Vaught` for written project attribution.

## Pull requests

Describe the problem, the chosen behavior, the user impact, and the validation performed. Keep generated PDFs and other output artifacts out of routine pull requests unless the artifact itself is necessary for visual review. Confirm that no sensitive manuscript content, credentials, local paths, or unrelated changes are included.

All contributions are accepted under the MIT License.

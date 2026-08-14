# Release process

Releases are made from a clean `main` branch after continuous integration passes on both supported Python versions. Update the version in `pyproject.toml`, the release date and narrative in `CHANGELOG.md`, the install tag in `README.md`, and the matching fields in `CITATION.cff`.

Run the complete local gate before committing the release preparation.

```shell
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest --cov --cov-fail-under=80
uv build
```

Inspect the wheel and source archive, including the version, console entry point, README rendering, and bundled MIT license. Audit the installed environment and confirm that the example report and every highlight mode still run.

After the release preparation is merged and the remote checks pass, create an annotated tag and publish the corresponding GitHub release.

```shell
git tag -a v0.1.0 -m "Release 0.1.0"
git push origin v0.1.0
gh release create v0.1.0 --verify-tag --generate-notes --title "tex-complexity 0.1.0"
```

Verify the release page and install from the exact tag with the README command. Do not reuse or move a published version tag.

# Release Checklist

## Local Validation

Run the full local checks:

```bash
make install-dev
make check
```

`make check` runs:

- `make smoke`
- `make test`
- `make compile`
- `make check-package`

## Build Artifacts

Build the source distribution and wheel:

```bash
make build
```

Validate package metadata:

```bash
make check-package
```

GitHub CI runs the same check target on pushes and pull requests.

## Install Test

Test the package in an isolated command environment:

```bash
pipx install --force dist/plex_tui-*.whl
plex-tui --version
plex-tui --smoke
```

For local source testing:

```bash
pipx install --force .
plex-tui --version
plex-tui --smoke
```

## TestPyPI

Before publishing to PyPI, run the `Publish to TestPyPI` workflow manually from
GitHub Actions. Then test installation with PyPI available for dependencies:

```bash
python -m venv /tmp/plex-tui-testpypi
/tmp/plex-tui-testpypi/bin/python -m pip install --upgrade pip
/tmp/plex-tui-testpypi/bin/python -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  plex-tui
/tmp/plex-tui-testpypi/bin/plex-tui --version
/tmp/plex-tui-testpypi/bin/plex-tui --smoke
```

## Versioning

Before tagging a release:

- Confirm the Git remote points to `https://github.com/so1omon563/plex-tui`.
- Update `version` in `pyproject.toml`.
- Move `CHANGELOG.md` entries from `Unreleased` to the release date.
- Confirm `README.md`, `PACKAGING.md`, and `config.example.toml` match current behavior.

## GitHub Release

Push the release commit and annotated tag:

```bash
git push --follow-tags
```

Then create a GitHub Release for the tag. If PyPI Trusted Publishing is
configured for the `pypi` environment, publishing the GitHub Release triggers
`.github/workflows/publish-pypi.yml`.

## Manual PyPI Fallback

Prefer Trusted Publishing. If it is not configured yet and a PyPI token is
available, upload the validated artifacts manually:

```bash
python -m twine upload dist/*
```

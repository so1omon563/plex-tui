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

## Install Test

Test the package in an isolated command environment:

```bash
pipx install --force dist/plex_tui-*.whl
plex-tui
```

For local source testing:

```bash
pipx install --force .
plex-tui
```

## Versioning

Before tagging a release:

- Confirm the Git remote points to `https://github.com/so1omon563/plex-tui`.
- Update `version` in `pyproject.toml`.
- Move `CHANGELOG.md` entries from `Unreleased` to the release date.
- Confirm `README.md`, `PACKAGING.md`, and `config.example.toml` match current behavior.

## Publish Later

When the project is tagged on `https://github.com/so1omon563/plex-tui` and has
a package publishing account:

```bash
python -m twine upload dist/*
```

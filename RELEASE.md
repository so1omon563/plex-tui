# Release Checklist

Use this checklist for tagged app releases from `so1omon563/plex-tui`.

## 1. Local Validation

Run the full local checks:

```bash
make install-dev
make check
```

`make check` runs smoke, tests, compile, and package metadata validation.

## 2. Version Prep

Before tagging:

- Update `version` in `pyproject.toml`.
- Update `src/plextui/__init__.py`.
- Move `CHANGELOG.md` entries from `Unreleased` to the release date.
- Confirm `README.md`, `PACKAGING.md`, and `config.example.toml` match current behavior.
- Confirm the Git remote points to `https://github.com/so1omon563/plex-tui`.

## 3. Build Artifacts

Build and validate the source distribution and wheel:

```bash
make clean
make build
make check-package
```

Test the wheel in an isolated command environment:

```bash
pipx install --force dist/plex_tui-*.whl
plex-tui --version
plex-tui --smoke
```

## 4. TestPyPI

Run the `Publish to TestPyPI` workflow manually from GitHub Actions. Then test
installation with PyPI available for dependencies:

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

## 5. Tag And Publish PyPI

Create and push an annotated tag:

```bash
git tag -a vX.Y.Z -m "Release X.Y.Z"
git push --follow-tags
```

Create a GitHub Release for the tag. Publishing the GitHub Release triggers
`.github/workflows/publish-pypi.yml` through PyPI Trusted Publishing. If needed,
the same workflow can be run manually with `ref=vX.Y.Z`.

After PyPI publishes, validate the real package:

```bash
python -m venv /tmp/plex-tui-pypi
/tmp/plex-tui-pypi/bin/python -m pip install --upgrade pip
/tmp/plex-tui-pypi/bin/python -m pip install plex-tui
/tmp/plex-tui-pypi/bin/plex-tui --version
/tmp/plex-tui-pypi/bin/plex-tui --smoke
```

## 6. Homebrew Tap

Update `so1omon563/homebrew-plex-tui`:

- Formula URL and sha256.
- Python resource blocks if dependencies changed.
- Formula test expectations if version output changed.

Validate:

```bash
brew test so1omon563/plex-tui/plex-tui
brew audit --strict --online so1omon563/plex-tui/plex-tui
```

## 7. Arch AUR

Update `packaging/aur/PKGBUILD` and regenerate `.SRCINFO`:

```bash
cd packaging/aur
makepkg --printsrcinfo > .SRCINFO
```

Run the `AUR Package` workflow and wait for it to pass. Then update the AUR
package repository:

```bash
cp packaging/aur/PKGBUILD /path/to/aur-plex-tui/PKGBUILD
cp packaging/aur/.SRCINFO /path/to/aur-plex-tui/.SRCINFO
cd /path/to/aur-plex-tui
git add PKGBUILD .SRCINFO
git commit -m "Update to X.Y.Z-1"
git push
```

## Manual PyPI Fallback

Prefer Trusted Publishing. If it is not available and a PyPI token is
configured, upload validated artifacts manually:

```bash
python -m twine upload dist/*
```

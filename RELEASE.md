# Release Checklist

Use this checklist for planned app releases from `so1omon563/plex-tui`.
Normal releases now move through a pull request into `main`; the merge runs
`.github/workflows/bump.yml`, creates the version tag, optionally creates the
GitHub Release, and publishes to PyPI in the same workflow run.

## 1. Local Validation

Run the full local checks:

```bash
make install-dev
make check
```

`make check` runs smoke, tests, compile, and package metadata validation.

## 2. Release PR Prep

Prepare a release PR:

- Update `version` in `pyproject.toml`.
- Update `src/plextui/__init__.py`.
- Move `CHANGELOG.md` entries from `Unreleased` to the release version and date.
- Confirm `README.md`, `PACKAGING.md`, and `config.example.toml` match current behavior.
- Confirm the Git remote points to `https://github.com/so1omon563/plex-tui`.
- Make sure the PR title or merge commit includes the right bump marker:
  `#patch`, `#minor`, or `#major`.
- Add `#release`, `#publish`, or `#ship` when the merge should create the
  GitHub Release and publish to PyPI.

The semver bumper creates tags from merge metadata, but it does not edit project
files. Keep the version files and changelog in the PR aligned with the tag the
merge will create.

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

## 5. Merge And Publish

Merge the release PR after CI passes. The `Version Bump and Release` workflow:

1. Runs `so1omon563/custom-semver-bumper@v1` on the merged PR and creates the
   next `vX.Y.Z` tag.
2. Runs `so1omon563/release-creator@v1` when the merge message includes
   `#release`, `#publish`, or `#ship`.
3. Publishes the tagged package to PyPI through Trusted Publishing after the
   GitHub Release is created.

The older `Publish to PyPI` workflow remains available as a manual fallback with
`ref=vX.Y.Z`, and still supports manually created GitHub Releases.

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

## Manual Fallbacks

If a tag exists but the release step needs to be retried, create the GitHub
Release manually or with `so1omon563/release-creator@v1`, then run
`Publish to PyPI` manually with `ref=vX.Y.Z`.

Prefer Trusted Publishing. If it is not available and a PyPI token is
configured, upload validated artifacts manually:

```bash
python -m twine upload dist/*
```

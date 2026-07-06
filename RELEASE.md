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

- Confirm `CHANGELOG.md` has accurate `Unreleased` entries for the changes being
  released. Add or revise those notes before staging the release.
- Run `make stage-release BUMP=patch`, `BUMP=minor`, or `BUMP=major`.
- Confirm `README.md`, `PACKAGING.md`, and `config.example.toml` match current behavior.
- Confirm the Git remote points to `https://github.com/so1omon563/plex-tui`.
- Make sure the PR title includes the right bump marker:
  `#patch`, `#minor`, or `#major`.
- Add `#release`, `#publish`, or `#ship` when the merge should create the
  GitHub Release and publish to PyPI.
- If the release PR started as a Linear-linked feature or fix PR, keep the
  issue key in the title, for example
  `SO1-57 Prepare release 0.14.2 #patch #release`, so Linear keeps the PR
  attached while release automation still reads the markers.

The semver bumper creates tags from merge metadata, but it does not edit project
files. `make stage-release` fetches tags, chooses the next version from the
latest semver tag, updates `pyproject.toml` and `src/plextui/__init__.py`, and
moves `CHANGELOG.md` `Unreleased` entries into a dated version section. It fails
when `Unreleased` is empty so release notes are fixed before the release PR is
opened. Keep the staged files aligned with the tag the merge will create.

Do not update Homebrew or AUR checksums in the release PR. Those checksums depend
on the tag or published artifact that does not exist until after merge. Handle
packaging repository updates in a follow-up PR whose title has no semver bump
marker, so it cannot create another version tag.

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
   next `vX.Y.Z` tag when the merged PR title includes `#patch`, `#minor`, or
   `#major`.
2. Runs `so1omon563/release-creator@v1` when the merged PR title includes
   `#release`, `#publish`, or `#ship`. Keep release markers out of ordinary PR
   bodies so examples and validation notes do not publish accidentally.
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

## Repository Protection

`main` is protected in both `so1omon563/plex-tui` and
`so1omon563/homebrew-plex-tui` with active repository rulesets:

- PRs are required.
- Force pushes and branch deletion are blocked.
- `plex-tui` requires `Python 3.11` and `Python 3.13` checks before merge.
- Approving reviews are intentionally not required. Generated packaging PRs
  should merge through required checks and auto-merge, not self-approval.

## 6. Homebrew Tap

The `Post-release Homebrew Publish` workflow updates
`so1omon563/homebrew-plex-tui` after a successful release workflow only when the
latest GitHub Release tag points at the completed workflow commit. Tag-only bump
runs are ignored so they do not repackage an older release. The workflow can also
be run manually with a release tag. It updates:

- Formula URL and sha256.
- Python resource blocks if dependencies changed.
- Formula test expectations if version output changed.
- Homebrew bottle assets and the generated formula `bottle do` block.

It builds the formula on macOS 15 with `brew install --build-bottle`, generates
bottle metadata with `brew bottle --json`, uploads the bottle tarball to a
`plex-tui-X.Y.Z` GitHub Release in the tap repository, merges the generated
`bottle do` block into the formula, runs `brew audit --strict --online`, opens a
tap PR, and merges it. This uses `PACKAGING_PR_TOKEN`, which must have access to
create releases, upload assets, push branches, and merge pull requests in the
tap repository.

Before the bottle build starts, the workflow preflights the token against the
tap repository's REST, GraphQL, and pull-request APIs. This should catch missing
or invalid PR permissions before spending time on the hosted bottle build. The
tap branch and PR steps are also idempotent: a rerun reuses the
`automation/plex-tui-vX.Y.Z` branch or an existing tap PR when a previous run
failed after pushing the branch.

If the automated workflow cannot run, update and validate manually:

```bash
brew test so1omon563/plex-tui/plex-tui
brew audit --strict --online so1omon563/plex-tui/plex-tui
```

Open tap updates as packaging-only PRs without semver bump markers.

## 7. Arch AUR

The `Post-release AUR Update` workflow opens a packaging-only PR after a
successful release workflow only when the latest GitHub Release tag points at the
completed workflow commit. Tag-only bump runs are ignored so they do not
repackage an older release. The workflow can also be run manually with a release
tag. It updates `packaging/aur/PKGBUILD`, regenerates `.SRCINFO`, validates the
package with `makepkg`, runs `namcap`, opens a PR without a semver bump marker,
and enables auto-merge.

Generated packaging PRs are not self-approved. GitHub rejects self-approval when
the PR author and approval token resolve to the same account. The rulesets use
zero required approvals so packaging-only automation branches can merge after
required checks pass.

After that PR merges, the `AUR Package` workflow validates the merged metadata
on `main`. A successful `AUR Package` run triggers `Publish AUR Package`, which
pushes `PKGBUILD` and `.SRCINFO` to `ssh://aur@aur.archlinux.org/plex-tui.git`.
This requires the `AUR_SSH_PRIVATE_KEY` repository secret.

If the automated workflow cannot run, update `packaging/aur/PKGBUILD` and
regenerate `.SRCINFO` manually:

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

Open repository metadata updates as packaging-only PRs without semver bump
markers.

## Post-Release Dry Run

To verify post-release packaging without publishing a new app release, manually
dispatch the post-release workflows with the latest real release tag, for
example `v0.3.6`. A healthy idempotent run should:

- update, bottle, and audit the Homebrew formula when bottle metadata is
  missing; then skip tap PR creation on later reruns when the formula and bottle
  block are already current;
- regenerate and validate AUR metadata, then skip packaging PR auto-merge when
  there is no diff.

## Manual Fallbacks

If a tag exists but the release step needs to be retried, create the GitHub
Release manually or with `so1omon563/release-creator@v1`, then run
`Publish to PyPI` manually with `ref=vX.Y.Z`.

Prefer Trusted Publishing. If it is not available and a PyPI token is
configured, upload validated artifacts manually:

```bash
python -m twine upload dist/*
```

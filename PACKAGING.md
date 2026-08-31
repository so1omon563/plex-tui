# Packaging

plex-tui is distributed through PyPI, a Homebrew tap, the Arch AUR, and an
upstream Nix flake. The source repository remains the canonical place for
versioning, release notes, and validation.

## Supported Channels

### PyPI

Recommended cross-platform install:

```bash
pipx install plex-tui
```

PyPI publishing uses GitHub Actions Trusted Publishing:

- Workflow: `.github/workflows/publish-pypi.yml`
- PyPI environment: `pypi`
- Trigger: GitHub Release publication, or manual workflow dispatch with a ref

TestPyPI uses a separate manual workflow:

- Workflow: `.github/workflows/publish-testpypi.yml`
- TestPyPI environment: `testpypi`

Install tests from TestPyPI need PyPI as a dependency fallback:

```bash
python -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  plex-tui
```

### Homebrew

Tap repository:

```text
https://github.com/so1omon563/homebrew-plex-tui
```

User install:

```bash
brew trust --tap so1omon563/plex-tui
brew tap so1omon563/plex-tui
brew install plex-tui
```

The formula depends on `mpv` and `python@3.13`, then installs the Python app in
a Homebrew-managed virtualenv. Post-release automation publishes Sequoia Apple
Silicon Homebrew bottles so supported installs can pour the prebuilt app
virtualenv instead of rebuilding Python resources such as `pillow` from source.
Intel macOS remains supported through Homebrew's source install path while that
platform continues to be supported. If no matching bottle is available,
Homebrew falls back to the source install path.
Homebrew 6 requires non-official taps to be trusted before Homebrew loads
formulae from them. The `plex-tui` formula only uses Homebrew/core formula
dependencies, so users do not need to trust any additional taps for `mpv`,
`python@3.13`, or the bundled Python resources.

Validation commands:

```bash
brew test so1omon563/plex-tui/plex-tui
brew audit --strict --online so1omon563/plex-tui/plex-tui
```

Install-time investigation lives in `docs/homebrew-install-time.md`. Use
`scripts/measure_homebrew_install.py` to capture no-op upgrade, reinstall,
fresh-install, and bottle-pour timings before changing the tap formula.

### Arch AUR

AUR package:

```text
https://aur.archlinux.org/packages/plex-tui
```

User install:

```bash
paru -S plex-tui
```

The source copy for AUR metadata lives in `packaging/aur/`. The package uses
Arch system dependencies, including `mpv`, `python-textual`, `python-pillow`,
`python-plexapi`, `python-platformdirs`, and `python-rich`.

Validation is handled by `.github/workflows/aur.yml`, which runs inside
`archlinux:base-devel` and checks:

- `makepkg --clean --syncdeps --noconfirm --check`
- `.SRCINFO` is in sync with `PKGBUILD`
- `namcap PKGBUILD ./*.pkg.tar.*`

### Nix

The repository flake supports `aarch64-linux` and `x86_64-linux` directly from
GitHub:

```bash
nix run github:so1omon563/plex-tui
nix profile install github:so1omon563/plex-tui
```

`flake.nix` reads the app version from `pyproject.toml`, installs the Python
dependencies through nixpkgs, and places `mpv` on the packaged command's runtime
path. CI builds the locked default package on Linux. Refresh `flake.lock` when
the pinned nixpkgs revision needs to move.

## Release Maintenance

For each new app release:

1. Publish and validate PyPI.
2. Let the `Post-release Homebrew Publish` workflow update, bottle, validate,
   and merge the Homebrew tap formula.
3. Let the `Post-release AUR Update` workflow update AUR metadata, open the
   packaging PR, approve it, and enable auto-merge.
4. After the packaging PR merges and the `AUR Package` workflow passes on
   `main`, the `Publish AUR Package` workflow pushes the validated `PKGBUILD`
   and `.SRCINFO` to AUR.

The AUR automation requires:

- `PACKAGING_PR_TOKEN`: a token that can create, approve, and auto-merge the
  generated packaging PR when branch protection requires those actions.
- `AUR_SSH_PRIVATE_KEY`: the private SSH key for pushing to
  `ssh://aur@aur.archlinux.org/plex-tui.git`.

The Homebrew automation uses `PACKAGING_PR_TOKEN`; that token must also be able
to create or update GitHub Releases, upload bottle assets, push branches, and
merge pull requests in `so1omon563/homebrew-plex-tui`.

## Known Follow-Up

- Continue validating Homebrew bottle publishing on release dry-runs and
  follow-up packaging PRs.
- Consider standalone artifacts only after the app behavior stabilizes.

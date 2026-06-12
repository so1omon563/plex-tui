# Packaging

plex-tui is distributed through PyPI, a Homebrew tap, and the Arch AUR. The
source repository remains the canonical place for versioning, release notes,
and validation.

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
brew tap so1omon563/plex-tui
brew install plex-tui
```

The formula depends on `mpv` and `python@3.13`, then installs the Python app in
a Homebrew-managed virtualenv. The first install can take several minutes
because native Python resources such as `pillow` are built from source.

Validation commands:

```bash
brew test so1omon563/plex-tui/plex-tui
brew audit --strict --online so1omon563/plex-tui/plex-tui
```

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

## Release Maintenance

For each new app release:

1. Publish and validate PyPI.
2. Update the Homebrew tap formula URL/hash and Python resources.
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

## Known Follow-Up

- Automate Homebrew tap updates after PyPI publishing.
- Investigate faster Homebrew installs without compromising formula quality.
- Consider standalone artifacts only after the app behavior stabilizes.

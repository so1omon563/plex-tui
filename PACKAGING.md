# Packaging Options

## Current Target

The current package is a standard Python project with a `plex-tui` console
script. The best short-term install path is:

```bash
pipx install .
```

This keeps Python dependencies isolated while still exposing a normal command.
Users must install `mpv` separately with their system package manager.

Users can also install from GitHub:

```bash
pipx install "git+https://github.com/so1omon563/plex-tui.git"
pipx install "git+https://github.com/so1omon563/plex-tui.git@v0.2.0"
```

For local package validation, test both source and wheel installs:

```bash
pipx install --force .
plex-tui --version
plex-tui --smoke
python -m build
pipx install --force dist/plex_tui-*.whl
plex-tui --version
plex-tui --smoke
```

## Recommended Path

1. **PyPI + pipx**

   Publish the Python package to PyPI once tagged GitHub releases are stable.
   Users install with:

   ```bash
   pipx install plex-tui
   ```

   This is the lowest-maintenance distribution path for Python/Textual apps.
   It does not solve the external `mpv` dependency, so docs must keep calling
   that out explicitly.

   The repository includes `.github/workflows/publish-pypi.yml` for PyPI Trusted
   Publishing. Configure the PyPI project to trust:

   - Owner: `so1omon563`
   - Repository: `plex-tui`
   - Workflow: `publish-pypi.yml`
   - Environment: `pypi`

   After that, publishing a GitHub Release from a `v*` tag builds and uploads
   the package.

2. **Homebrew tap**

   Add a Homebrew formula after PyPI packaging is stable. The formula can depend
   on `mpv` and install the Python package through a virtualenv.

   This would give macOS users a single command:

   ```bash
   brew install <tap>/plex-tui
   ```

   Formula requirements:

   - Depend on `python@3.13` or the current Homebrew Python.
   - Depend on `mpv`.
   - Install from a tagged source archive or PyPI release.
   - Run `plex-tui --smoke` in the formula test.

   See `packaging/homebrew/README.md` for the starting point.

3. **Arch AUR**

   Add an AUR package for Arch users. This can depend on `mpv` and Python
   dependencies from Arch packages where practical.

   Package requirements:

   - `depends=('python' 'mpv' ...)`
   - Use a tagged GitHub source archive for `plex-tui`.
   - Prefer system Python packages for `python-textual`, `python-pillow`,
     `python-plexapi`, and `python-platformdirs` when available.
   - Include a `check()` step that runs `plex-tui --smoke`.

   See `packaging/aur/PKGBUILD` for the draft package and
   `packaging/aur/README.md` for validation commands.

4. **Standalone binaries**

   Consider PyInstaller or Shiv/Pex only after the app behavior stabilizes.
   Standalone artifacts are convenient but add CI and platform complexity.
   They still cannot bundle every user's `mpv` setup cleanly, so they do not
   remove the external player dependency.

## Not Recommended Yet

- System distro packages before the app has tagged releases.
- Bundling `mpv` into the Python package.
- Native image protocol support as a packaging requirement.

## Packaging Requirements

Every distribution path should preserve:

- `plex-tui` command name.
- Python 3.11+ support.
- MIT license metadata.
- Clear external `mpv` dependency.
- Config paths based on `platformdirs`.
- Smoke/test/build checks from `RELEASE.md`.

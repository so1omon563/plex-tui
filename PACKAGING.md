# Packaging Options

## Current Target

The current package is a standard Python project with a `plex-tui` console
script. The best short-term install path is:

```bash
pipx install .
```

This keeps Python dependencies isolated while still exposing a normal command.
Users must install `mpv` separately with their system package manager.

Once pushed to GitHub, users can also install from:

```bash
pipx install "git+https://github.com/so1omon563/plex-tui.git"
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

2. **Homebrew tap**

   Add a Homebrew formula after PyPI packaging is stable. The formula can depend
   on `mpv` and install the Python package through a virtualenv.

   This would give macOS users a single command:

   ```bash
   brew install <tap>/plex-tui
   ```

3. **Arch AUR**

   Add an AUR package for Arch users. This can depend on `mpv` and Python
   dependencies from Arch packages where practical.

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

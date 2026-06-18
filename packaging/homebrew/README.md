# Homebrew Packaging

The published Homebrew tap lives in a separate repository:

```text
https://github.com/so1omon563/homebrew-plex-tui
```

Users install with:

```bash
brew tap so1omon563/plex-tui
brew install plex-tui
```

The formula installs `plex-tui` into a Homebrew-managed virtualenv and declares
`mpv` as a dependency.

## Maintenance

For each `plex-tui` release:

1. Update the formula URL and sha256 for the new PyPI sdist.
2. Refresh Python resource blocks if dependencies changed.
3. Run:

   ```bash
   brew test so1omon563/plex-tui/plex-tui
   brew audit --strict --online so1omon563/plex-tui/plex-tui
   ```

The current formula is correct but slow on first install because native Python
resources such as `pillow` are built from source.

Install-time investigation notes and the baseline measurement helper live in the
main repo at `docs/homebrew-install-time.md` and
`scripts/measure_homebrew_install.py`.

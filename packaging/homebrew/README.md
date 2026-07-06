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
3. Build and publish a Homebrew bottle, then merge the generated `bottle do`
   block into the formula.
4. Run:

   ```bash
   brew test so1omon563/plex-tui/plex-tui
   brew audit --strict --online so1omon563/plex-tui/plex-tui
   ```

The source formula is correct but slow on first install because native Python
resources such as `pillow` are built from source. Release automation publishes
Sequoia Apple Silicon macOS bottles so supported installs can pour a prebuilt
virtualenv. Intel macOS continues to use Homebrew's source-build path while that
platform remains supported.

Install-time investigation notes and the baseline measurement helper live in the
main repo at `docs/homebrew-install-time.md` and
`scripts/measure_homebrew_install.py`.

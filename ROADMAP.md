# Roadmap

## App UX

- Keep measuring real library browsing, especially any remaining grid latency after the prefetch/rendering and idle-detail passes.
- Improve the settings screen beyond action rows:
  - richer inline controls for grouped playback, artwork, browsing, and account actions
  - consider dedicated edit widgets for toggles, numeric values, and option sets
- Iterate on artwork/grid presentation:
  - tune density presets across narrow and wide terminals
  - consider separate poster-size controls if density presets are not enough
- Improve playback diagnostics:
  - add more targeted playback troubleshooting hints for common `mpv` failures
  - consider a compact active-playback footer once more player state is available

## Packaging & Distribution

- Improve Homebrew install time; the current formula works but builds native
  Python resources such as `pillow` from source.
- Automate Homebrew tap updates after PyPI releases, preferably by opening a
  pull request in `so1omon563/homebrew-plex-tui` with the new formula URL,
  sha256, and Python resource updates.
- Consider standalone artifacts only after the app behavior stabilizes.

## Technical Follow-Up

- Keep profiling grid browsing with `PLEX_TUI_PERF_LOG=1`.
- Revisit native terminal image support, especially Kitty, behind a safe opt-in path.
- Add focused regression tests for any real-world Plex media edge cases discovered during use.

# Roadmap

## App UX

- Verify real library browsing after the prefetch/rendering and idle-detail
  passes, especially any remaining list/grid latency on large remote libraries.
- Tune grid artwork defaults such as `grid_prefetch_pages` only if verification
  shows the current defaults are too aggressive or too conservative.
- Continue tuning focus and selection affordances based on real terminal themes.
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

- Keep planned releases moving through PRs so merged release PRs drive automatic
  tagging, GitHub Release creation, and PyPI publishing.
- Improve Homebrew install time; the current formula works but builds native
  Python resources such as `pillow` from source.
- Automate Homebrew tap updates after PyPI releases, preferably by opening a
  pull request in `so1omon563/homebrew-plex-tui` with the new formula URL,
  sha256, and Python resource updates.
- Consider standalone artifacts only after the app behavior stabilizes.

## Technical Follow-Up

- Use `PLEX_TUI_PERF_LOG=1` for focused regression checks when changing grid,
  artwork, pagination, or detail-loading behavior.
- Revisit whether verbose `PLEX_TUI_ARTWORK_LOG=1` should expose more structured artwork counters.
- Revisit native terminal image support, especially Kitty, behind a safe opt-in path.
- Add focused regression tests for any real-world Plex media edge cases discovered during use.

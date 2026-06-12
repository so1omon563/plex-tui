# Roadmap

## App UX

- Verify real library browsing after the prefetch/rendering and idle-detail
  passes, especially any remaining list/grid latency on large remote libraries.
- Tune grid artwork defaults such as `grid_prefetch_pages` only if verification
  shows the current defaults are too aggressive or too conservative.
- Continue tuning focus and selection affordances based on real terminal themes.
- Continue refining Settings ergonomics as new preferences are added.
- Consider separate poster-size controls only if density presets are not enough
  after real-library verification.
- Continue improving playback diagnostics as real-world `mpv` and Plex stream
  failures show up in use.

## Packaging & Distribution

- Keep planned releases moving through PRs so merged release PRs drive automatic
  tagging, GitHub Release creation, and PyPI publishing.
- Add a GitHub ruleset or branch protection for `main` that requires branch
  work, pull requests, and passing checks before merge.
- Improve Homebrew install time; the current formula works but builds native
  Python resources such as `pillow` from source.
- Extend post-release packaging automation to the Homebrew tap so a release
  publishes every supported package channel.
- Consider standalone artifacts only after the app behavior stabilizes.

## Technical Follow-Up

- Use `PLEX_TUI_PERF_LOG=1` for focused regression checks when changing grid,
  artwork, pagination, or detail-loading behavior.
- Revisit whether verbose `PLEX_TUI_ARTWORK_LOG=1` should expose more structured artwork counters.
- Revisit native terminal image support with a Kitty Unicode-placeholder
  prototype. Direct Kitty graphics protocol placement inside Textual caused UI
  hangs, so any future implementation should transmit images quietly, render
  normal placeholder text that Textual can redraw safely, and keep block art as
  the mandatory fallback.
- Add focused regression tests for any real-world Plex media edge cases discovered during use.

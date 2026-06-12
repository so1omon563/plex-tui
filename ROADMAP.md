# Roadmap

## App UX

- Rework grid view presentation so poster/title blocks feel balanced across
  terminal sizes. The current grid is functional but visually uneven: poster
  blocks, titles, and pane content can look lopsided or off-center.
- Continue tuning focus, row markers, and selection affordances based on real
  terminal themes.
- Polish the details pane hierarchy for long summaries, missing metadata, and
  playback readiness hints.
- Continue refining Settings ergonomics as new preferences are added, especially
  grouping, current-value scanning, and change feedback.
- Tune real-library browsing only when verification shows a specific issue; the
  latest perf pass showed fast grid rendering and poster fetches dominated by
  network/cache timing.
- Tune grid artwork defaults such as `grid_prefetch_pages` only if future logs
  show the current defaults are too aggressive or too conservative.
- Consider separate poster-size controls only if density presets are not enough
  after real-library verification.
- Continue improving playback diagnostics as real-world `mpv` and Plex stream
  failures show up in use.

## Packaging & Distribution

- Keep planned releases moving through PRs so merged release PRs drive automatic
  tagging, GitHub Release creation, PyPI publishing, Homebrew tap publishing,
  and AUR publishing.
- Keep `main` protected in both `plex-tui` and `homebrew-plex-tui`; `plex-tui`
  requires the Python 3.11 and 3.13 checks before merge.
- Improve Homebrew install time; the current formula works but builds native
  Python resources such as `pillow` from source.
- Keep post-release package publishing fully automated across PyPI, Homebrew,
  and AUR.
- Consider standalone artifacts only after the app behavior stabilizes.

## Plex Integration Research

- Review the Plex module in
  [`anthonycaccese/240-MP`](https://github.com/anthonycaccese/240-MP/tree/main)
  for ideas that fit a terminal-first Plex client. Areas to evaluate include
  profile switching, selective library display, Continue Watching/Resume, hubs,
  playlists, collections, categories, movie editions, pre-play audio/subtitle
  selection, alphabet browsing, show/season browsing, and direct-play versus
  transcode quality choices.

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

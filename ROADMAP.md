# Roadmap

## App UX

- Continue refining grid view presentation after the initial card/detail
  balance pass, especially against real terminal themes and wide/narrow panes.
- Continue tuning focus, row markers, and selection affordances based on real
  terminal themes. Status hints should keep a compact context prefix such as
  `Media:`, `Grid:`, or `Settings:` so the active pane is clear at a glance.
- Continue polishing the details pane hierarchy after the dense metadata,
  stream-list, and playback-readiness passes, especially real-library edge
  cases.
- Continue refining Settings ergonomics as new preferences are added, especially
  grouping, current-value scanning, and change feedback. The list rows should
  stay compact, with rules and ranges living in the details pane.
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
  requires the Python 3.11 and 3.13 checks before merge. Rulesets require PRs
  with zero approving reviews so automation branches can merge after checks
  without self-approval.
- Improve Homebrew install time; baseline the current install/update paths with
  `scripts/measure_homebrew_install.py`, then prioritize tap bottle automation.
  The current formula works but builds Python resources from source, with
  native compilation concentrated in `pillow`.
- Keep post-release package publishing fully automated across PyPI, Homebrew,
  and AUR. Periodically dry-run existing release tags through the post-release
  workflows to confirm Homebrew and AUR no-op cleanly when already current.
- Consider standalone artifacts only after the app behavior stabilizes.

## Plex Integration Research

- Research notes from
  [`anthonycaccese/240-MP`](https://github.com/anthonycaccese/240-MP/tree/main)
  live in `docs/plex-integration-research.md`.
- Continue Watching now has a sidebar browse entrypoint backed by Plex on-deck
  data; watch for real-library edge cases around ordering and pagination.
- Selective library visibility is available in Settings so noisy Plex libraries
  can be hidden from the sidebar.
- Library submenus are available for Library, Recommended, Collections, and
  Playlists. Revisit Categories after mapping PlexAPI support against a real
  server response.
- Alphabet navigation is available for loaded browse lists and grids with
  previous/next section jumps.
- Explicit playback controls are available for play-from-start versus resume,
  direct/default playback versus selected transcode quality presets, and
  Plex-side resume offsets for transcoded streams.
- Later design passes: profile switching with auto sign-in, visible movie
  edition handling, and in-playback audio/subtitle switching through mpv IPC.

## Technical Follow-Up

- Use `PLEX_TUI_PERF_LOG=1` for focused regression checks when changing grid,
  artwork, pagination, or detail-loading behavior.
- Revisit whether verbose `PLEX_TUI_ARTWORK_LOG=1` should expose more structured artwork counters.
- Continue validating Kitty Unicode-placeholder artwork in real terminals.
  Block art remains the mandatory fallback outside known native-image paths.
- Continue expanding Kitty graphics support beyond Kitty itself after the
  initial Ghostty path. `artwork_renderer = "kitty"` is the explicit "try Kitty
  protocol" override, while `auto` should stay conservative until terminal
  support is verified.
- Research explicit iTerm inline-image protocol support as a separate renderer
  path rather than assuming iTerm speaks Kitty graphics. Include WezTerm in that
  research because its documented image path follows the iTerm image protocol.
- Add focused regression tests for any real-world Plex media edge cases discovered during use.

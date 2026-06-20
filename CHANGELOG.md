# Changelog

## Unreleased

## 0.4.9 - 2026-06-19

- Improved playlist-management discoverability in the details pane, Help view,
  and README usage docs.
- Fixed a crash when selecting playlist container cards whose PlexAPI objects
  do not expose media stream parts.

## 0.4.7 - 2026-06-19

- Added playlist management for creating playlists from selected media, adding
  selected media to existing playlists, and removing items from playlist views.
- Added intentional collection-card artwork for hub, playlist, category, and
  other container grid cards, with geometric glyphs and roomier spacing for
  all-container grids such as Recommended.

## 0.4.4 - 2026-06-18

- Added a keyboard action to mark the selected playable Plex item watched or
  unwatched from the browse view.
- Added Plex library Categories browsing, visible movie-edition variants, and
  live mpv audio/subtitle switching when the active playback exposes matching
  tracks.
- Made library rows open the full Library view by default, with Space opening
  the browse-mode menu as the alternate action, and added a Settings option to
  swap those actions.
- Added a Backspace/Delete Continue Watching removal action for selected items
  in the Continue Watching view.
- Improved episode readability by showing show, season, and episode context in
  episode rows and directly under the episode title in details.

## 0.4.3 - 2026-06-18

- Made the default `mpv` window open with `--autofit=80%`, keeping custom
  Settings overrides for exact pixel sizes or other percentage presets, and
  made the old `1280x720` preset cycle back to Default.
- Added Homebrew bottle publishing to the post-release tap automation so macOS
  installs can pour a prebuilt `plex-tui` virtualenv instead of rebuilding
  Python resources from source, with bounded verbose CI diagnostics for bottle
  builds.
- Documented that Homebrew bottles are published for Apple Silicon macOS, while
  Intel macOS remains supported through Homebrew's source-build path.

## 0.4.2 - 2026-06-18

- Prefer episode stills and season posters for TV artwork while keeping show art
  as the fallback.

## 0.4.1 - 2026-06-18

- Let explicit `artwork_renderer = "kitty"` try Kitty graphics even when
  Kitty-specific environment variables are absent, and let `auto` enable the
  Kitty graphics path in Ghostty.

## 0.4.0 - 2026-06-17

- Added native Kitty poster artwork via Unicode placeholders for terminals that
  advertise Kitty graphics support, with higher-resolution native image fetches
  and block art kept as the fallback.

## 0.3.43 - 2026-06-16

- Kept the footer command bar focused on core actions while leaving the full
  keyboard reference discoverable from Help.

## 0.3.41 - 2026-06-16

- Fixed Plex-transcoded resume playback by passing the resume offset into the
  Plex stream request instead of relying only on mpv seeking.
- Split playback controls so `p` starts selected media from the beginning and
  `r` resumes from the saved Plex position when available.

## 0.3.39 - 2026-06-16

- Fixed playback resume so videos launched from in-progress rows start at the
  displayed Plex resume position even when full metadata reloads omit it.
- Made post-release Homebrew publishing wait for PyPI package availability before
  resolving formula resources.

## 0.3.37 - 2026-06-15

- Fell back to direct Plex root checks during browser login when PlexAPI's
  resource connection probe rejects URLs that are reachable from the machine.

## 0.3.35 - 2026-06-15

- Documented Homebrew 6 tap trust requirements for installing from the
  `so1omon563/plex-tui` tap.
- Verified Plex server reachability during browser login before saving a server
  URL, so first-run auth no longer offers endpoints that cannot be reached from
  the current machine.

## 0.3.31 - 2026-06-15

- Polished media type labels so list and grid rows describe Plex media kinds
  more clearly.
- Improved first-run Plex server selection by preferring usable local/private
  connection URLs, labeling connection types, marking the recommended endpoint,
  and adding relogin recovery guidance for unreachable saved URLs.

## 0.3.28 - 2026-06-13

- Added a DOX-aligned project agent model and documented repository operating
  guidance for future work.
- Added Plex integration research notes for library, collection, playlist, and
  richer metadata opportunities.
- Added Continue Watching as a first-class library entrypoint and selective
  library visibility controls.
- Restored browsable library submenus and added UI regression coverage for
  library tree navigation.
- Added paged alphabet navigation jumps for loaded media lists and grids.
- Added explicit playback quality controls for auto/direct-default playback
  versus forced Plex transcode quality presets.

## 0.3.20 - 2026-06-13

- Polished grid and details layout so poster placeholders, card text, long
  titles, facts, summaries, and detail rows fit their panes more consistently.
- Simplified Settings list scanning with compact action badges, plain section
  headers, indented value rows, and numeric ranges kept in the detail pane.
- Clarified focused-row status hints with context prefixes such as `Media:`,
  `Grid:`, and `Settings:`.
- Improved dense detail sections by wrapping metadata and preference rows,
  showing audio/subtitle stream counts, and limiting long stream lists with a
  clear remaining-count line.
- Added explicit details-pane playback readiness actions for playable items and
  openable container items.

## 0.3.14 - 2026-06-13

- Validated the fully automatic release path after fixing post-release
  packaging guards.
- Resolved post-release package guard checks so workflow-triggered packaging
  jobs compare release tags against squash merge commits instead of PR head
  commits.

## 0.3.12 - 2026-06-12

- Added release workflow guards so tag-only patch bumps do not republish the
  latest GitHub Release through Homebrew or AUR automation.
- Limited publish markers to PR titles so release examples in PR bodies do not
  accidentally create GitHub Releases.
- Protected `main` in the app and Homebrew tap repositories while keeping
  automation PRs mergeable without manual approval.
- Documented protected release automation, packaging dry-runs, and default
  semver bump expectations for future PRs.

## 0.3.6 - 2026-06-12

- Polished grid cards so poster placeholders, cached artwork, titles,
  subtitles, and selected status align more evenly in the media pane.
- Improved the details pane hierarchy with clearer playback readiness,
  explicit empty metadata/stream states, tighter preference rows, and wrapped
  summaries.
- Improved Settings detail feedback with consistent controls guidance, clearer
  armed-confirmation text, and more useful saved-setting summaries.
- Polished playback diagnostics with clearer active playback status, structured
  playback error details, and more direct debug-log follow-up guidance.
- Added shieldcn.dev README badges for CI, release, PyPI, AUR, Homebrew tap,
  and license status.
- Documented release-prep guidance for fetching origin tags before deciding the
  next release version.

## 0.3.0 - 2026-06-12

- Added `plex-tui --diagnostics` for collecting environment and playback setup details.
- Added PR-merge version tagging, GitHub Release creation, and PyPI publishing workflow automation.
- Added a local release workflow and version metadata verification target.
- Added targeted playback troubleshooting hints for common `mpv` and Plex stream failures.
- Added a compact active-playback footer while media is playing.
- Simplified Settings rows into inline controls for numeric values, toggles, and option cycling.
- Tuned grid density geometry and stabilized unloaded poster placeholders.
- Added explicit Kitty renderer fallback diagnostics while native images remain disabled inside Textual.

## 0.2.1 - 2026-06-11

- Added GitHub Actions CI and PyPI Trusted Publishing workflow scaffolding.
- Added a manual TestPyPI Trusted Publishing workflow.
- Published `plex-tui` to PyPI and updated install documentation.
- Published the Homebrew tap and updated install documentation.
- Added Arch package validation workflow scaffolding.
- Published the Arch AUR package and updated install documentation.
- Added Arch AUR packaging files and Homebrew packaging notes.
- Refreshed documentation for current install, packaging, and release workflows.
- Added a Settings diagnostics action for recent `debug.log` output and playback error details with log context.
- Clarified Settings rows with action-type tags and per-row detail-pane guidance.
- Improved grid browsing smoothness by debouncing detail reloads, throttling artwork prefetch, and avoiding cached-artwork rendering during selection redraws.
- Made grid detail reloads idle-aware so rapid selection movement no longer starts stale Plex reload workers.
- Made grid artwork appear progressively as each card renders and added stronger focused-pane styling.
- Added an explicit `[FOCUS]` marker to the active pane title.
- Kept focus markers in sync when using Tab navigation and refocused the visible browser after list/grid view changes.
- Made Tab navigation cycle explicitly through Libraries, Media, and Details panes.
- Added a short idle debounce for list detail reloads to reduce detail-pane churn during fast row movement.
- Increased the list detail debounce to further reduce repeated artwork loads during row navigation.
- Split detail text refresh from detail artwork loading so artwork waits for a longer stable selection window.

## 0.2.0 - 2026-06-11

- Improved README structure and expanded the post-0.1.0 roadmap.
- Grouped the Settings screen into account, stream, playback, artwork, browsing, and diagnostics sections.
- Added direct Settings input for custom `mpv` window sizes.
- Added direct Settings input for custom page size and auto-load threshold values.
- Added confirmation for destructive Settings preference clears.
- Replaced the heavy selected grid-card border with a quieter marker/footer treatment.
- Added configurable compact, comfortable, and large grid density modes.
- Kept Settings open after value changes and added clearer changed-value feedback.
- Preserved Settings row highlighting after opening Settings and changing values.
- Added README screenshots for grid and list views.
- Clarified README install instructions for `main` versus tagged releases.
- Improved active playback status, details-pane playback context, and abnormal `mpv` exit diagnostics.

## 0.1.0 - 2026-06-11

- Added Plex PIN login and server selection.
- Added library browsing with paged loading and automatic loading near the end of the list.
- Added current-library search with paged results and bounded global search.
- Added playback through `mpv` with Plex resume and progress reporting.
- Added audio and subtitle pickers with saved language preferences.
- Added support for external subtitles and embedded PGS/VOBSUB subtitle playback.
- Added media details for metadata, audio tracks, subtitle tracks, and saved stream preferences.
- Added settings actions for reload, relogin, and audio/subtitle preference management.
- Added settings actions for page size, auto-load threshold, mpv window sizing, and debug log visibility.
- Added playback diagnostics with token-redacted `debug.log` output.
- Added development workflow targets, smoke checks, and Linux/macOS setup documentation.
- Added release checklist and packaging option documentation.
- Added CLI flags for version, config/debug paths, and smoke checks.
- Added configurable page size and auto-load threshold for browsing performance.
- Added grid page navigation, richer grid status text, and adjacent-page artwork prefetching.

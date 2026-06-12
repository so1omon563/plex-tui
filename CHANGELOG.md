# Changelog

## Unreleased

- Added `plex-tui --diagnostics` for collecting environment and playback setup details.
- Added PR-merge version tagging, GitHub Release creation, and PyPI publishing workflow automation.
- Added a local release workflow and version metadata verification target.
- Added targeted playback troubleshooting hints for common `mpv` and Plex stream failures.
- Added a compact active-playback footer while media is playing.
- Simplified Settings rows into inline controls for numeric values, toggles, and option cycling.
- Tuned grid density geometry and stabilized unloaded poster placeholders.

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

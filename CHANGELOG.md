# Changelog

## Unreleased

- Clarified that active playback controls only work while plex-tui has focus,
  moved forward seek from `f` to `.` to avoid mpv's fullscreen key, and removed
  duplicate playback control hints from the footer.

## 0.13.3 - 2026-06-26

- Fixed current-library search so submitted `/` searches query Plex when the
  loaded page is incomplete, instead of only matching items already scrolled
  into the view.

## 0.13.2 - 2026-06-26

- Added built-in mpv network/cache options to reduce startup buffering for
  larger Plex streams.
- Added an `o` optimized playback shortcut that requests a Plex transcode for
  slow-starting media without changing the default direct-play behavior.

## 0.13.1 - 2026-06-26

- Fixed release packaging so package metadata can be republished with a version
  that matches the release tag, and gave Homebrew more time for PyPI indexing.

## 0.12.12 - 2026-06-26

- Reworked the Details pane into a quieter media-case style layout that leads
  with title, editorial facts, playback actions, and summary before catalog and
  technical stream information.
- Quieted the overall app composition by reducing pane-title chrome and letting
  unselected grid cards recede behind the selected media card.
- Softened the Libraries pane when focus is in the media grid so it reads more
  like orientation than the active browsing surface.
- Refined focus ownership so the Libraries pane marks location without keeping
  an active row when Media or Details owns focus.
- Fixed slow Discover/search submissions so the hidden search input no longer
  traps normal shortcuts like Escape or resume.
- Fixed external mpv playback so the video window opens immediately while
  plex-tui stays running.
- Fixed cached grid artwork so changing card density does not reuse images
  rendered for the previous poster size.
- Fixed left/right arrow handling so focused panes keep ownership instead of
  letting media-grid movement leak across the interface.
- Changed Tab focus to switch between Libraries and Media only, with Details
  available directly through `d`.
- Tuned grid interaction hierarchy so selected cards carry action/progress
  context while pane borders recede when unfocused.
- Subdued inactive-pane row highlights so focus remains clearer while
  preserving stable grid card geometry.
- Fixed Plex Home profile switching to prefer profile-specific server resource
  tokens, falling back to the switched account token only when Plex does not
  advertise reachable server resources for that profile.
- Fixed Continue Watching to load from Plex's profile-aware home continue hub
  instead of broader server-level On Deck and Continue Watching endpoints.
- Added Settings-based Plex Home profile switching with PIN prompts for
  protected profiles.
- Clarified in-app library management by showing hidden-library counts and
  disambiguating duplicate library names in Settings.
- Added a security policy for private vulnerability reporting, supported
  versions, and security-sensitive project areas.

## 0.12.7 - 2026-06-22

- Added a Discover alternate action to browse Plex Movies & Shows VOD hubs
  directly from the TUI, so Plex-hosted free titles can use the normal playback
  flow when Plex exposes stream URLs.
- Added a visible On Plex sidebar row for the same VOD hub browsing path.
- Added a separate Settings/config toggle for the On Plex sidebar row.
- Fixed opening Plex-hosted VOD hubs whose child URLs are returned as relative
  `/hubs/...` paths.
- Avoided per-row watched-progress reloads while rendering Plex-hosted online
  metadata lists.
- Limited Plex-hosted VOD hub child fetches to the configured page size and
  logged child-load timings, including when Plex returns more items than
  requested.
- Changed playback shortcuts on non-playable hub items to open their child
  items instead of stopping at a "not directly playable" status.
- Fixed Plex-hosted online movie playback to prefer the media part URL instead
  of a metadata-provider transcode URL that mpv can reject.
- Resolved Plex-hosted playback URLs through the VOD provider host and hydrated
  online episodes there, fixing playable movie failures and episode playback
  crashes from On Plex hubs.
- Reported unavailable Plex-hosted VOD episodes cleanly when Plex lists them
  but does not provide a stream external players can play.
- Detected Plex-hosted DRM-protected VOD playlists before launching mpv, so
  those items show the unavailable-playback view instead of appearing to play
  with no window or audio.
- Clarified On Plex detail-pane and README language so Plex-listed online
  titles are not promised as playable until playback confirms a usable stream.
- Stopped probing child items when opening playable media, avoiding Plex-hosted
  provider `/children` 404s before playback.
- Skipped external subtitle URL attachment for Plex-hosted online metadata
  playback so mpv can try the HLS stream directly.
- Logged external mpv stderr to the debug log and avoided full-screen Plex
  errors when Plex-hosted show child loading returns provider 404s.
- Loaded Plex-hosted show and season children through the working key-based
  online metadata `/children` endpoint.

## 0.12.4 - 2026-06-22

- Added Settings toggles to hide or show the Playlists and Discover sidebar
  entrypoints.
- Fixed Discover artwork for external Plex metadata image URLs, stable grid
  selection for Discover results, missing-availability selection hangs, and
  clarified Discover availability details.
- Changed startup to open Continue Watching by default instead of the first
  visible library.
- Added a Discover result-type preference and CLI option, defaulting searches
  to Movies & Shows while still allowing Movies, Shows, or All results.
- Improved Discover availability labels so result rows and provider picks show
  provider counts, offer types, and clearer no-availability states.
- Improved Discover title searches so exact movie/show title matches suppress
  obvious adjacent-title noise when Plex returns it.
- Added a default-on start-over prompt for resumable media so `p` asks whether
  to resume or start from the beginning, with a Settings toggle to disable it.
- Refreshed Continue Watching after marking an episode watched so Plex can
  surface the next episode when available.

## 0.11.1 - 2026-06-22

- Added a TUI Discover entrypoint for searching Plex Discover and opening
  provider availability links from movie/show results.
- Added `plex-tui discover-open` to open a selected Plex Discover availability
  URL in the browser.
- Added a read-only `plex-tui discover` CLI command for searching Plex Discover
  and free streaming availability with the saved account token.
- Removed the `requests` runtime dependency by using Python's standard library
  for Plex server reachability checks.

## 0.7.1 - 2026-06-21

- Expanded playlist management with a top-level Playlists entrypoint, bulk
  item selection for playlist add/remove actions, playlist rename/delete
  actions, richer playlist details, and playlist-specific Backspace/Delete
  hints while browsing playlist contents.
- Added opt-in experimental terminal playback through mpv's terminal video
  outputs. External mpv windows remain the default, while terminal playback
  prefers Kitty/Ghostty graphics, falls back to TCT text video, suspends the
  TUI, offers Smooth/Balanced/Sharp terminal video profiles, and is positioned
  as a novelty experiment rather than a replacement for external mpv playback.

## 0.5.0 - 2026-06-20

- Added compact watched-progress indicators to media rows, grid cards, browse
  status, and details so partially watched movies and episodes show how far
  along they are.
- Added live fuzzy search for the loaded current view, so `/` narrows results
  as you type and can match typos, acronyms, titles, and subtitles without
  making another Plex request.
- Added read-only CLI commands for checking app status, listing libraries,
  Continue Watching items, and Plex search results, with optional JSON output
  for scripts.
- Added Settings controls for reordering Plex libraries in the sidebar while
  preserving existing library visibility toggles.
- Added active `mpv` playback controls for pause/resume and short seek
  backward/forward actions from inside the TUI.
- Fixed app theme changes so pane chrome, status, playback footer, and active
  rows use Textual theme colors instead of a fixed custom palette.

## 0.4.13 - 2026-06-20

- Polished pane focus styling so sidebar, media, and details panes share a
  consistent focused border, title treatment, and compact focus marker.
- Made container-only grid views such as Recommended use wider navigation cards
  with two-line titles so hub and collection names are easier to read.
- Hardened Kitty artwork transmission to reduce visible graphics payload text
  leaking into the TUI during artwork refreshes.
- Improved details, Settings, list, and grid metadata rhythm with aligned
  detail rows, scannable Settings sections, and shared media metadata labels.
- Added intentional loading, empty, and Plex error states, and reused browse
  mode glyphs in the library menu for clearer wayfinding.
- Refreshed README screenshots for the current grid, list, browse-mode,
  collection-card, and block-renderer views.
- Aligned pane borders, focused pane titles, active list rows, and selected
  grid-card text around a shared visual-state palette.

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

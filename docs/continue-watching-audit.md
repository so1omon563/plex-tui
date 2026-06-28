# Continue Watching Audit

Date: 2026-06-28

Linear: SO1-24

## Scope

This audit checks the current Continue Watching implementation against a real
configured Plex account without changing library state.

## Implementation Checked

- `PlexService.continue_watching_page()` tries
  `server.library.hubs(identifier="home.continue")` first.
- If the home continue hub is unavailable, it falls back to
  `server.continueWatching()`.
- If that endpoint is unavailable, it falls back to `server.library.onDeck()`.
- The app stores the result as a `BrowseState` with source
  `continue_watching` and uses client-side slicing for pagination.
- Marking an item watched from Continue Watching refreshes page 0 so Plex can
  surface the next item or next episode.
- Removing an item calls PlexAPI `removeFromContinueWatching()` and removes the
  item from the current local view.

## Live Read-Only Check

The live probe used the saved local config and redacted item titles/keys into
short hashes. It did not call `markWatched`, `markUnwatched`, or
`removeFromContinueWatching`.

Observed behavior:

- Local page size was 40.
- `server.library.hubs(identifier="home.continue")` returned 6 items.
- `server.continueWatching()` returned 6 items.
- `server.library.onDeck()` returned 6 items.
- All three sources returned the same redacted item order for the sampled
  account state.
- Each sampled live item exposed `removeFromContinueWatching`, `markWatched`,
  and `markUnwatched`.
- `continue_watching_page(0, 2)` returned 2 items, `total=6`,
  `next_start=2`, and `has_more=True`.
- `continue_watching_page(2, 2)` returned the next 2 items, `total=6`,
  `next_start=4`, and `has_more=True`.
- `continue_watching_page(0, 40)` returned all 6 items and `has_more=False`.

## Result

No implementation change is recommended from this audit. The current behavior
stays scoped to native Plex Continue Watching/on-deck data with client-side
slicing, which matches the ticket constraint.

Destructive live checks were intentionally skipped because removing items or
marking them watched would mutate the user's Plex state. Existing tests cover
those app paths with fakes:

- `test_toggle_watched_refreshes_continue_watching_next_episode`
- `test_load_more_media_appends_continue_watching_page`
- `test_continue_watching_page_fetches_home_continue_hub`
- `test_continue_watching_page_falls_back_to_continue_watching_endpoint`
- `test_continue_watching_page_falls_back_to_on_deck`

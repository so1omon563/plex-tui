# Parent Navigation Audit

Linear SO1-57 checked whether Continue Watching TV episodes expose enough Plex
metadata to jump back to surrounding TV context after playback advancement or an
accidental watched toggle.

## Findings

- Fake Plex episode objects expose `parentKey` or `parentRatingKey` for the
  season. Resolving that key through `fetchItem()` returns a normal season
  object.
- The existing season open path already calls `episodes()` through
  `PlexService.children()`, so opening the season is enough to show previous,
  current, and neighboring episodes.
- The app already displays show/season labels in episode details, but those
  labels were not actionable from Continue Watching, search, or library episode
  rows.
- Movies, playlists, hubs, Discover, and On Plex items do not have the same
  episode parent relationship. No broader context menu is needed for the first
  slice.

## Decision

Add one shortcut: `b` opens the selected TV episode's season. That keeps the
recovery path small and reuses existing container navigation instead of adding a
new sibling picker.

## Verification

- `tests/test_plex_service.py::test_episode_parent_uses_parent_key_to_fetch_season`
  covers `parentKey` resolution.
- `tests/test_plex_service.py::test_episode_parent_falls_back_to_parent_rating_key`
  covers the fallback key shape.
- `tests/test_app_navigation.py::test_open_parent_context_from_continue_watching_episode`
  covers opening a Continue Watching episode's season and showing sibling
  episodes.

# Parent Navigation Audit

Linear SO1-57 checked whether Continue Watching TV episodes expose enough Plex
metadata to jump back to surrounding TV context after playback advancement or an
accidental watched toggle.

## Findings

- Fake Plex episode objects expose `parentKey` or `parentRatingKey` for the
  season, and `grandparentKey` or `grandparentRatingKey` for the show. Resolving
  those keys through `fetchItem()` returns normal season/show objects.
- The existing season open path already calls `episodes()` through
  `PlexService.children()`, so opening the season is enough to show previous,
  current, and neighboring episodes.
- The app already displays show/season labels in episode details, but those
  labels were not actionable or discoverable from Continue Watching, search, or
  library episode rows.
- Movies, playlists, hubs, Discover, and On Plex items do not have the same
  episode parent relationship. No broader context menu is needed for the first
  slice.

## Decision

Add two shortcuts: `b` opens the selected TV episode's season, and `B` opens
the show. Details lists both shortcuts when Plex reports the matching parent
keys. That keeps the recovery path small and reuses existing container
navigation instead of adding a new sibling picker.

## Verification

- `tests/test_plex_service.py::test_episode_parent_uses_parent_key_to_fetch_season`
  covers `parentKey` resolution.
- `tests/test_plex_service.py::test_episode_parent_falls_back_to_parent_rating_key`
  covers the fallback key shape.
- `tests/test_plex_service.py::test_episode_show_uses_grandparent_key_to_fetch_show`
  covers show-level resolution.
- `tests/test_app_helpers.py::test_episode_detail_actions_show_tv_context_shortcuts`
  covers Details-pane discoverability.
- `tests/test_app_navigation.py::test_open_parent_context_from_continue_watching_episode`
  covers opening a Continue Watching episode's season and showing sibling
  episodes.
- `tests/test_app_navigation.py::test_open_show_context_from_continue_watching_episode`
  covers opening a Continue Watching episode's show and showing seasons.

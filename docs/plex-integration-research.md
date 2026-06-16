# Plex Integration Research

## Source

- 240-MP repository: https://github.com/anthonycaccese/240-MP
- Plex module manifest: https://github.com/anthonycaccese/240-MP/blob/main/modules/plex/manifest.json
- Plex QML views: https://github.com/anthonycaccese/240-MP/tree/main/modules/plex/views
- Plex backend header: https://github.com/anthonycaccese/240-MP/blob/main/src/modules/plex/PlexBackend.h
- Architecture notes: https://github.com/anthonycaccese/240-MP/blob/main/ARCHITECTURE.md

## What 240-MP Does Well

240-MP treats Plex as a focused browse-and-play module. Its Plex module exposes
settings for enabled state, current user, auto sign-in, server, selected
libraries, video quality, resume behavior, and logout. Auth-dependent settings
are hidden until Plex auth is available.

Its Plex home view combines active server/user context with a list of Plex
entrypoints. The first-level browse experience includes Continue Watching and
selected libraries. A library opens a submenu rather than immediately dumping
all media; that submenu can route to Recommended, Library, Collections,
Playlists, and Categories. Full-library lists include an alphabet side
navigator.

The item detail view gives playback controls first-class focus. It presents
Play/Resume as the primary action, then lets the user cycle audio and subtitle
streams with left/right before launching playback. It also routes direct
playback versus forced transcode through the backend and player screen.

The backend surface is broad but coherent: users, servers, selected libraries,
continue watching, hubs, collections, playlists, categories, show/season
children, item details, direct stream URL building, transcode requests, timeline
updates, and dynamic settings options.

## Current plex-tui Coverage

Already covered:

- Plex PIN login and server selection.
- Library list browsing with paged loading and automatic load-more.
- Continue Watching as a top-level browse entry.
- Selective library display in Settings.
- Library submenus for Library, Recommended, Collections, and Playlists.
- Alphabet navigation for loaded browse lists and grids.
- Current-library and global search.
- Show/season/episode child browsing through PlexAPI child helpers.
- Separate play-from-start and resume controls, including Plex-side resume
  offsets for transcoded streams and progress reporting.
- Saved audio/subtitle language preferences plus per-item stream pickers.
- Direct playback paths where possible, with transcode fallback through PlexAPI.
- Explicit video quality/direct/transcode preference in Settings and playback.
- Details pane metadata, audio/subtitle stream display, and playback readiness.

Not yet covered:

- User/profile switching and auto sign-in.
- Library Categories where PlexAPI exposes them cleanly.
- Movie editions as distinct, visible item variants.
- In-playback audio/subtitle switching after mpv has launched.

## Recommended Sequence

1. Library Categories.
   Add Categories to the library submenu after mapping PlexAPI support against
   real server responses. Keep the default browse path simple so
   Enter-on-library behavior stays fast.

2. Profile switching and auto sign-in.
   Useful, but more invasive than the browse entrypoints because it changes auth
   and account-token assumptions. Treat it as a separate design pass.

3. Movie editions.
   Surface editions as distinct item variants once enough real-library examples
   are available to keep the UI compact.

4. In-playback track switching.
   Defer until there is a clear design for driving mpv IPC track changes and
   reconciling Plex stream state after launch.

## Design Notes for plex-tui

- Keep terminal-first density. Prefer list entrypoints and status/detail text
  over heavy nested visual UI.
- Prefer PlexAPI helpers when they exist. Add raw Plex API calls only when a
  feature is not exposed cleanly by PlexAPI.
- Keep existing library/search paging behavior. New browse entrypoints should
  return the same `MediaPage`/`MediaItem` shapes where possible.
- Add focused service tests with fake Plex objects before wiring Textual
  navigation.
- Avoid broad playback refactors when implementing browse features.

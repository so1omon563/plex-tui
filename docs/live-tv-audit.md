# Live TV Audit

Date: 2026-06-30

Linear: SO1-56

## Scope

This audit checks whether Live TV is ready for a plex-tui implementation slice
without changing Plex account or server state.

## Implementation Checked

- `PlexService` currently maps normal library, Continue Watching, Discover, and
  Plex-hosted VOD surfaces.
- `PLAYABLE_TYPES` is limited to `movie`, `episode`, `track`, and `clip`.
- Playback through `player.play_with_mpv()` needs either a direct media part URL
  or a PlexAPI object that exposes `getStreamURL()`.
- The installed PlexAPI version was `4.18.1`.
- PlexAPI exposed Discover/VOD helpers on `MyPlexAccount`, but no first-class
  Live TV, guide, tuner, channel, or DVR helpers on `PlexServer` or
  `MyPlexAccount`.
- Plex Web's Live TV route uses a hybrid guide with provider identifiers, so
  Plex-hosted free Live TV needed a separate provider check from local-server
  DVR endpoints.

## Live Read-Only Check

The live probe used the saved local config and reported only aggregate endpoint
shape. It did not print tokens, media titles, guide entries, channel names, or
stream URLs.

Observed configured state:

- Saved Plex server config was present.
- Saved server token was present.
- Saved account token was present.
- The configured server was reachable.
- Library sections were normal movie/show libraries.

Observed PlexAPI/account surface:

- `MyPlexAccount` exposed `DISCOVER`, `VOD`, and `searchDiscover`.
- No account object attribute matched Live TV, guide, DVR, tuner, or channel.

Observed raw Plex server endpoints:

- `/livetv/dvrs` returned an empty `MediaContainer`.
- `/livetv/channels` returned 404 without a DVR context.
- `/livetv/guide` returned 404 without a DVR context.
- `/tv.plex.providers.epg.cloud` returned an empty `MediaContainer`.
- `/media/providers` only exposed the local Library provider.
- `/media/subscriptions` returned an empty `MediaContainer`.

Observed Plex-hosted EPG provider behavior:

- `https://epg.provider.plex.tv/` identified the provider as Live TV with
  `protocols=["livetv"]`.
- `https://epg.provider.plex.tv/lineups/plex/channels` returned 693 channel
  objects for the saved account's region.
- Sampled channel objects included `Media` / `Part` data with HLS media
  protocol and MPEG-TS containers.
- Some sampled channels were marked DRM; the implementation should detect and
  reject those before launching mpv.
- A sampled non-DRM channel part returned HTTP 200 with
  `application/x-mpegurl` content, and the body began with an HLS playlist
  marker.

## Result

Plex-hosted Live TV is technically reachable, but it is not exposed through the
same PlexAPI helpers used by Discover/VOD and it is separate from local-server
DVR Live TV. The implementation should stay focused on the hosted EPG provider
first.

The next useful slice is a small service layer that fetches Plex-hosted EPG
channels from the account token, maps channel rows to plex-tui media objects,
and rejects DRM-marked channels before playback. A TUI sidebar row and guide
view should wait until that read-only channel model has fake-backed tests.

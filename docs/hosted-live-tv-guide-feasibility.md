# Hosted Live TV Guide Feasibility

Date: 2026-07-01

Linear: SO1-61

## Scope

This audit checks whether Plex-hosted free Live TV guide data is accessible
enough for a future plex-tui guide view. Local DVR Live TV is still out of
scope.

The live probe used the saved local account token and only reported aggregate
endpoint shape. It did not print tokens, channel names, program titles, stream
URLs, or raw response bodies.

## Existing Hosted Channel Surface

The existing hosted-channel path remains valid:

- `https://epg.provider.plex.tv/lineups/plex/channels` returned 692 hosted
  channel rows for the saved account region.
- Every returned channel row had a `gridKey`.
- Every sampled channel row had a `Media.Part` stream entry.
- Channel rows exposed stable channel identifiers through `id` and `gridKey`,
  plus display metadata such as `callSign`, `shortTitle`, `vcn`, `language`,
  `isHd`, `thumb`, `art`, and `coverPoster`.
- The current sample had no `hidden` or DRM-marked channel rows, but the app
  should keep the existing DRM and missing-stream guards because earlier hosted
  probes observed those states.

## Guide Endpoint

Plex Web's current public bundle references the hosted channel list plus a cloud
guide fetch against `/grid`, keyed by `channelGridKey` and date. The same shape
works directly against the hosted EPG provider:

```text
GET https://epg.provider.plex.tv/grid?channelGridKey=<gridKey>&date=YYYY-MM-DD
Accept: application/json
X-Plex-Token: <account token>
```

Observed behavior:

- `/grid` returned a `MediaContainer` with `Metadata`, `offset`, `size`, and
  `totalSize`.
- Sampled current-day channel guide responses returned 9 to 30 program rows per
  channel, depending on schedule length.
- Yesterday, today, tomorrow, and seven-days-out date probes all returned guide
  rows for sampled channels.
- `X-Plex-Container-Start`, `X-Plex-Container-Size`, `start`, and `size` did
  not change the returned day response in the sampled calls, so the useful
  windowing model appears to be date-based rather than page-based.
- Program rows used normal Plex-style identifiers such as `ratingKey`, `guid`,
  `key`, `type`, `year`, `summary`, `thumb`, and parent/grandparent fields.
- Program timing fields were nested under the first `Media` item:
  `beginsAt`, `endsAt`, `duration`, `onAir`, `origin`, `premiere`, and
  `videoResolution`.
- Program image and genre metadata were present through `Image` and `Genre`
  arrays.

The obvious sibling paths remained unavailable:

- `/lineups/plex/grid` returned 404.
- `/lineups/plex/guide` returned 404.
- `/lineups/plex/programs` returned 404.
- `/lineups/plex/airings` returned 404.
- `/lineups/plex/channels/<id>/grid` returned 404.
- `/lineups/plex/channels/<id>/programs` returned 404.

## Feasibility

Hosted guide data is viable for a small implementation slice. A future
implementation should reuse the existing EPG provider helper, fetch hosted
channels first, then fetch `/grid` per visible channel and selected date using
the channel `gridKey`.

Keep the first implementation intentionally narrow:

- Show a simple now/next or selected-day program list for hosted Plex channels.
- Fetch guide data on demand for visible channels instead of preloading all
  channels.
- Treat local DVR guide endpoints as out of scope.
- Keep token redaction in diagnostics and never log signed guide or stream URLs.
- Preserve existing unavailable-channel handling for DRM or missing stream
  data, even when the current sample has none.

## Recommended Next Step

Open a separate implementation ticket for a hosted-only guide view backed by
`/grid`. The ticket should not include local DVR support.

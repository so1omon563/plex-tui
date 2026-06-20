# Collection Artwork Design

`plex-tui` uses real Plex artwork whenever Plex provides media posters,
episode stills, season art, or collection art. The collection artwork system is
for a different state: browse cards that represent organization instead of
media.

## Visual Language

Collection cards should feel like wayfinding and information architecture, not
fake posters. The first version uses terminal-native geometric glyphs on muted
blueprint-style panels:

- poster or still: actual media artwork;
- missing poster: quiet missing-artwork block;
- collection card: intentional glyph for a hub, playlist, category, or query.

The glyph is the dominant artwork element. A faint construction layer of corner
marks, guide dots, and center lines sits behind the glyph so the card feels like
part of a deliberate wayfinding system instead of an empty color field. Title,
type, and action remain in the normal grid-card text below the artwork so the
visual stays calm at compact terminal sizes.

## Glyph System

Glyphs are selected from stable media metadata first, then title hints when Plex
only reports a generic hub object.

- Continue Watching: play/progress mark.
- Recently Added: plus/cross mark.
- Recently Released: burst mark.
- Recommended: connected-node constellation.
- Trending and Top shelves: upward path.
- Unwatched shelves: hollow circles.
- Actor shelves: simplified person.
- Genre and category cards: one shared family with title-derived motif
  variations, such as angled marks for action, circles for comedy, diamonds for
  horror, and grid marks for documentary.
- Playlist cards: layered panel.
- Collection cards: repeated diamond mark.
- Generic hubs: abstract geometric mark.

The system is intentionally small and text-based so it remains legible in
compact grids, plain terminals, Kitty/Ghostty image modes, and low-resolution
remote sessions. New glyphs should use the same line weight, centered geometry,
and blueprint layer so they read as symbols from one fictional design system,
not unrelated icons.

## Grid Behavior

Rows made entirely of collection cards use a navigation-grid treatment instead
of poster-grid treatment. They are left aligned and separated by a blank row so
views like Recommended read as deliberate browse choices instead of a compact
cluster of failed posters.

Mixed rows or playable-media rows continue to use the centered poster-grid
presentation.

## Screenshots

Current examples live in the README screenshot set:

- `docs/assets/collection-recommended.png`
- `docs/assets/collection-categories.png`
- `docs/assets/grid-view.png`
- `docs/assets/grid-tv-shows.png`
- `docs/assets/list-view.png`

## Expansion Notes

Future iterations can reuse these glyphs in sidebar navigation, filters,
badges, and search result indicators. New glyphs should stay geometric,
low-detail, and readable at compact density before they are added.

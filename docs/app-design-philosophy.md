# App Design Philosophy

`plex-tui` is a terminal Plex client for watching media, not managing a server.
Its interface should feel terminal-native, media-aware, and calm enough to use
from the couch or during a keyboard-heavy workday.

The collection-card artwork pass established the strongest current visual
direction: real media uses real artwork, while organizational objects use a
purpose-built wayfinding language. This document extends that idea to the whole
app.

## Product Thesis

plex-tui should feel like information architecture over decoration.

Plex's native visual language is large artwork and rich media surfaces. A
terminal client cannot and should not mimic that literally. Instead, plex-tui
should make browsing feel deliberate: clear panes, compact rows, strong
keyboard affordances, readable metadata, and artwork only where it helps the
choice.

The app should answer three questions quickly:

- Where am I?
- What is selected?
- What can I do next?

Everything else should support those answers.

## Principles

### Terminal-Native, Not Retro

The app should use the terminal as a capable modern interface, not as a nostalgia
theme. Dense information, keyboard-first flow, scrollable panes, and Textual
layout should do the work. Avoid decorative terminal tricks that make content
harder to parse.

### Watching Is The Primary Job

The browsing path should privilege choosing and playing media. Administration,
debugging, configuration, and diagnostics matter, but they should stay secondary
unless the user intentionally opens them.

### Real Media Gets Real Artwork

Posters, episode stills, season posters, and collection art should remain the
visual priority when Plex provides them. Missing media artwork should be quiet;
it should not compete with real posters or imply a special category.

### Organizational Objects Get Wayfinding

Collections, playlists, categories, hubs, and query shelves are not failed
posters. They should use the geometric glyph system documented in
`docs/collection-artwork-design.md`: centered glyphs, shared line weight, muted
blueprint layers, and title-derived variation where a screen would otherwise
repeat the same card.

### Calm Density Beats Empty Space

The app should be compact, but not cramped. Terminal users benefit from dense
lists and visible metadata; media browsing benefits from enough rhythm to compare
titles without scanning a wall of identical rows. Spacing should be meaningful:
roomier when cards represent navigation choices, tighter when browsing real
media.

### Details Are An Inspector

The details pane should behave like an inspector, not a dumping ground. The
highest-value context belongs at the top in readable phrases. Secondary metadata,
preferences, tracks, and diagnostics should be grouped below with predictable
section names.

### Visible Controls Stay Compact

The footer should show common actions and current context, while `?` Help
remains the complete reference. Prefer concise action language such as
`Media:`, `Grid:`, `Settings:`, and `Playlists:` so users know which pane owns
the action without reading prose.

## Surface Contracts

### Sidebar

The sidebar is orientation. It should show durable entry points and avoid
becoming a command palette. Continue Watching should stay visible even when
normal libraries are hidden, because it is a primary watching workflow.

Focus should be obvious but not loud. Border weight, pane title treatment, and
row highlight should work together so the active pane is visible at a glance.

### Main Browse Pane

The main pane is comparison. List and grid views should both make it easy to
compare adjacent items.

- List view should prioritize title, year, edition, duration, progress, and
  resume/watched state in a predictable order.
- Grid view should keep poster art dominant for playable media.
- Collection-only grid pages should use roomier spacing and left alignment so
  they read as browse choices.
- Mixed pages should not let container cards visually overpower real media.

### Details Pane

The details pane should follow this hierarchy:

1. Title and immediate context.
2. Playability and primary action.
3. Media facts and progress.
4. Preferences and effective playback choices.
5. Track lists.
6. Summary or diagnostics.

Episode context deserves special handling because a standalone episode title is
often not enough. Show, season, and episode number should be visible near the
title when available.

### Footer And Status Rows

The bottom rows are for orientation and action recall, not documentation.

- Status should report what loaded or what changed.
- Footer hints should stay short and context-specific.
- Destructive or state-changing actions should be named plainly.
- Full explanations belong in Help or details, not the footer.

### Settings

Settings should remain a compact list with details-pane explanations. Rows
should optimize for scanning current values; ranges, consequences, and caveats
belong in the details pane.

Any setting that cycles or toggles and rebuilds the list must preserve the
highlighted row after the change.

### Help

Help should be complete, grouped by workflow, and calm. It should not duplicate
README prose, but it must expose every action that is otherwise hidden from the
footer.

### Empty, Loading, And Error States

Empty and loading states should be informative without looking broken.

- Empty library or playlist views should say what is empty and what action, if
  any, can change it.
- Loading rows should name what is being fetched so the main pane never looks
  blank while Plex is responding.
- Missing artwork should be visually quiet.
- Playback and Plex errors should include the next useful diagnostic path
  without exposing tokens or noisy internals.

## Visual Language

### Color

Color should communicate focus, selection, media state, and object type. Avoid
adding unrelated accent colors for decoration.

The current golden selection accent is useful because it reads as action and
current choice. Muted blueprint palettes work for organizational cards because
they recede behind the glyphs. Future palettes should preserve that contrast:
real artwork carries color; interface chrome stays restrained.

### Typography And Text

Text should be compact and direct.

- Prefer labels users can act on: `Ready to play`, `Press Enter to open`,
  `p play / r resume`.
- Avoid long instructional sentences inside the TUI.
- Preserve consistent section names: `Playback`, `Metadata`, `Preferences`,
  `Effective Playback`, `Audio Tracks`, `Subtitle Tracks`, `Summary`.
- Titles can truncate in browse cards; details should recover the full context.

### Glyph Reuse

Collection glyphs should eventually appear beyond artwork cards when they help
orientation: sidebar badges, browse-mode rows, search result indicators, or
filter headings. Reuse should be modest; glyphs become product language when
they help identify object families, not when every label receives decoration.

The first reusable surface is the library browse-mode menu: Library,
Recommended, Collections, Playlists, and Categories use the same small glyph
families as their card counterparts while keeping the row label itself plain
for selection logic.

## Current Alignment

Already aligned:

- README voice now explains why the project exists.
- Collection cards have their own visual language instead of pretending artwork
  failed to load.
- Library browse modes support watching-first defaults while keeping alternate
  modes available.
- Details now elevate episode context and split playback, preferences, tracks,
  and summaries.
- Empty, loading, and Plex error states use intentional rows and inspector
  details instead of blank lists or generic error blobs.
- Library browse-mode rows reuse the collection glyph vocabulary as compact
  wayfinding markers.
- Pane borders, focused pane titles, active list rows, and selected grid-card
  text now share a small visual-state palette instead of unrelated theme
  variables.
- Footer hints keep a compact visible action set with Help as the full
  reference.

Still uneven:

- List view and grid view do not yet share a strong metadata rhythm.
- Settings rows work, but the scanning hierarchy can be tightened.
- The new non-happy-path states are intentionally simple; future screenshot
  passes should capture real examples once they are easy to reproduce.
- Glyph reuse should stay selective and earn its place surface by surface.
- README screenshots should be refreshed after palette changes are reviewed in
  a real terminal session.

## Recommended Implementation Order

1. Pane and focus polish: make active pane, active row, and pane title treatment
   feel like one system.
2. Details-pane hierarchy: tighten section spacing, labels, and high-value
   context for media, playlists, settings, and errors.
3. List/grid metadata rhythm: align title, subtitle, progress, edition, and
   action language across both browse modes.
4. Settings scan pass: preserve compact rows while making current values easier
   to compare.
5. Broader glyph reuse experiments: introduce small family markers only where
   they improve orientation.
6. Screenshot refresh: update README screenshots after the next visible UI
   refinement pass that changes the default browse surfaces.

## Review Checklist

Use this checklist for future UI PRs:

- Can the user tell which pane is focused?
- Can the user tell what is selected?
- Is the next primary action visible without opening Help?
- Does the details pane recover any context lost to browse-card truncation?
- Does real artwork remain visually dominant over chrome and placeholders?
- Do organizational objects look intentional rather than missing media?
- Does the footer stay compact?
- Does Help include every non-obvious action?
- Are tokens and private paths still absent from user-facing diagnostics?
- Do screenshots still look coherent in grid, list, collection, categories, and
  settings-heavy views?

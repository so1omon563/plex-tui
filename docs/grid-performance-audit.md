# Grid Performance Audit

Date: 2026-06-28

Linear: SO1-25

## Scope

This audit checks the current grid rendering and prefetch defaults against a
real configured Plex account without changing library state.

## Implementation Checked

- `grid_geometry_for_size()` chooses the visible grid page from pane size and
  `grid_density`.
- `MediaGrid.refresh_grid()` renders only the visible page.
- `PlexTuiApp.schedule_grid_prefetch()` hydrates visible artwork from the
  rendered-artwork cache, starts the current page first, and queues lookahead
  pages while another prefetch is in flight.
- `PlexTuiApp.prefetch_grid_items()` fetches and renders poster artwork on
  worker threads, records rendered-artwork cache hits, and only marks a page
  prefetched when all expected artwork rendered.

## Live Read-Only Check

The live probe used the saved local config and reported only aggregate counts
and timings. It did not print titles, media keys, URLs, tokens, or raw logs.

Observed config:

- `page_size=40`
- `grid_density=large`
- `grid_prefetch_pages=3`
- `artwork_mode=on`
- `artwork_renderer=auto`
- Card artwork fetch size was `24x24`.

Observed data fetches:

- Connecting to Plex took 1823.6 ms.
- Loading the library list took 778.0 ms and returned 2 libraries.
- The first browsed library page returned 11 items, all with poster artwork, in
  1616.6 ms.
- Continue Watching returned 6 items, all with poster artwork, in 773.2 ms.

Observed grid sizing and local render cost:

| Pane | Columns | Rows | Visible Items | Max Prefetched Items From Loaded Page | Grid Construct |
| --- | ---: | ---: | ---: | ---: | ---: |
| `58x24` | 1 | 1 | 1 | 4 | 0.3 ms |
| `80x24` | 2 | 1 | 2 | 8 | 0.2 ms |
| `138x34` | 4 | 2 | 8 | 11 | 0.5 ms |

Observed artwork cost:

- Cold poster sample: 8 fetched, 0 failures, median fetch 357.6 ms, max fetch
  774.5 ms.
- Cold card render: median 1.2 ms, max 11.0 ms.
- Warm poster sample: 8 cached before fetch, median cache read 0.1 ms, max
  cache read 0.2 ms.
- Warm card render: median 0.7 ms, max 11.9 ms.

## Result

No implementation change is recommended from this audit. Local grid
construction and card rendering are sub-millisecond to low-millisecond work in
the sampled paths. The slow part is read-only Plex/network artwork fetches, and
the current default of three lookahead pages stays bounded by visible page size,
the loaded page, and the existing single-active-prefetch queue.

The observed account state had a small first library page, so the wide-pane
lookahead window exhausted the loaded page at 11 items rather than reaching the
nominal `8 * 4 = 32` items. Re-check with `PLEX_TUI_PERF_LOG=1` and
`PLEX_TUI_ARTWORK_LOG=1` before changing grid density, prefetch pages, page
size, or artwork fetch size.

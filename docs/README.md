# Documentation

Start with the README. It explains the project quickly, shows the interface,
and points here when you need more detail.

## Reading Path

1. [`../README.md`](../README.md): what plex-tui is, what it feels like, and how
   to install it.
2. [`user-guide.md`](user-guide.md): first run, configuration, playback,
   keyboard bindings, artwork, diagnostics, and CLI helpers.
3. [`architecture.md`](architecture.md): runtime shape and source map.
4. [`../CONTRIBUTING.md`](../CONTRIBUTING.md): local development and PR
   expectations.

## Reference

- [`../config.example.toml`](../config.example.toml): complete commented config
  example.
- [`../DESIGN.md`](../DESIGN.md): product and visual principles.
- [`app-design-philosophy.md`](app-design-philosophy.md): implementation-facing
  UI direction and review checklist.
- [`collection-artwork-design.md`](collection-artwork-design.md): geometric
  glyph card language for non-poster objects.
- [`continue-watching-audit.md`](continue-watching-audit.md): sanitized
  Continue Watching ordering and pagination audit.
- [`parent-navigation-audit.md`](parent-navigation-audit.md): fake-backed
  parent navigation audit for Continue Watching TV episodes.
- [`live-tv-audit.md`](live-tv-audit.md): sanitized Live TV and DVR API
  reachability audit.
- [`grid-performance-audit.md`](grid-performance-audit.md): sanitized grid
  rendering and prefetch default audit.
- [`assets/`](assets/): README and showcase screenshots.

## Maintainers

- [`../PACKAGING.md`](../PACKAGING.md): PyPI, Homebrew, AUR, and package
  automation.
- [`../RELEASE.md`](../RELEASE.md): release prep, validation, and publishing.
- [`../ROADMAP.md`](../ROADMAP.md): planned follow-up work.
- [`../SECURITY.md`](../SECURITY.md): private vulnerability reporting.
- [`architecture-poster.drawio.png`](architecture-poster.drawio.png): visual
  runtime poster.
- [`codebase.drawio.png`](codebase.drawio.png): module import graph.

# Roadmap

## Immediate Post-0.1.0

- Validate a fresh install from the `v0.1.0` tag on macOS:
  - `pipx install "git+https://github.com/so1omon563/plex-tui.git@v0.1.0"`
  - `plex-tui --smoke`
  - real browsing and playback session
- Add screenshots or an animated terminal capture to the README.
- Collect rough edges from real library browsing, especially grid view latency and artwork rendering.

## App UX

- Improve the settings screen beyond action rows:
  - richer row controls for grouped playback, artwork, browsing, and account actions
  - clearer visual affordances for confirmation-required actions
- Iterate on artwork/grid presentation:
  - tune density presets across narrow and wide terminals
  - consider separate poster-size controls if density presets are not enough
- Improve playback status:
  - clearer current `mpv` state
  - better reporting when Plex/default stream choices are used
  - more visible playback errors from `debug.log`

## Packaging & Distribution

- Publish to PyPI after more tagged-release testing.
- Add a Homebrew tap formula once PyPI or tagged source installs are stable.
- Draft an Arch AUR package with `mpv` as an explicit dependency.
- Consider standalone artifacts only after the app behavior stabilizes.

## Technical Follow-Up

- Keep profiling grid browsing with `PLEX_TUI_PERF_LOG=1`.
- Revisit native terminal image support, especially Kitty, behind a safe opt-in path.
- Add focused regression tests for any real-world Plex media edge cases discovered during use.

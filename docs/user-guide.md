# User Guide

plex-tui is a terminal Plex client for browsing and watching media through
`mpv`. The README is the front door; this guide keeps the operational details in
one place.

## Requirements

- Python 3.11 or newer.
- `mpv` available on `PATH`.
- A Plex account and reachable Plex server.

When installing with PyPI or from GitHub, install `mpv` with your platform
package manager:

```bash
# macOS
brew install mpv

# Debian / Ubuntu
sudo apt install mpv

# Fedora
sudo dnf install mpv

# Arch Linux / Manjaro
sudo pacman -S mpv
```

## First Run And Configuration

On first run, plex-tui starts a Plex browser login and asks which server
connection to save. If a browser cannot be opened, use the login URL shown in
the terminal.

The login flow writes a config file with the selected server URL and token. Use
Settings or `plex-tui --config-path` to find the active file.

If your Plex server has multiple libraries with the same name, use Settings to
hide or reorder individual sidebar libraries. Duplicate library names show their
type and Plex key in Settings so each row is identifiable.

Use Settings to switch Plex Home profiles after login. Protected profiles prompt
for their PIN before reconnecting with that profile's server and account tokens.

Minimal manual config:

```toml
base_url = "http://127.0.0.1:32400"
token = "your-plex-token"
```

Environment variables also work:

```bash
export PLEX_TUI_BASE_URL="http://127.0.0.1:32400"
export PLEX_TUI_TOKEN="your-plex-token"
```

See [`config.example.toml`](../config.example.toml) for optional settings.

## CLI Helpers

Launch `plex-tui` with no command for the full interactive browser. Read-only
helpers are available for quick checks and scripts:

```bash
plex-tui --version
plex-tui --config-path
plex-tui --debug-log-path
plex-tui --diagnostics
plex-tui --smoke
plex-tui status
plex-tui status --json
plex-tui libraries
plex-tui continue-watching --limit 5
plex-tui search "blade runner"
plex-tui search "alien" --library Movies --json
plex-tui discover "matrix" --limit 5 --media-type movie
plex-tui discover-open "matrix" --index 3 --service-index 1
```

`discover-open` opens a selected Plex Discover availability URL in your
browser. In the TUI, press Space on the Discover sidebar row or select On Plex
to browse Plex Movies & Shows VOD hubs.

Some On Plex titles are listed by Plex but cannot be played through external
players such as `mpv`. plex-tui marks those items unavailable when Plex does not
provide a playable stream, including protected streams that Plex's own clients
may handle differently.

## Playback

Playback is launched through `mpv`. By default, plex-tui opens an external mpv
window so the TUI can keep showing playback status and controls.

| Key | Action |
| --- | --- |
| `p` | Play the selected item from the beginning |
| `r` | Resume from the saved Plex position when available |
| `o` | Play an optimized/transcoded stream for slow-starting media |
| `c` | Pause or resume the active `mpv` playback |
| `z` | Seek active playback back 10 seconds |
| `.` | Seek active playback forward 30 seconds |
| `x` | Stop the launched `mpv` process |
| `w` | Toggle watched / unwatched for the selected playable Plex item |

Playback controls are sent to the launched `mpv` process through IPC while
plex-tui has focus.

Playback behavior:

- Plex progress is updated in the background while playback is active.
- Press `o` on a slow-starting item to request an optimized Plex transcode for
  that launch without changing the default direct-play behavior.
- Saved audio/subtitle language preferences are applied when matching streams
  are available.
- Choosing an audio or subtitle track while playback is active also asks `mpv`
  to switch the active track when the launched stream exposes a matching track.
- Experimental terminal playback can be enabled from Settings. It is a novelty
  mode that suspends the TUI while mpv owns the terminal; external mpv remains
  the recommended watch path.

Playback mode defaults to Plex direct/default behavior. Settings can force Plex
transcoding with Original, 1080p 8 Mbps, 720p 4 Mbps, or 480p 2 Mbps quality
presets. The default `mpv` launch uses `--autofit=80%`; Settings can override it
with values such as `90%`, `1280x720`, or `80%x80%`.

## Playlist Management

Playlist actions are available from selected playable media, the top-level
Playlists sidebar row, and from inside playlist views. Use `u` to build a bulk
selection, then use the same add/remove actions on the selected set.

| Key | Where | Action |
| --- | --- | --- |
| `enter` | Playlists sidebar row | Browse all Plex playlists |
| `enter` | Playlist row/card | Open that playlist |
| `u` | Media item | Toggle the item in the bulk selection |
| `P` | Playable media item or bulk selection | Open the Add to Playlist picker |
| `enter` | Add to Playlist picker | Add the selected media to an existing playlist |
| `enter` | `New playlist...` row | Create a playlist containing the selected media |
| `backspace` / `delete` | Open playlist view | Remove selected items from that playlist |
| `e` | Playlist row/card or open playlist | Rename the playlist |
| `D` | Playlist row/card or open playlist | Confirm, then delete the playlist |

## Key Bindings

| Key | Action |
| --- | --- |
| `q` | Quit |
| `ctrl+r` | Reload Plex connection |
| `/` | Search the current view or library |
| `g` | Search all libraries through Plex |
| `?` | Show help |
| `tab` / `shift+tab` | Switch focus between Libraries and Media |
| `l` | Focus libraries |
| `m` | Focus media |
| `d` | Focus details directly |
| `space` | Run the alternate action for a selected library |
| `v` | Toggle list/grid view |
| `pageup` / `pagedown` | Move one page in grid view |
| `,` | Show settings |
| `escape` | Clear search, go back, or close current view |
| `enter` | Open selected item |
| `p` | Play selected item from the beginning |
| `r` | Resume selected item from the saved Plex position |
| `o` | Play selected item as an optimized/transcoded stream |
| `c` | Pause or resume active playback |
| `z` / `.` | Seek active playback back / forward |
| `x` | Stop launched `mpv` |
| `w` | Mark selected item watched / unwatched |
| `P` | Add selected playable item to a playlist |
| `u` | Toggle selected item for bulk playlist actions |
| `backspace` / `delete` | Remove selected item from Continue Watching or a playlist |
| `e` / `D` | Rename / delete selected or open playlist |
| `a` / `s` | Choose audio / subtitle preference |
| `A` / `S` | Clear audio preference / cycle subtitle mode |

## Artwork

plex-tui has two artwork paths: poster rendering for real media and glyph cards
for Plex objects that are not posters.

- Default mode renders portable colored block art, so it works in ordinary
  terminals without native image support.
- In Kitty and Ghostty, `artwork_renderer = "auto"` renders native terminal
  images through Kitty Unicode placeholders.
- `artwork_renderer = "kitty"` explicitly tries the Kitty graphics protocol in
  other compatible terminals.
- Collections, playlists, categories, hubs, and query shelves use geometric
  glyph artwork instead of pretending to be missing posters.
- Compact, comfortable, and large density modes adjust card and poster sizing.

See [`collection-artwork-design.md`](collection-artwork-design.md) for the
design notes behind container artwork.

## Diagnostics

Playback diagnostics are written to `debug.log` in the app config directory.
Tokens are redacted from logged `mpv` arguments.

Useful paths:

```bash
plex-tui --config-path
plex-tui --debug-log-path
```

Collect environment information for issue reports:

```bash
plex-tui --diagnostics
```

Enable browsing performance timings before launch:

```bash
PLEX_TUI_PERF_LOG=1 plex-tui
```

Verbose grid artwork internals are quieter by default. Include them only when
debugging poster loading:

```bash
PLEX_TUI_PERF_LOG=1 PLEX_TUI_ARTWORK_LOG=1 plex-tui
```

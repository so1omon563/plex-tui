# plex-tui

[![CI](https://shieldcn.dev/github/so1omon563/plex-tui/ci.png)](https://github.com/so1omon563/plex-tui/actions/workflows/ci.yml)
[![Release](https://shieldcn.dev/github/so1omon563/plex-tui/release.png)](https://github.com/so1omon563/plex-tui/releases/latest)
[![PyPI](https://shieldcn.dev/badge/dynamic/json.png?url=https%3A%2F%2Fpypi.org%2Fpypi%2Fplex-tui%2Fjson&query=%24.info.version&label=PyPI&logo=pypi)](https://pypi.org/project/plex-tui/)
[![AUR](https://shieldcn.dev/badge/dynamic/json.png?url=https%3A%2F%2Faur.archlinux.org%2Frpc%2Fv5%2Finfo%2Fplex-tui&query=%24.results%5B0%5D.Version&label=AUR&logo=archlinux)](https://aur.archlinux.org/packages/plex-tui)
[![Homebrew](https://shieldcn.dev/badge/Homebrew-tap-blue.png?logo=homebrew)](https://github.com/so1omon563/homebrew-plex-tui)
[![License](https://shieldcn.dev/github/so1omon563/plex-tui/license.png)](LICENSE)

A standalone Python/Textual terminal UI for browsing Plex and launching playback
through `mpv`.

plex-tui is an early release. It supports Plex login, server selection, paged
library browsing, search, list/grid views, stream preferences, terminal poster
artwork, and playback progress reporting.

## Screenshots

### Grid view

![plex-tui grid view](docs/assets/grid-view.png)

### List view

![plex-tui list view](docs/assets/list-view.png)

## Requirements

- Python 3.11 or newer
- `mpv` available on `PATH`
- A Plex account/server

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

## Installation

### PyPI

```bash
pipx install plex-tui
plex-tui --smoke
plex-tui
```

This is the recommended cross-platform install path. It keeps Python
dependencies isolated, but you still need to install `mpv` separately.
If `pipx` is not installed, install it with your platform package manager first
or follow the pipx installation guide.

### Homebrew

```bash
brew trust --tap so1omon563/plex-tui
brew tap so1omon563/plex-tui
brew install plex-tui
plex-tui --smoke
```

The Homebrew formula installs `mpv` automatically. Apple Silicon macOS installs
use prebuilt bottles when available so Homebrew can pour the app virtualenv
instead of rebuilding native Python dependencies such as `pillow` from source.
Intel macOS installs still use Homebrew's source-build path while that platform
continues to be supported.
Homebrew 6 requires non-official taps to be trusted before Homebrew loads
formulae from them. `plex-tui` only depends on formulae from Homebrew/core, so no
additional tap trust is required for its dependencies.

### Arch Linux

```bash
paru -S plex-tui
plex-tui --smoke
```

The AUR package depends on `mpv`. Any AUR helper can be used; `paru` is only an
example.

### GitHub

```bash
pipx install "git+https://github.com/so1omon563/plex-tui.git"
pipx install "git+https://github.com/so1omon563/plex-tui.git@v0.2.1"
```

Use this path for testing `main` before a tagged/PyPI release.

Useful CLI checks:

```bash
plex-tui --version
plex-tui --config-path
plex-tui --debug-log-path
plex-tui --diagnostics
plex-tui --smoke
```

For local development:

```bash
git clone https://github.com/so1omon563/plex-tui.git
cd plex-tui
python3 -m venv .venv
source .venv/bin/activate
make install-dev
make run
```

## First Run & Configuration

On first run, plex-tui starts a Plex browser login and asks which server
connection to save. If a browser cannot be opened, use the login URL shown in
the terminal.

The login flow writes a config file with the selected server URL and token. Use
the Settings screen or `plex-tui --config-path` to find the active file.

You can also configure a server manually. macOS config path:

```bash
mkdir -p "$HOME/Library/Application Support/plex-tui"
$EDITOR "$HOME/Library/Application Support/plex-tui/config.toml"
```

Linux config path:

```bash
mkdir -p "$HOME/.config/plex-tui"
$EDITOR "$HOME/.config/plex-tui/config.toml"
```

Minimal config:

```toml
base_url = "http://127.0.0.1:32400"
token = "your-plex-token"
```

Environment variables also work:

```bash
export PLEX_TUI_BASE_URL="http://127.0.0.1:32400"
export PLEX_TUI_TOKEN="your-plex-token"
```

See `config.example.toml` for optional settings.

## Playback

Playback is launched through `mpv`; plex-tui does not embed a video player.
Use `p` to start the selected item from the beginning, or `r` to resume from
the saved Plex position when one is available. While playback is active, Plex
progress is updated in the background. Saved audio/subtitle language
preferences are applied when matching streams are available, and the details
pane shows the effective playback choices. Playback mode defaults to
direct/default behavior and can be changed in Settings to force Plex
transcoding with Original, 1080p 8 Mbps, 720p 4 Mbps, or 480p 2 Mbps quality
presets. The default `mpv` launch uses `--autofit=80%` so videos open at a
comfortable size on modern displays; Settings can override this with values
such as `90%`, `1280x720`, or `80%x80%`. If an older config has an exact
`mpv_window_size = "1280x720"` override, cycle the mpv window-size setting once
to return to the Default preset.
Use `w` from a playable movie or episode to toggle its Plex watched state.
When playback is active, choosing an audio or subtitle track from the picker
also asks mpv to switch the active track when the launched stream exposes a
matching track.

## Key Bindings

| Key | Action |
| --- | --- |
| `q` | Quit |
| `ctrl+r` | Reload Plex connection |
| `/` | Search current library |
| `g` | Search all libraries |
| `?` | Show help |
| `tab` / `shift+tab` | Move focus |
| `l` | Focus libraries |
| `m` | Focus media |
| `space` | Run the alternate action for a selected library |
| `v` | Toggle list/grid view |
| `pageup` / `pagedown` | Move one page in grid view |
| `,` | Show settings |
| `escape` | Clear search, go back, or close current view |
| `enter` | Open selected item |
| `p` | Play selected item from the beginning |
| `r` | Resume selected item from the saved Plex position |
| `w` | Mark selected item watched / unwatched |
| `backspace` / `delete` | Remove selected item from Continue Watching |
| `a` / `s` | Choose audio / subtitle preference |
| `A` / `S` | Clear audio preference / cycle subtitle mode |
| `x` | Stop launched `mpv` |

## Features

- Plex PIN login and server selection.
- Paged library browsing with automatic loading near the end of loaded items.
- Library submenu entrypoints for all items, Recommended, Collections,
  Playlists, and Categories. Library rows open all items by default; Space
  opens the browse-mode menu, and Settings can swap the primary and alternate
  actions.
- Current-library search and bounded global search.
- List view plus configurable-density grid view with terminal poster artwork.
- External subtitle support and direct playback for embedded PGS/VOBSUB tracks.
- Audio and subtitle pickers with saved language preferences.
- Separate play-from-start and resume actions with Plex progress reporting.
- Watched/unwatched toggling for selected playable Plex items.
- Continue Watching items can be removed from the Continue Watching view.
- Movie editions appear as distinct variants when Plex reports multiple
  editions for a selected movie.
- Settings screen for stream preferences, playback mode and transcode quality,
  artwork modes, grid density, page size, auto-load threshold, grid artwork
  prefetching, media view, library Enter behavior, and `mpv` window size.
- App diagnostics view for version, paths, `mpv`, Plex connection, artwork, and
  browsing settings.

## Artwork

Poster artwork renders as portable colored block art by default, so it works in
ordinary terminals without native image support. In Kitty and Ghostty, set
`artwork_renderer` to `auto` to render native terminal images through Kitty
Unicode placeholders. Set `artwork_renderer` to `kitty` to explicitly try the
Kitty graphics protocol in other compatible terminals. This keeps Textual in
charge of layout and redraws while the terminal paints the poster inside those
cells. Outside detected Kitty-compatible terminals, `auto` falls back to block
art; `plex-tui --diagnostics` reports the active renderer status.

Grid view prefetches artwork for the visible page immediately and, by default,
prepares three pages ahead in the background. `grid_prefetch_pages` can be set
from `0` to `5`; use `0` to fetch only the visible page on slower systems.
Compact, comfortable, and large density modes adjust card and poster sizing. The
artwork cache is bounded and stored in the app cache directory shown in
Settings.

## Diagnostics

Playback diagnostics are written to `debug.log` in the app config directory.
Tokens are redacted from logged `mpv` arguments.
The Settings diagnostics section can show the debug log path, recent log lines,
and an app diagnostics summary for support reports.

Useful paths:

```bash
plex-tui --config-path
plex-tui --debug-log-path
```

Enable browsing performance timings before launch:

```bash
PLEX_TUI_PERF_LOG=1 plex-tui
```

This also records alphabet-jump decisions, including the current title, Plex
sort title, loaded alphabet buckets, and selected target row.

To collect environment information for issue reports:

```bash
plex-tui --diagnostics
```

Verbose grid artwork internals are quieter by default. Include them only when
debugging poster loading:

```bash
PLEX_TUI_PERF_LOG=1 PLEX_TUI_ARTWORK_LOG=1 plex-tui
```

## Development

Common commands:

```bash
make smoke          # app construction and helper sanity check
make test           # pytest suite
make compile        # compile src and tests
make check-package  # build and validate package metadata
make check          # smoke, tests, compile, package validation
```

Packaging and release docs:

- `PACKAGING.md`: PyPI/pipx, Homebrew, AUR, and standalone packaging options.
- `RELEASE.md`: release validation and tagging checklist.
- `ROADMAP.md`: planned follow-up work.

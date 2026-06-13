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
brew tap so1omon563/plex-tui
brew install plex-tui
plex-tui --smoke
```

The Homebrew formula installs `mpv` automatically. The first install can take
several minutes because native Python dependencies such as `pillow` are built
from source.

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
While playback is active, Plex progress is updated in the background. Saved
audio/subtitle language preferences are applied when matching streams are
available, and the details pane shows the effective playback choices.

## Key Bindings

| Key | Action |
| --- | --- |
| `q` | Quit |
| `r` | Reload Plex connection |
| `/` | Search current library |
| `g` | Search all libraries |
| `?` | Show help |
| `tab` / `shift+tab` | Move focus |
| `l` | Focus libraries |
| `m` | Focus media |
| `v` | Toggle list/grid view |
| `pageup` / `pagedown` | Move one page in grid view |
| `,` | Show settings |
| `escape` | Clear search, go back, or close current view |
| `enter` | Open selected item |
| `p` | Play selected item with `mpv` |
| `a` / `s` | Choose audio / subtitle preference |
| `A` / `S` | Clear audio preference / cycle subtitle mode |
| `x` | Stop launched `mpv` |

## Features

- Plex PIN login and server selection.
- Paged library browsing with automatic loading near the end of loaded items.
- Current-library search and bounded global search.
- List view plus configurable-density grid view with terminal poster artwork.
- External subtitle support and direct playback for embedded PGS/VOBSUB tracks.
- Audio and subtitle pickers with saved language preferences.
- Plex resume support and playback progress reporting.
- Settings screen for stream preferences, artwork modes, grid density, page
  size, auto-load threshold, grid artwork prefetching, media view, and `mpv`
  window size.
- App diagnostics view for version, paths, `mpv`, Plex connection, artwork, and
  browsing settings.

## Artwork

Poster artwork renders as portable colored block art, so it works in ordinary
terminals without Kitty, iTerm2, or Sixel support. Native Kitty image output is
disabled inside the Textual app because direct Kitty graphics protocol placement
can destabilize the UI. If `artwork_renderer` is set to `auto` or `kitty`, the
app falls back to block art and summarizes the fallback in
`plex-tui --diagnostics`.

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

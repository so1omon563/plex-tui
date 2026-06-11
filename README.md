# plex-tui

A standalone Python/Textual terminal UI for browsing Plex and launching playback
through `mpv`.

plex-tui is currently an early release. It supports Plex login, server
selection, paged library browsing, search, list/grid views, stream preferences,
terminal poster artwork, and playback progress reporting.

## Requirements

- Python 3.11 or newer
- `mpv` available on `PATH`
- A Plex account/server

Install `mpv` with your platform package manager:

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

## Install

The recommended install path is `pipx`:

```bash
pipx install "git+https://github.com/so1omon563/plex-tui.git@v0.1.0"
plex-tui --smoke
plex-tui
```

Useful CLI checks:

```bash
plex-tui --version
plex-tui --config-path
plex-tui --debug-log-path
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
  size, auto-load threshold, media view, and `mpv` window size.

## Artwork

Poster artwork renders as portable colored block art, so it works in ordinary
terminals without Kitty, iTerm2, or Sixel support. Native terminal image output
is disabled for now because Kitty protocol rendering conflicts with Textual's
screen renderer in practice.

Grid view prefetches artwork for the visible page immediately and the next page
after selection settles. Compact, comfortable, and large density modes adjust
card and poster sizing. The artwork cache is bounded and stored in the app cache
directory shown in Settings.

## Diagnostics

Playback diagnostics are written to `debug.log` in the app config directory.
Tokens are redacted from logged `mpv` arguments.

Enable browsing performance timings before launch:

```bash
PLEX_TUI_PERF_LOG=1 plex-tui
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

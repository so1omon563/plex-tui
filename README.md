# plex-tui

A small Python/Textual Plex TUI prototype.

## Requirements

- Python 3.11 or newer
- `mpv` available on `PATH`

plex-tui uses Plex for browsing/control, but playback is launched through
`mpv`. Browsing works without `mpv`, but pressing `p` to play media requires it.

Install `mpv` with your platform package manager:

```bash
# macOS with Homebrew
brew install mpv

# Debian / Ubuntu
sudo apt install mpv

# Fedora
sudo dnf install mpv

# Arch Linux / Manjaro
sudo pacman -S mpv
```

## Setup

```bash
cd ~/plex-tui
python3 -m venv .venv
source .venv/bin/activate
make install-dev
```

On first run, `plex-tui` will start a Plex browser login and then ask which server
connection to save. If the browser cannot be opened, such as over SSH or on a
headless Linux machine, use the Plex login URL shown in the terminal.

You can also create a config file manually. On macOS:

```bash
mkdir -p "$HOME/Library/Application Support/plex-tui"
$EDITOR "$HOME/Library/Application Support/plex-tui/config.toml"
```

```toml
base_url = "http://127.0.0.1:32400"
token = "your-plex-token"
```

Or use environment variables:

```bash
export PLEX_TUI_BASE_URL="http://127.0.0.1:32400"
export PLEX_TUI_TOKEN="your-plex-token"
```

On Linux, the config path is usually `~/.config/plex-tui/config.toml`:

```bash
mkdir -p "$HOME/.config/plex-tui"
$EDITOR "$HOME/.config/plex-tui/config.toml"
```

Run:

```bash
make run
```

Or run the installed console command directly:

```bash
plex-tui
```

## Development

Common local commands:

```bash
make smoke
make test
make compile
```

`make smoke` checks imports, app construction, bindings, config path resolution,
and a small helper self-check without connecting to Plex.

To try the package in an isolated command environment:

```bash
pipx install ~/plex-tui
plex-tui
```

During local development, reinstall the `pipx` copy after changes:

```bash
pipx reinstall ~/plex-tui
```

## Keys

- `q`: quit
- `r`: reload
- `/`: search current library
- `g`: search all libraries
- `?`: show help
- `tab` / `shift+tab`: move keyboard focus
- `l`: move keyboard focus to the libraries list
- `m`: move keyboard focus to the media list
- `v`: toggle media list/poster view
- `,`: show settings
- `escape`: clear search / go back
- `enter`: open selected item
- `p`: play selected playable item with `mpv`
- `a`: choose and save an audio preference
- `s`: choose and save a subtitle preference
- `x`: stop launched `mpv`

The status line shows context-sensitive hints for the highlighted row.

Search results are navigable views. Press `escape` from results or opened
children to return to the previous list. Current-library search results page
like library browsing. Global search is bounded to avoid unbounded hub results
from Plex.

Top-level library views load in pages. Navigating near the end of the loaded
items fetches the next page automatically. You can also select the
`Load more...` row and press `enter`.

The settings view shows the active config and supports reconnect/reload,
Plex relogin, clearing or changing audio/subtitle preferences separately,
artwork on/off, artwork renderer selection, and media list/poster view mode.

The details pane shows metadata, saved audio/subtitle preferences, reported
audio tracks, and reported subtitle tracks. Subtitle rows include external vs
embedded when Plex exposes enough information.

The details pane also renders Plex poster artwork as portable colored block
art when a poster is available. This works in ordinary color terminals and does
not require Kitty, iTerm2, or Sixel image protocol support. Downloaded artwork
is cached in the app cache directory shown in Settings.

Poster view mode changes the media browser from compact text rows to larger
poster cards. Cards use cached artwork immediately and update selected posters
after their artwork is fetched.

`artwork_renderer = "kitty"` enables experimental Kitty terminal image protocol
output for the details pane. `artwork_renderer = "auto"` uses Kitty output only
when a Kitty terminal is detected; otherwise it falls back to colored block art.

When playback starts, external subtitle streams reported by Plex are passed to
`mpv` automatically. Items with embedded PGS/VOBSUB subtitles are direct-played
from the original media part so `mpv` can see the subtitle tracks.

Audio and subtitle picker choices are saved as language preferences. On future
playback, plex-tui resolves those preferences against the selected media item's
available tracks. Playback status includes the resolved audio/subtitle choice,
or notes when a preferred language was not found and Plex/default behavior was
used.

Playback resumes from Plex's saved position when available. While the app is
running, playback position is reported back to Plex periodically and when
playback stops.

Playback diagnostics are written to the app config directory as `debug.log`.
The log includes stream mode, selected tracks, and sanitized `mpv` launch
arguments with Plex tokens redacted.

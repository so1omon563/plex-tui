# plex-tui

A small Python/Textual Plex TUI prototype.

## Setup

```bash
cd ~/plex-tui
python3 -m venv .venv
source .venv/bin/activate
make install-dev
```

On first run, `plex-tui` will start a Plex browser login and then ask which server
connection to save.

You can also create a config file manually:

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

On Linux, the config path is usually `~/.config/plex-tui/config.toml`.

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
- `tab` / `shift+tab`: move keyboard focus
- `l`: move keyboard focus to the libraries list
- `m`: move keyboard focus to the media list
- `,`: show settings
- `escape`: clear search / go back
- `enter`: open selected item
- `p`: play selected playable item with `mpv`
- `a`: choose and save an audio preference
- `s`: choose and save a subtitle preference
- `x`: stop launched `mpv`

Search results are navigable views. Press `escape` from results or opened
children to return to the previous list. Current-library search results page
like library browsing. Global search is bounded to avoid unbounded hub results
from Plex.

Top-level library views load in pages. Navigating near the end of the loaded
items fetches the next page automatically. You can also select the
`Load more...` row and press `enter`.

The settings view shows the active config and supports reconnect/reload,
Plex relogin, and clearing audio/subtitle preferences.

When playback starts, external subtitle streams reported by Plex are passed to
`mpv` automatically. Items with embedded PGS/VOBSUB subtitles are direct-played
from the original media part so `mpv` can see the subtitle tracks.

Audio and subtitle picker choices are saved as language preferences. On future
playback, plex-tui resolves those preferences against the selected media item's
available tracks.

Playback resumes from Plex's saved position when available. While the app is
running, playback position is reported back to Plex periodically and when
playback stops.

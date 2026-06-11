# plex-tui

A small Python/Textual Plex TUI prototype.

## Setup

```bash
cd ~/plex-tui
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
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
plex-tui
```

## Keys

- `q`: quit
- `r`: reload
- `/`: search current library
- `g`: search all libraries
- `tab` / `shift+tab`: move keyboard focus
- `l`: move keyboard focus to the libraries list
- `m`: move keyboard focus to the media list
- `escape`: clear search / go back
- `enter`: open selected item
- `p`: play selected playable item with `mpv`
- `x`: stop launched `mpv`

When playback starts, external subtitle streams reported by Plex are passed to
`mpv` automatically. Items with embedded PGS/VOBSUB subtitles are direct-played
from the original media part so `mpv` can see the subtitle tracks.

Playback resumes from Plex's saved position when available. While the app is
running, playback position is reported back to Plex periodically and when
playback stops.

# TCT Playback Spike

## Summary

mpv's `tct` video output can render video as true-color Unicode art in a text
console, and local mpv 0.41.0 reports `tct` as an available video output. That
makes terminal-video playback technically feasible, but it should not be added
to the normal playback path for the next release.

The recommended product direction from the spike was:

- Keep external `mpv` window playback as the default.
- Keep the current mpv IPC controls for normal playback.
- Treat TCT as a future opt-in experimental mode only if we can isolate it from
  the Textual app screen.

The first implementation follows that direction by exposing terminal playback
as an experimental display setting. It suspends the Textual UI, starts mpv with
terminal video output, waits for mpv to exit, and then resumes the TUI. Real
testing showed TCT works but is inherently blocky, so the launch path should
prefer mpv's Kitty graphics output in Kitty/Ghostty-compatible terminals and
use TCT as a fallback. Live Ghostty playback also showed large Kitty frame
payloads are choppy, so terminal playback needs Smooth/Balanced/Sharp profiles
that downscale and, for Smooth, reduce frame rate before mpv emits terminal
graphics. Even with those profiles, terminal playback should be treated as a
novelty/experiment; external mpv remains the recommended playback experience.

The SO1-54 follow-up keeps that automatic Kitty/TCT behavior but adds an
explicit terminal video output selector for manual experiments:

- `auto`: prefer Kitty/Ghostty detection, then fall back to TCT.
- `kitty`: force `mpv --vo=kitty`.
- `sixel`: force `mpv --vo=sixel` for mpv builds and terminals that support it.
- `tct`: force the original TCT text-video path.
- `drm`: force `mpv --vo=drm` for console sessions without a window manager.

Local macOS mpv 0.41.0 reports `tct` and `kitty`, but not `drm` or `sixel`, so
the latter two are wired as opt-in outputs for environments whose mpv builds
provide those video drivers.

## Evidence

The current mpv manual documents `tct` as a color Unicode art video output for
text consoles. It also notes that `--profile=sw-fast` may be needed for decent
performance, and that TCT image output is not synchronized with other terminal
output, which can cause broken images. The same manual recommends
`--terminal=no` or `--really-quiet` to reduce terminal-output interference and
documents `--vo-tct-buffering=<pixel|line|frame>` plus explicit
`--vo-tct-width` and `--vo-tct-height` sizing options.

Local capability check:

```text
mpv v0.41.0
Available video outputs include:
  tct              true-color terminals
  kitty            Kitty terminal graphics protocol
```

The current `plex-tui` player path launches mpv with an IPC socket and redirects
stdout/stderr to `DEVNULL`. That is correct for external-window playback, but a
TCT mode would need a terminal-owned output path instead of the current quiet
background launch.

## Integration Options

### Option 1: Replace The TUI During Playback

Launch mpv with `--vo=tct`, suspend or leave the Textual screen, and let mpv own
the terminal until playback exits.

Pros:

- Most likely to work with mpv's TCT output model.
- Avoids interleaving Textual rendering and mpv frame output.
- Preserves the current app architecture better than embedding frames.

Cons:

- Playback stops feeling integrated with the TUI.
- Returning from alternate-screen state needs careful cleanup.
- Active playback footer, details, and in-app controls are unavailable while
  mpv owns the terminal unless a separate controller process remains active.

### Option 2: Embedded TCT Pane

Try to render TCT output inside the current Textual layout.

Pros:

- Highest novelty value.
- Could make playback feel fully terminal-native if it worked perfectly.

Cons:

- High risk. mpv warns that TCT output is not synchronized with other terminal
  output.
- Textual also controls terminal drawing, cursor state, focus, alternate-screen
  behavior, and repaint timing.
- The current app redirects mpv stdout/stderr away from the terminal; a TCT
  launch path would need to let mpv write terminal frame output, which would
  compete with Rich/Textual rendering if done inside the active app screen.
- Any partial failure would look like corrupted UI rather than a graceful
  playback fallback.

This option is not recommended.

### Option 3: Separate Terminal Or Subprocess Mode

Start TCT playback in a separate terminal process or a clearly separate
command-line mode.

Pros:

- Avoids corrupting the active Textual screen.
- Keeps the feature explicit and experimental.
- Could reuse the existing stream URL, resume, progress, and IPC setup.

Cons:

- Platform-specific terminal launching is messy.
- It still does not provide a clean embedded player.
- More configuration and documentation burden than the feature likely deserves
  right now.

This is the only implementation path worth considering later.

## Prototype Command Shape

If this is revisited, the first manual experiment should be outside Textual:

```bash
mpv --vo=tct --terminal=yes --vo-tct-buffering=frame --vf=fps=15,scale=640:-2 --profile=sw-fast --really-quiet "$URL"
```

Kitty, Sixel, and DRM experiments should start with the corresponding native
mpv video output:

```bash
mpv --no-config --vo=kitty path/to/video.mp4
mpv --no-config --vo=sixel path/to/video.mp4
mpv --no-config --vo=drm path/to/video.mp4
```

Sizing experiments should add explicit cell dimensions:

```bash
mpv --vo=tct --terminal=yes --vo-tct-buffering=frame --vo-tct-width=120 --vo-tct-height=40 --vf=fps=15,scale=640:-2 --profile=sw-fast --really-quiet "$URL"
```

An app-driven prototype would need a new playback mode that does not redirect
mpv's terminal output to `DEVNULL`, and it should probably leave the Textual
screen before launching mpv.

## Implementation Direction

Keep external mpv playback as the default path. Terminal playback should remain
an explicit opt-in path that isolates mpv terminal output from Textual
rendering, prefers Kitty/Ghostty graphics when available, and treats TCT as a
portable but block-cell fallback. Do not position terminal playback as a
replacement for the external mpv window.

## Future Acceptance Criteria

Promote TCT beyond research only if all of these are true:

- It is opt-in and never the default playback mode.
- The TUI returns cleanly after playback exits or fails.
- mpv terminal output cannot corrupt the Textual layout.
- Existing play-from-start, resume, progress reporting, and token-redacted
  diagnostics still work.
- Failure falls back to normal external mpv playback or shows a clear error.

## Sources

- [mpv manual: terminal video outputs and TCT options](https://mpv.io/manual/stable/#video-output-drivers-tct)

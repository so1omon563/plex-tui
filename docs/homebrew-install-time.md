# Homebrew Install-Time Investigation

The current Homebrew formula is correct for a Python application: it uses
`Language::Python::Virtualenv`, declares `python@3.13`, and installs explicit
Python `resource` blocks into a Homebrew-managed virtualenv. The slow path is
therefore expected formula work, not a known correctness bug.

## Current Hypothesis

Fresh installs are slow because Homebrew installs the app from source resources.
Most dependencies are pure Python, but `pillow` is a native dependency and is
the most likely expensive build. Even no-op updates can feel slow because
Homebrew still evaluates the tap, dependency state, Python resources, and the
installed virtualenv before deciding there is little to do.

Baseline measurements on Apple silicon with `plex-tui 0.4.2`:

| Scenario | Auto-update | Result |
| --- | --- | ---: |
| `brew upgrade plex-tui` no-op | disabled | 0.5s |
| `brew upgrade plex-tui` no-op | enabled | 4.7s |
| `brew reinstall plex-tui` from source | disabled | 49.6s |
| `brew install plex-tui` after uninstall | disabled | 49.6s |
| `brew install --force-bottle plex-tui` from local bottle | disabled | 3.3s |
| `brew test plex-tui` | n/a | 3.0s |

The source install output reported `/opt/homebrew/Cellar/plex-tui/0.4.2` was
"built in 47 seconds". The local bottle prototype avoided that build and poured
successfully in 3.3 seconds, then passed `brew test`.

Separate these timing buckets before changing packaging:

- Homebrew overhead: auto-update, tap loading, dependency resolution, and audit
  checks.
- System dependencies: `mpv` and `python@3.13` installation or upgrades.
- App resources: Python source resources installed into `libexec`.
- Native compilation: currently expected to be dominated by `pillow`.
- Post-install checks: `brew test` and smoke execution.

## Dependency Layers

A truly first-time Homebrew install has two dependency layers:

- Formula dependencies: `mpv` and `python@3.13`, plus their recursive Homebrew
  dependencies. On the measured machine these were already installed, but
  `brew deps --installed so1omon563/plex-tui/plex-tui` listed the full runtime
  stack, including `ffmpeg`, `vapoursynth`, `yt-dlp`, and many media libraries
  below `mpv`.
- Python resources: the formula vendors every Python dependency into
  `plex-tui`'s Homebrew-managed virtualenv. These resources are absent from a
  fresh `plex-tui` install even if the user has similar packages elsewhere.

The Python resources currently installed by the formula are:

- `certifi`
- `charset-normalizer`
- `idna`
- `linkify-it-py`
- `markdown-it-py`
- `mdit-py-plugins`
- `mdurl`
- `pillow`
- `platformdirs`
- `PlexAPI`
- `Pygments`
- `requests`
- `rich`
- `textual`
- `typing-extensions`
- `uc-micro-py`
- `urllib3`

Homebrew logs from a `--build-bottle` install showed each Python resource being
built as a wheel from its source resource. Only `pillow` produced native
extensions and a compiler log. The installed virtualenv contains Pillow
extension modules such as `PIL/_imaging*.so`, and `brew linkage plex-tui` shows
links to `freetype`, `jpeg-turbo`, `libtiff`, and `little-cms2`.

## Measurement Script

Use the local measurement helper from the repository root:

```bash
python3 scripts/measure_homebrew_install.py --help
```

Measure a no-op update path without changing the installed formula:

```bash
python3 scripts/measure_homebrew_install.py --upgrade --test --output /tmp/plex-tui-brew-noop.json
```

Measure a reinstall of the current formula:

```bash
python3 scripts/measure_homebrew_install.py --reinstall --test --output /tmp/plex-tui-brew-reinstall.json
```

Measure a fresh formula install after uninstalling only `plex-tui`:

```bash
python3 scripts/measure_homebrew_install.py --fresh-install --test --output /tmp/plex-tui-brew-fresh.json
```

Measure a bottle-pour path after adding a valid `bottle do` block to the tap
formula:

```bash
python3 scripts/measure_homebrew_install.py --fresh-install --force-bottle --test --output /tmp/plex-tui-brew-bottle.json
```

By default, the script sets `HOMEBREW_NO_AUTO_UPDATE=1` so measurements focus on
the formula and dependency work. Add `--allow-auto-update` when measuring the
full user-facing command cost.

## Candidate Improvements

### Bottle The Tap

Build and publish Homebrew bottles for `so1omon563/homebrew-plex-tui`, then add
a `bottle do` block to the formula. Homebrew automatically downloads a matching
bottle when one exists, which should avoid rebuilding the virtualenv and native
resources during ordinary installs.

This is the highest-impact path for first-install time in the current
measurement. A local `arm64_tahoe` bottle for `0.4.2` was 3.1MB, relocatable
with `cellar: :any`, and poured in 3.3 seconds. It requires a tap-side bottle
workflow, storage for bottle artifacts, formula `bottle do` updates, and
verification on the supported macOS runners.

### Reduce Runtime Dependencies

Review whether any dependency can move from required runtime to an optional
feature. `pillow` is the main candidate because it enables rich artwork paths
but also brings native build cost. Removing or optionalizing it would require a
deliberate app fallback so Homebrew users do not lose expected artwork behavior
silently.

This path can improve both Homebrew and PyPI installs, but it changes app
capability and needs product judgment.

### Keep The Formula Source-Based

Keep `virtualenv_install_with_resources` unchanged and improve docs only. This
preserves the simplest, most standard formula and avoids bottle automation, but
it does not solve the initial-install pain.

### Standalone Artifacts

Standalone app artifacts could bypass Python resource installation entirely, but
they are a larger distribution project. Keep this behind bottle exploration
unless app packaging requirements change.

## Next Slice

1. Capture baseline timings for no-op upgrade, reinstall, and fresh install on
   Apple silicon. Done for `0.4.2`.
2. Prototype bottle creation in the tap repo and compare bottle-pour timing
   against the baseline. Done locally for `arm64_tahoe`.
3. Add tap automation that builds bottles, uploads them to a release asset, and
   merges the generated `bottle do` block. Implemented in the post-release
   Homebrew workflow.
4. Keep optional `pillow` dependency reduction as a secondary path if bottle
   automation proves too brittle.
5. Update `PACKAGING.md` and the tap README once bottle automation is proven.

## References

- Homebrew Bottles: https://docs.brew.sh/Bottles
- Homebrew Python formula guidance:
  https://docs.brew.sh/Python-for-Formula-Authors

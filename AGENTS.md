# Repository Guidelines

## Project Structure & Module Organization

This is a Python/Textual terminal app for browsing Plex and launching playback
through `mpv`.

- `src/plextui/`: application source.
  - `app.py`: Textual UI, navigation, settings, and high-level actions.
  - `plex_service.py`: Plex API mapping and media detail extraction.
  - `player.py`: `mpv` launch, stream selection, and playback diagnostics.
  - `config.py`, `auth.py`, `artwork.py`, `models.py`: supporting modules.
- `tests/`: pytest suite, split by app helpers/navigation and service modules.
- `.github/workflows/`: CI plus PyPI/TestPyPI/AUR validation workflows.
- `packaging/`: Homebrew and AUR maintenance notes; `packaging/aur/` contains
  the source copy of `PKGBUILD` and `.SRCINFO`.
- `README.md`, `PACKAGING.md`, `RELEASE.md`, `ROADMAP.md`: user and release docs.
- `config.example.toml`: example user configuration.

## Build, Test, and Development Commands

Use the project Makefile from the repository root:

```bash
make install-dev   # install editable package with dev dependencies
make run           # start the TUI locally
make smoke         # import/app construction sanity check
make test          # run pytest
make compile       # compile src and tests
make build         # build sdist and wheel
make check-package # build and validate package metadata
make check         # smoke, tests, compile, and package validation
```

The app requires Python 3.11+ and uses external `mpv` for playback.

## Coding Style & Naming Conventions

Use standard Python style with 4-space indentation and type annotations for new
public helpers or cross-module data. Prefer small pure helper functions for
rendering/status logic, and keep Textual event handling in `PlexTuiApp`.

Naming conventions:

- Classes: `PascalCase`, for example `MediaGrid`.
- Functions and variables: `snake_case`.
- Tests: `test_<behavior>` or async helpers named `run_<behavior>_check`.

No formatter is currently enforced. Keep edits minimal and consistent with
nearby code.

## Testing Guidelines

Tests use `pytest`. Add focused unit tests for helper logic and app navigation
tests for Textual behavior. Prefer deterministic fake objects over live Plex
calls. Run at least:

```bash
make test
make compile
make smoke
```

For packaging or metadata changes, also run `make check-package` or `make check`.
For AUR package changes, run the `AUR Package` workflow or validate with
`makepkg` on Arch.

## Commit & Pull Request Guidelines

Git history uses short imperative subjects, such as `Speed up grid navigation`
and `Polish settings and grid navigation`. Keep commits scoped to one logical
change and include docs/tests with behavior changes.

Pull requests should include:

- A concise summary of user-visible behavior.
- Tests run and results.
- Screenshots or terminal notes for TUI changes when useful.
- Any config, packaging, or migration impact.

Use PRs for repository changes. When publishing local commits, branch from
`main` with a scoped name such as `codex/release-prep`, push that branch, and
open a draft PR instead of pushing directly to `main`. Treat `main` as a
protected branch even before GitHub branch protection or rulesets are enabled.

By default, PR titles or bodies should include exactly one semver bump marker:
`#patch`, `#minor`, or `#major`. Most changes should advance tags when merged,
even when they do not publish a GitHub Release. Add `#release` only when the
merge should create the GitHub Release and publish package channels. Exceptions
are allowed for packaging-only follow-ups, automation repair, docs-only
maintenance, or other changes that should not create a new version tag; call out
the reason in the PR body when omitting a bump marker.

GitHub CLI notes:

- `gh auth status` may fail inside the sandbox even when the user is logged in
  via the macOS keyring. Re-run `gh` auth, PR, and push operations outside the
  sandbox when keyring access is required.
- Prefer the GitHub connector for PR creation when it has access. If it returns
  `403 Resource not accessible by integration`, fall back to
  `gh pr create --draft` using the authenticated CLI session.
- Keep PR bodies explicit about validation, especially `make check` results and
  release workflow checks such as `actionlint`.

## Security & Configuration Tips

Never commit real Plex tokens, account tokens, debug logs, or local config files.
Use `config.example.toml` for examples. Logs should redact tokens; preserve that
behavior when changing playback or request diagnostics.

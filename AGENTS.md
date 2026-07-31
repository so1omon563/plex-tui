# Repository Guidelines and DOX Rail

## DOX Framework

This repository uses the DOX AGENTS.md model, adapted from
`agent0ai/dox`. AGENTS.md files are binding work contracts for their subtrees.
The root AGENTS.md is the project-wide rail for durable workflow rules,
preferences, constraints, and the Child DOX Index.

### Core Contract

- Work products, source materials, instructions, records, assets, and durable
  docs must stay understandable from the nearest applicable AGENTS.md plus each
  parent AGENTS.md above it.
- The closer an AGENTS.md file is to the work, the more specific and practical
  it should be. A child AGENTS.md may specialize local rules, but it must not
  weaken this root contract.
- Do not rely on memory for repository rules. Re-read the applicable DOX chain
  in the current session before editing.

### Read Before Editing

Before editing files:

1. Read the root AGENTS.md.
2. Identify every file or folder expected to change.
3. Walk from the repository root to each target path.
4. Read every AGENTS.md found along each route.
5. If a parent AGENTS.md lists a child AGENTS.md whose scope contains the path,
   read that child and continue from there.
6. Use the nearest AGENTS.md as the local contract, plus parent docs for
   repo-wide rules.

### Update After Editing

Every meaningful change requires a DOX pass before the task is done. Update the
closest owning AGENTS.md when a change affects:

- purpose, scope, ownership, or responsibilities;
- durable structure, contracts, workflows, or operating rules;
- required inputs, outputs, permissions, constraints, side effects, or artifacts;
- durable user preferences about behavior, communication, process,
  organization, or quality;
- AGENTS.md creation, deletion, move, rename, or index contents.

Update parent docs when parent-level structure, ownership, workflow, or child
index entries change. Update child docs when parent changes alter local rules.
Small edits that do not change behavior or contracts may leave docs unchanged,
but the DOX pass still must happen.

### Child Doc Shape

Create a child AGENTS.md when a folder becomes a durable boundary with its own
purpose, rules, responsibilities, workflow, materials, or quality standards.
Default section order:

- Purpose
- Ownership
- Local Contracts
- Work Guidance
- Verification
- Child DOX Index

Keep docs concise, current, and operational. Document stable contracts, not
diary entries. Put broad rules in parent docs and concrete details in child
docs. Delete stale or contradictory text instead of explaining history.

### Closeout

Before finishing a task:

1. Re-check changed paths against the applicable DOX chain.
2. Update nearest owning docs and any affected parents or children.
3. Refresh affected Child DOX Index entries.
4. Remove stale or contradictory text.
5. Run existing verification when relevant.
6. Report any docs intentionally left unchanged and why.

### Child DOX Index

There are currently no child AGENTS.md files. This root file owns the top-level
contracts for these durable areas:

- `.github/workflows/`: CI, version bumping, release, PyPI, Homebrew, and AUR
  automation. Keep workflow changes aligned with release checks and actionlint.
  Homebrew bottle publishing should stay pinned to macOS 15 unless package
  coverage is deliberately moved to a different supported bottle target.
- `src/plextui/`: Python/Textual app source, Plex API mapping, artwork,
  config/auth, mpv playback, and smoke entry points.
- `tests/`: pytest coverage for app helpers/navigation, service mapping,
  config/auth/player/artwork behavior, and release workflow checks.
- `scripts/`: release/package maintenance scripts used by checks, deterministic
  release staging, and post-release automation.
- `packaging/`: Homebrew and AUR notes plus source AUR metadata.
- `docs/`: research notes and README visual assets.
- Root docs and config examples: README, DESIGN, PACKAGING, RELEASE, ROADMAP,
  CHANGELOG, SECURITY, Makefile, pyproject, and `config.example.toml`.

Add child AGENTS.md files only when a subtree needs local rules that would make
this root rail too broad.

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
- `README.md`, `CONTRIBUTING.md`, `PACKAGING.md`, `RELEASE.md`, `ROADMAP.md`:
  user, contributor, and release docs.
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
make stage-release # stage version and changelog updates for next release
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

For Plex items with multiple media versions, keep `p` and `r` as the normal
default playback actions and use `V` for explicit version selection. Version
selection must resolve the chosen Plex part after metadata reload and must not
silently fall back to another file. Direct playback must keep every ordered
part of the selected media version in one continuous timeline; unsupported
multipart modes must fail clearly before launching mpv.
Apply asynchronous browse refresh results only when their originating
`BrowseState` object is still current; source labels are not unique identities.
CLI status and diagnostics must report config-load failures without tracebacks;
JSON modes must always emit parseable error objects.

Async view-opening workers must apply UI results through the shared navigation
identity guard. Newer navigation, overlays, and Back actions invalidate older
results, and media pickers must also verify that their originating selection is
still current.

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

For behavior changes that users or future release notes should know about, add
or update the `CHANGELOG.md` `Unreleased` section as part of the work. Do not
leave release-note reconstruction to the release staging step unless the change
is intentionally internal-only and that reason is clear in the PR.

Pull requests should include:

- A concise summary of user-visible behavior.
- Tests run and results.
- Screenshots or terminal notes for TUI changes when useful.
- Any config, packaging, or migration impact.

Use PRs for repository changes. When publishing local commits, branch from
`main` with a scoped name such as `codex/release-prep`, push that branch, and
open a draft PR instead of pushing directly to `main`.
Create or switch to a scoped branch before doing repo work; do not keep feature
work in the local `main` working tree.
Repo work is not complete when a branch is merely pushed. Treat the workflow as
open until there is a draft PR for the branch or the work is explicitly
canceled.
For Linear-linked work, keep the ticket In Review while its PR is open and move
it to Done only after the PR is merged.

`main` is protected by repository rulesets. Changes must flow through PRs; force
pushes and branch deletion are blocked. `plex-tui` requires the Python 3.11 and
3.13 CI checks before merge. The Homebrew tap also requires PRs for `main`.
Rulesets intentionally require zero approving reviews so automation PRs can
merge after required checks pass without self-approval.

By default, PR titles should include exactly one standalone semver bump marker:
`#patch`, `#minor`, or `#major`. Markers are case-insensitive,
whitespace-delimited PR-title tokens. Most changes should advance tags when
merged, even when they do not publish a GitHub Release. Add `#release` only when
the merge should create the GitHub Release and publish package channels.
Exceptions are allowed for packaging-only follow-ups, automation repair,
docs-only maintenance, or other changes that should not create a new version
tag; call out the reason in the PR body when omitting a bump marker. The version
workflow reads semver bump markers from PR titles only.
When a change is judged release-worthy, do not only add `#release`: run the
scripted release prep in the same branch and keep the release marker in the PR
title. A release decision means both staged release files and a publishing
marker are required unless the release is explicitly canceled.
When converting an issue-linked feature or fix PR into a release PR, preserve
the issue key in the PR title, for example
`SO1-57 Prepare release 0.14.2 #patch #release`, so Linear keeps the PR linked
to the ticket while the release workflow still sees the title markers.

When preparing or estimating a release version, fetch remote tags first with
`git fetch --tags origin` and base the decision on the latest origin tag, not
only local tags or the latest GitHub Release. Non-release PRs with `#patch`,
`#minor`, or `#major` still create tags, so release prep files should match the
tag that the release PR merge will create.

Use `make stage-release BUMP=patch`, `BUMP=minor`, or `BUMP=major` to stage a
planned release. Agents must use this script-backed target for normal release
prep instead of hand-editing version files and moving changelog entries. The
target fetches tags, chooses the next version from the latest semver tag, updates
`pyproject.toml`, `src/plextui/__init__.py`, and `CHANGELOG.md`, and fails if
`CHANGELOG.md` has no `Unreleased` notes to release. After staging, run
`make check-release` and the relevant validation before opening the release PR.

GitHub Release publishing is controlled by standalone release markers in PR
titles only: `#release`, `#publish`, or `#ship`. Keep those markers out of
ordinary PR titles unless the merge should publish PyPI, Homebrew, and AUR. PR
bodies may mention release markers for explanation without publishing.

Post-release package workflows may depend on newly published PyPI artifacts.
Keep Homebrew tap publication waiting for `pip` to resolve the new
`plex-tui==VERSION` before updating formula resources, so PyPI indexing lag does
not break otherwise successful releases.

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
On POSIX, keep the app config directory owner-only (`0700`) and config,
debug-log, and rotated debug-log files owner-only (`0600`), including when
repairing existing files.
Persist Plex server `clientIdentifier` values so profile switches survive URL
changes and never fall back silently to another server.
Use `SECURITY.md` for vulnerability reporting policy and keep it aligned with
token handling, packaging, and release automation changes.


## Optional Local Tooling

If `rtk` is installed, it can be used to reduce noisy command output while
preserving command behavior, for example `rtk git status`, `rtk git diff`, or
`rtk pytest tests/`. Do not require `rtk` for repository work; fall back to the
normal command when it is unavailable or when raw debugging output is needed.
Run interactive full-screen TUI checks such as `make run` without `rtk`, because
the wrapper can affect terminal geometry and retained Textual rendering.

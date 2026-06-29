# Contributing

Thanks for helping improve plex-tui. The project values small, focused changes
that keep the app calm, keyboard-first, and reliable.

## Local Setup

```bash
git clone https://github.com/so1omon563/plex-tui.git
cd plex-tui
python3 -m venv .venv
source .venv/bin/activate
make install-dev
```

## Common Commands

```bash
make run           # start the TUI locally
make smoke         # import/app construction sanity check
make test          # run pytest
make compile       # compile src and tests
make check-package # build and validate package metadata
make check         # smoke, tests, compile, package validation
```

Run the smallest focused test that covers your change while working. Before a
PR, run `make check` when the change affects app behavior, packaging metadata,
or public documentation examples.

## Pull Requests

- Open changes through a PR; `main` is protected.
- Keep each PR scoped to one logical change.
- Include tests or a clear validation note.
- Update `CHANGELOG.md` `Unreleased` for behavior changes users should know
  about.
- Use exactly one semver bump marker in the PR title when the merge
  should create a version tag: `#patch`, `#minor`, or `#major`.
- Add `#release` only when the merge should publish a GitHub Release and package
  channels.
- When converting an issue-linked PR into a release PR, keep the issue key in
  the title, for example `SO1-57 Prepare release 0.14.2 #patch #release`, so
  Linear keeps the PR attached.

Docs-only maintenance may omit a bump marker when it should not create a new
version tag. Say that plainly in the PR body; the workflow only reads semver
bump markers from the PR title.

## Documentation

Keep the README focused on the public introduction and install path. Put
operational detail in [`docs/user-guide.md`](docs/user-guide.md), design intent
in [`DESIGN.md`](DESIGN.md), release process in [`RELEASE.md`](RELEASE.md), and
packaging details in [`PACKAGING.md`](PACKAGING.md).

## Security

Do not commit Plex tokens, account tokens, local config files, or debug logs.
See [`SECURITY.md`](SECURITY.md) for private vulnerability reporting.

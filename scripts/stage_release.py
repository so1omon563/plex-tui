#!/usr/bin/env python3
"""Stage deterministic release metadata updates."""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> Version:
        if not VERSION_RE.fullmatch(value):
            raise ValueError(f"invalid version {value!r}; expected X.Y.Z")
        major, minor, patch = [int(part) for part in value.split(".")]
        return cls(major, minor, patch)

    @classmethod
    def parse_tag(cls, value: str) -> Version | None:
        match = TAG_RE.fullmatch(value)
        if not match:
            return None
        major, minor, patch = [int(part) for part in match.groups()]
        return cls(major, minor, patch)

    def bump(self, kind: str) -> Version:
        if kind == "major":
            return Version(self.major + 1, 0, 0)
        if kind == "minor":
            return Version(self.major, self.minor + 1, 0)
        if kind == "patch":
            return Version(self.major, self.minor, self.patch + 1)
        raise ValueError(f"unsupported bump kind {kind!r}")

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument("--bump", choices=["patch", "minor", "major"], default="patch", help="semver bump from latest tag")
    parser.add_argument("--version", help="explicit X.Y.Z version to stage")
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="release date in YYYY-MM-DD format")
    parser.add_argument("--no-fetch", action="store_true", help="use local tags without fetching origin first")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    try:
        stage_release(root, args.bump, args.version, args.date, fetch_tags=not args.no_fetch)
    except ReleaseStageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


class ReleaseStageError(RuntimeError):
    pass


def stage_release(root: Path, bump: str, explicit_version: str | None, release_date: str, *, fetch_tags: bool) -> None:
    validate_release_date(release_date)
    ensure_clean_worktree(root)
    if fetch_tags:
        run_git(root, ["fetch", "--tags", "origin"])

    latest = latest_tag_version(root)
    if latest is None:
        raise ReleaseStageError("no semver tags found; expected tags like v0.3.31")

    version = Version.parse(explicit_version) if explicit_version else latest.bump(bump)
    if version <= latest:
        raise ReleaseStageError(f"target version {version} must be newer than latest tag v{latest}")
    if tag_exists(root, version):
        raise ReleaseStageError(f"tag v{version} already exists")

    current = Version.parse(read_pyproject_version(root / "pyproject.toml"))
    if current >= version:
        raise ReleaseStageError(f"project metadata is {current}, but target release is {version}")

    ensure_changelog_ready(root / "CHANGELOG.md")
    update_pyproject_version(root / "pyproject.toml", version)
    update_init_version(root / "src/plextui/__init__.py", version)
    update_changelog(root / "CHANGELOG.md", version, release_date)

    print(f"staged release {version}")
    print(f"PR title: Prepare release {version} #{bump} #release")


def validate_release_date(value: str) -> None:
    try:
        dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ReleaseStageError(f"invalid release date {value!r}; expected YYYY-MM-DD") from exc


def ensure_clean_worktree(root: Path) -> None:
    completed = run_git(root, ["status", "--porcelain"], capture=True)
    if completed.stdout.strip():
        raise ReleaseStageError("working tree must be clean before staging a release")


def latest_tag_version(root: Path) -> Version | None:
    completed = run_git(root, ["tag", "--list", "v[0-9]*"], capture=True)
    versions = [version for tag in completed.stdout.splitlines() if (version := Version.parse_tag(tag.strip()))]
    if not versions:
        return None
    return max(versions)


def tag_exists(root: Path, version: Version) -> bool:
    completed = run_git(root, ["tag", "--list", f"v{version}"], capture=True)
    return bool(completed.stdout.strip())


def run_git(root: Path, args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=capture,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        output = ((exc.stdout or "") + (exc.stderr or "")).strip()
        message = f"git {' '.join(args)} failed"
        if output:
            message = f"{message}: {output}"
        raise ReleaseStageError(message) from exc


def read_pyproject_version(path: Path) -> str:
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseStageError(f"read {path}: {exc}") from exc
    version = data.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ReleaseStageError(f"{path} missing project.version")
    return version


def update_pyproject_version(path: Path, version: Version) -> None:
    text = read_text(path)
    updated, count = re.subn(r'(?m)^version = "[^"]+"$', f'version = "{version}"', text, count=1)
    if count != 1:
        raise ReleaseStageError(f"{path} must contain exactly one project version assignment")
    path.write_text(updated, encoding="utf-8")


def update_init_version(path: Path, version: Version) -> None:
    text = read_text(path)
    updated, count = re.subn(r'(?m)^__version__ = "[^"]+"$', f'__version__ = "{version}"', text, count=1)
    if count != 1:
        raise ReleaseStageError(f"{path} must contain exactly one __version__ assignment")
    path.write_text(updated, encoding="utf-8")


def ensure_changelog_ready(path: Path) -> None:
    read_unreleased_entries(path)


def update_changelog(path: Path, version: Version, release_date: str) -> None:
    text, content_start, next_start, unreleased = read_unreleased_entries(path)
    before = text[: text.find("## Unreleased")]
    after = text[next_start:]
    section = f"## Unreleased\n\n## {version} - {release_date}\n\n{unreleased}\n\n"
    path.write_text(before + section + after, encoding="utf-8")


def read_unreleased_entries(path: Path) -> tuple[str, int, int, str]:
    text = read_text(path)
    header = "## Unreleased"
    start = text.find(header)
    if start == -1:
        raise ReleaseStageError("CHANGELOG.md must contain an Unreleased section")

    content_start = start + len(header)
    next_match = re.search(r"(?m)^## \d+\.\d+\.\d+ - \d{4}-\d{2}-\d{2}$", text[content_start:])
    if next_match is None:
        raise ReleaseStageError("CHANGELOG.md must contain a dated release section after Unreleased")

    next_start = content_start + next_match.start()
    unreleased = text[content_start:next_start].strip()
    if not unreleased:
        raise ReleaseStageError("CHANGELOG.md Unreleased section is empty; add release notes before staging")
    return text, content_start, next_start, unreleased


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReleaseStageError(f"read {path}: {exc}") from exc


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Validate local release workflow and version metadata."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    message: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    results = run_checks(root)

    failed = [result for result in results if not result.ok]
    for result in results:
        prefix = "ok" if result.ok else "FAIL"
        print(f"{prefix}: {result.message}")

    return 1 if failed else 0


def run_checks(root: Path) -> list[CheckResult]:
    return [
        check_version_metadata(root),
        check_changelog_version(root),
        check_release_workflow(root),
        check_homebrew_workflow(root),
        check_actionlint(root),
    ]


def check_version_metadata(root: Path) -> CheckResult:
    try:
        pyproject_version = read_pyproject_version(root / "pyproject.toml")
        init_version = read_init_version(root / "src/plextui/__init__.py")
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        return CheckResult(False, f"read version metadata: {exc}")

    versions = {
        "pyproject.toml": pyproject_version,
        "src/plextui/__init__.py": init_version,
    }
    unique_versions = set(versions.values())
    if len(unique_versions) != 1:
        details = ", ".join(f"{name}={version}" for name, version in versions.items())
        return CheckResult(False, f"version metadata is inconsistent: {details}")

    return CheckResult(True, f"version metadata is consistent at {pyproject_version}")


def check_changelog_version(root: Path) -> CheckResult:
    try:
        version = read_pyproject_version(root / "pyproject.toml")
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        return CheckResult(False, f"read changelog metadata: {exc}")

    pattern = re.compile(rf"^## {re.escape(version)} - \d{{4}}-\d{{2}}-\d{{2}}$", re.MULTILINE)
    if not pattern.search(changelog):
        return CheckResult(False, f"CHANGELOG.md has no dated section for {version}")

    return CheckResult(True, f"CHANGELOG.md contains a dated {version} section")


def check_release_workflow(root: Path) -> CheckResult:
    path = root / ".github/workflows/bump.yml"
    try:
        workflow = path.read_text(encoding="utf-8")
    except OSError as exc:
        return CheckResult(False, f"read {path}: {exc}")

    required_snippets = [
        "pull_request:",
        'types: ["closed"]',
        'branches: ["main"]',
        "github.event.pull_request.merged == true",
        "contains(github.event.pull_request.title, '#patch')",
        "contains(github.event.pull_request.title, '#minor')",
        "contains(github.event.pull_request.title, '#major')",
        "contents: write",
        "fetch-depth: 0",
        "uses: so1omon563/custom-semver-bumper@v1",
        "GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}",
        "release_requested: ${{ steps.release-intent.outputs.release_requested }}",
        "id: release-intent",
        "uses: so1omon563/release-creator@v1",
        "tag: ${{ needs.bump-version.outputs.new_tag }}",
        "from-tag: ${{ needs.bump-version.outputs.previous_tag }}",
        "move-major-tag:",
        "move-minor-tag:",
        "uses: pypa/gh-action-pypi-publish@release/v1",
        "id-token: write",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in workflow]
    if missing:
        return CheckResult(False, f"bump.yml is missing required release wiring: {', '.join(missing)}")

    if "publish-pypi:" not in workflow or "create-release" not in workflow:
        return CheckResult(False, "bump.yml must publish PyPI after creating a release")

    return CheckResult(True, "bump.yml contains PR merge tagging, release creation, and PyPI publish wiring")


def check_homebrew_workflow(root: Path) -> CheckResult:
    path = root / ".github/workflows/post-release-homebrew.yml"
    try:
        workflow = path.read_text(encoding="utf-8")
    except OSError as exc:
        return CheckResult(False, f"read {path}: {exc}")

    required_snippets = [
        "Wait for PyPI package availability",
        "python scripts/update_homebrew_formula.py",
        "id: tap-update",
        'HOMEBREW_NO_REQUIRE_TAP_TRUST: "1"',
        "bottle_root_url=\"https://github.com/so1omon563/homebrew-plex-tui/releases/download/${bottle_release}\"",
        "grep -Fq",
        "timeout-minutes: 60",
        "brew config",
        "gh api graphql",
        "gh pr list --repo so1omon563/homebrew-plex-tui --limit 1",
        "brew info so1omon563/plex-tui/plex-tui",
        "Still building Homebrew bottle for plex-tui ${VERSION}",
        "brew install --verbose --build-bottle so1omon563/plex-tui/plex-tui",
        "brew bottle \\",
        "--json \\",
        "--root-url \"$BOTTLE_ROOT_URL\"",
        "scripts/prepare_homebrew_bottle_assets.py",
        "brew bottle --merge --write --no-commit",
        "gh release create \"$BOTTLE_RELEASE\"",
        "gh release upload \"$BOTTLE_RELEASE\"",
        "brew audit --strict --online so1omon563/plex-tui/plex-tui",
        "git ls-remote --exit-code --heads origin \"$branch\"",
        "gh pr list \\",
        "gh pr create \\",
        "gh pr merge \"$pr_url\"",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in workflow]
    if missing:
        return CheckResult(False, f"post-release-homebrew.yml is missing bottle publish wiring: {', '.join(missing)}")

    return CheckResult(True, "post-release-homebrew.yml updates formulae and publishes Homebrew bottles")


def check_actionlint(root: Path) -> CheckResult:
    actionlint = shutil.which("actionlint")
    if actionlint is None:
        return CheckResult(True, "actionlint is not installed; skipped workflow lint")

    workflow_dir = root / ".github/workflows"
    paths = sorted([*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")])
    if not paths:
        return CheckResult(False, ".github/workflows contains no workflow files")

    completed = subprocess.run(
        [actionlint, *[str(path) for path in paths]],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        output = (completed.stdout + completed.stderr).strip()
        return CheckResult(False, f"actionlint failed: {output}")

    return CheckResult(True, f"actionlint passed for {len(paths)} workflow files")


def read_pyproject_version(path: Path) -> str:
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    version = data.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError(f"{path} missing project.version")
    return version


def read_init_version(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', text, re.MULTILINE)
    if not match:
        raise ValueError(f"{path} missing __version__ assignment")
    return match.group(1)


def read_assignment(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(name)}=([^\n]+)$", text, re.MULTILINE)
    if not match:
        raise ValueError(f"{path} missing {name} assignment")
    return match.group(1).strip().strip('"')


def read_srcinfo_value(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"^\s*{re.escape(name)} = ([^\n]+)$", text, re.MULTILINE)
    if not match:
        raise ValueError(f"{path} missing {name} value")
    return match.group(1).strip()


if __name__ == "__main__":
    sys.exit(main())

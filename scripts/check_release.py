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
        check_actionlint(root),
    ]


def check_version_metadata(root: Path) -> CheckResult:
    try:
        pyproject_version = read_pyproject_version(root / "pyproject.toml")
        init_version = read_init_version(root / "src/plextui/__init__.py")
        aur_version = read_assignment(root / "packaging/aur/PKGBUILD", "pkgver")
        srcinfo_version = read_srcinfo_value(root / "packaging/aur/.SRCINFO", "pkgver")
        srcinfo_source = read_srcinfo_value(root / "packaging/aur/.SRCINFO", "source")
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        return CheckResult(False, f"read version metadata: {exc}")

    versions = {
        "pyproject.toml": pyproject_version,
        "src/plextui/__init__.py": init_version,
        "packaging/aur/PKGBUILD": aur_version,
        "packaging/aur/.SRCINFO": srcinfo_version,
    }
    unique_versions = set(versions.values())
    if len(unique_versions) != 1:
        details = ", ".join(f"{name}={version}" for name, version in versions.items())
        return CheckResult(False, f"version metadata is inconsistent: {details}")

    expected_tag = f"v{pyproject_version}"
    if expected_tag not in srcinfo_source:
        return CheckResult(False, f".SRCINFO source does not reference {expected_tag}")

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
        "contents: write",
        "fetch-depth: 0",
        "uses: so1omon563/custom-semver-bumper@v1",
        "GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}",
        "release_requested: ${{ steps.bump.outputs.should_release }}",
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


def check_actionlint(root: Path) -> CheckResult:
    actionlint = shutil.which("actionlint")
    if actionlint is None:
        return CheckResult(True, "actionlint is not installed; skipped workflow lint")

    path = root / ".github/workflows/bump.yml"
    completed = subprocess.run(
        [actionlint, str(path)],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        output = (completed.stdout + completed.stderr).strip()
        return CheckResult(False, f"actionlint failed: {output}")

    return CheckResult(True, "actionlint passed for bump.yml")


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

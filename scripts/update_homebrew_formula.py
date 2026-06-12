#!/usr/bin/env python3
"""Update the Homebrew formula for a released plex-tui version."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("formula", type=Path, help="path to Formula/plex-tui.rb")
    parser.add_argument("version", help="release version without the leading v")
    args = parser.parse_args(argv)

    if not VERSION_RE.fullmatch(args.version):
        print(f"error: version must look like X.Y.Z: {args.version}", file=sys.stderr)
        return 1

    try:
        sdist = fetch_sdist("plex-tui", args.version)
        resources = resolve_resources(args.version)
        update_formula(args.formula, args.version, sdist["url"], sdist["sha256"], resources)
    except (OSError, KeyError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


def fetch_sdist(project: str, version: str) -> dict[str, str]:
    quoted_project = urllib.parse.quote(project)
    quoted_version = urllib.parse.quote(version)
    url = f"https://pypi.org/pypi/{quoted_project}/{quoted_version}/json"
    with urllib.request.urlopen(url, timeout=30) as response:
        data: dict[str, Any] = json.load(response)

    for file_info in data.get("urls", []):
        if file_info.get("packagetype") == "sdist":
            sdist_url = file_info.get("url")
            sha256 = file_info.get("digests", {}).get("sha256")
            if isinstance(sdist_url, str) and isinstance(sha256, str):
                name = data.get("info", {}).get("name", project)
                if not isinstance(name, str):
                    name = project
                return {"name": name, "url": sdist_url, "sha256": sha256}

    raise ValueError(f"PyPI has no sdist for {project} {version}")


def resolve_resources(version: str) -> list[dict[str, str]]:
    with tempfile.NamedTemporaryFile(suffix=".json") as report:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--dry-run",
                "--ignore-installed",
                "--no-cache-dir",
                "--disable-pip-version-check",
                f"--report={report.name}",
                f"plex-tui=={version}",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        report.seek(0)
        data: dict[str, Any] = json.load(report)

    resources: list[dict[str, str]] = []
    for item in data.get("install", []):
        metadata = item.get("metadata", {})
        name = metadata.get("name")
        package_version = metadata.get("version")
        if not isinstance(name, str) or not isinstance(package_version, str):
            continue
        if normalize_name(name) == "plex-tui":
            continue
        resources.append(fetch_sdist(name, package_version))

    return sorted(resources, key=lambda resource: normalize_name(resource["name"]))


def update_formula(
    path: Path,
    version: str,
    url: str,
    sha256: str,
    resources: list[dict[str, str]] | None = None,
) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    updated_url = False
    updated_sha = False
    updated_test = False
    in_resource = False

    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('resource "'):
            in_resource = True
        if stripped == "end":
            in_resource = False

        if not in_resource and not updated_url and stripped.startswith('url "'):
            lines[index] = f'  url "{url}"\n'
            updated_url = True
            continue

        if updated_url and not in_resource and not updated_sha and stripped.startswith('sha256 "'):
            lines[index] = f'  sha256 "{sha256}"\n'
            updated_sha = True
            continue

        if re.search(r'assert_match "plex-tui \d+\.\d+\.\d+"', line):
            lines[index] = re.sub(
                r'assert_match "plex-tui \d+\.\d+\.\d+"',
                f'assert_match "plex-tui {version}"',
                line,
            )
            updated_test = True

    missing = [
        name
        for name, updated in {
            "top-level url": updated_url,
            "top-level sha256": updated_sha,
            "version test": updated_test,
        }.items()
        if not updated
    ]
    if missing:
        raise ValueError(f"formula is missing expected fields: {', '.join(missing)}")

    if resources is not None:
        lines = replace_resources(lines, resources)

    path.write_text("".join(lines), encoding="utf-8")


def replace_resources(lines: list[str], resources: list[dict[str, str]]) -> list[str]:
    first_resource = next(
        (index for index, line in enumerate(lines) if line.strip().startswith('resource "')),
        None,
    )
    install_index = next(
        (index for index, line in enumerate(lines) if line.strip() == "def install"),
        None,
    )
    if first_resource is None or install_index is None or first_resource >= install_index:
        raise ValueError("formula is missing replaceable resource blocks")

    return [
        *lines[:first_resource],
        *format_resources(resources),
        *lines[install_index:],
    ]


def format_resources(resources: list[dict[str, str]]) -> list[str]:
    lines: list[str] = []
    for resource in resources:
        lines.extend(
            [
                f'  resource "{resource["name"]}" do\n',
                f'    url "{resource["url"]}"\n',
                f'    sha256 "{resource["sha256"]}"\n',
                "  end\n",
                "\n",
            ]
        )
    return lines


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


if __name__ == "__main__":
    sys.exit(main())

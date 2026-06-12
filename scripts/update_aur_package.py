#!/usr/bin/env python3
"""Update Arch AUR package metadata for a released plex-tui version."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="release version without the leading v")
    parser.add_argument("sha256", help="sha256 for the GitHub release source archive")
    parser.add_argument(
        "--pkgbuild",
        type=Path,
        default=Path("packaging/aur/PKGBUILD"),
        help="path to the PKGBUILD to update",
    )
    args = parser.parse_args(argv)

    try:
        update_pkgbuild(args.pkgbuild, args.version, args.sha256)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


def update_pkgbuild(path: Path, version: str, sha256: str) -> None:
    if not VERSION_RE.fullmatch(version):
        raise ValueError(f"version must look like X.Y.Z: {version}")
    if not SHA256_RE.fullmatch(sha256):
        raise ValueError(f"sha256 must be 64 lowercase hex characters: {sha256}")

    text = path.read_text(encoding="utf-8")
    text = replace_assignment(text, "pkgver", version)
    text = replace_assignment(text, "pkgrel", "1")
    text = replace_array(text, "sha256sums", sha256)
    path.write_text(text, encoding="utf-8")


def replace_assignment(text: str, name: str, value: str) -> str:
    pattern = re.compile(rf"^{re.escape(name)}=.*$", re.MULTILINE)
    updated, count = pattern.subn(f"{name}={value}", text, count=1)
    if count != 1:
        raise ValueError(f"PKGBUILD is missing {name}")
    return updated


def replace_array(text: str, name: str, value: str) -> str:
    pattern = re.compile(rf'^{re.escape(name)}=\("[^"]+"\)$', re.MULTILINE)
    updated, count = pattern.subn(f'{name}=("{value}")', text, count=1)
    if count != 1:
        raise ValueError(f"PKGBUILD is missing {name}")
    return updated


if __name__ == "__main__":
    sys.exit(main())

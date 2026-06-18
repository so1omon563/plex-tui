#!/usr/bin/env python3
"""Prepare Homebrew bottle files for GitHub Release upload."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bottle_json", type=Path, help="path to brew bottle --json output")
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="directory where upload-ready bottle files should be written",
    )
    args = parser.parse_args(argv)

    try:
        prepared = prepare_assets(args.bottle_json, args.output_dir)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for path in prepared:
        print(path)
    return 0


def prepare_assets(bottle_json: Path, output_dir: Path) -> list[Path]:
    data = json.loads(bottle_json.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)

    prepared: list[Path] = []
    for local_name, upload_name in bottle_files(data):
        source = bottle_json.parent / local_name
        if not source.is_file():
            raise ValueError(f"missing local bottle file: {source}")
        destination = output_dir / upload_name
        shutil.copy2(source, destination)
        prepared.append(destination)

    if not prepared:
        raise ValueError(f"{bottle_json} contains no bottle files")

    return prepared


def bottle_files(data: dict[str, Any]) -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    for formula in data.values():
        bottle = formula.get("bottle", {})
        tags = bottle.get("tags", {})
        for tag in tags.values():
            local_name = tag.get("local_filename")
            upload_name = tag.get("filename")
            if not isinstance(local_name, str) or not isinstance(upload_name, str):
                raise ValueError("bottle JSON tag is missing filename metadata")
            files.append((local_name, upload_name))
    return files


if __name__ == "__main__":
    sys.exit(main())

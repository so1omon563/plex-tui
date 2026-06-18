#!/usr/bin/env python3
"""Measure Homebrew install, update, and test timings for plex-tui."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


DEFAULT_FORMULA = "so1omon563/plex-tui/plex-tui"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--formula",
        default=DEFAULT_FORMULA,
        help=f"Homebrew formula to measure (default: {DEFAULT_FORMULA})",
    )
    parser.add_argument(
        "--fresh-install",
        action="store_true",
        help="uninstall the formula, then measure brew install",
    )
    parser.add_argument(
        "--force-bottle",
        action="store_true",
        help="add --force-bottle when measuring brew install or reinstall",
    )
    parser.add_argument(
        "--reinstall",
        action="store_true",
        help="measure brew reinstall for the current formula",
    )
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="measure brew upgrade; useful for no-op update timing",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="measure brew test after install/update commands",
    )
    parser.add_argument(
        "--allow-auto-update",
        action="store_true",
        help="allow Homebrew auto-update during measured commands",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="optional JSON file for the timing report",
    )
    args = parser.parse_args(argv)

    if shutil.which("brew") is None:
        print("error: brew was not found on PATH", file=sys.stderr)
        return 1

    if not any([args.fresh_install, args.reinstall, args.upgrade, args.test]):
        parser.error("choose at least one measured action")

    env = os.environ.copy()
    if not args.allow_auto_update:
        env["HOMEBREW_NO_AUTO_UPDATE"] = "1"

    results: list[dict[str, Any]] = []
    formula = args.formula

    results.append(run_step(["brew", "--version"], env))
    results.append(run_step(["brew", "info", formula], env))

    if args.fresh_install:
        if is_installed(formula, env):
            results.append(run_step(["brew", "uninstall", "--ignore-dependencies", formula], env))
        results.append(run_step(brew_command("install", formula, args.force_bottle), env))

    if args.reinstall:
        results.append(run_step(brew_command("reinstall", formula, args.force_bottle), env))

    if args.upgrade:
        results.append(run_step(["brew", "upgrade", formula], env))

    if args.test:
        results.append(run_step(["brew", "test", formula], env))

    report = {
        "formula": formula,
        "auto_update": args.allow_auto_update,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "results": results,
    }

    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(report, indent=2))
    return 0 if all(result["returncode"] == 0 for result in results) else 1


def is_installed(formula: str, env: dict[str, str]) -> bool:
    result = subprocess.run(
        ["brew", "list", "--versions", formula],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def brew_command(action: str, formula: str, force_bottle: bool) -> list[str]:
    command = ["brew", action]
    if force_bottle:
        command.append("--force-bottle")
    command.append(formula)
    return command


def run_step(command: list[str], env: dict[str, str]) -> dict[str, Any]:
    started = time.monotonic()
    completed = subprocess.run(
        command,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    elapsed = time.monotonic() - started
    output = completed.stdout.strip()
    return {
        "command": command,
        "elapsed_seconds": round(elapsed, 3),
        "returncode": completed.returncode,
        "output_tail": tail_lines(output, 80),
    }


def tail_lines(output: str, limit: int) -> str:
    lines = output.splitlines()
    return "\n".join(lines[-limit:])


if __name__ == "__main__":
    sys.exit(main())

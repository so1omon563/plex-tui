from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts/prepare_homebrew_bottle_assets.py"
SPEC = importlib.util.spec_from_file_location("prepare_homebrew_bottle_assets", SCRIPT_PATH)
assert SPEC is not None
prepare_homebrew_bottle_assets = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = prepare_homebrew_bottle_assets
SPEC.loader.exec_module(prepare_homebrew_bottle_assets)


def test_prepare_assets_copies_bottle_to_upload_filename(tmp_path):
    bottle_json = tmp_path / "plex-tui--0.4.2.arm64_tahoe.bottle.json"
    local_bottle = tmp_path / "plex-tui--0.4.2.arm64_tahoe.bottle.tar.gz"
    output_dir = tmp_path / "upload"
    local_bottle.write_bytes(b"bottle")
    bottle_json.write_text(
        json.dumps(
            {
                "so1omon563/plex-tui/plex-tui": {
                    "bottle": {
                        "tags": {
                            "arm64_tahoe": {
                                "local_filename": local_bottle.name,
                                "filename": "plex-tui-0.4.2.arm64_tahoe.bottle.tar.gz",
                            }
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    prepared = prepare_homebrew_bottle_assets.prepare_assets(bottle_json, output_dir)

    assert prepared == [output_dir / "plex-tui-0.4.2.arm64_tahoe.bottle.tar.gz"]
    assert prepared[0].read_bytes() == b"bottle"


def test_prepare_assets_requires_local_bottle_file(tmp_path):
    bottle_json = tmp_path / "plex-tui--0.4.2.arm64_tahoe.bottle.json"
    bottle_json.write_text(
        json.dumps(
            {
                "so1omon563/plex-tui/plex-tui": {
                    "bottle": {
                        "tags": {
                            "arm64_tahoe": {
                                "local_filename": "missing.tar.gz",
                                "filename": "plex-tui-0.4.2.arm64_tahoe.bottle.tar.gz",
                            }
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    try:
        prepare_homebrew_bottle_assets.prepare_assets(bottle_json, tmp_path / "upload")
    except ValueError as exc:
        assert "missing local bottle file" in str(exc)
    else:
        raise AssertionError("expected missing bottle file to fail")

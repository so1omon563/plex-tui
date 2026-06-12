from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts/check_release.py"
SPEC = importlib.util.spec_from_file_location("check_release", SCRIPT_PATH)
assert SPEC is not None
check_release = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = check_release
SPEC.loader.exec_module(check_release)

UPDATE_AUR_PATH = Path(__file__).resolve().parents[1] / "scripts/update_aur_package.py"
UPDATE_AUR_SPEC = importlib.util.spec_from_file_location("update_aur_package", UPDATE_AUR_PATH)
assert UPDATE_AUR_SPEC is not None
update_aur_package = importlib.util.module_from_spec(UPDATE_AUR_SPEC)
assert UPDATE_AUR_SPEC.loader is not None
sys.modules[UPDATE_AUR_SPEC.name] = update_aur_package
UPDATE_AUR_SPEC.loader.exec_module(update_aur_package)


def test_release_checks_pass_for_repository():
    root = Path(__file__).resolve().parents[1]

    results = check_release.run_checks(root)

    assert all(result.ok for result in results)


def test_version_metadata_reports_mismatch(tmp_path):
    write_release_fixture(tmp_path, pyproject_version="0.2.1", init_version="0.2.2")

    result = check_release.check_version_metadata(tmp_path)

    assert not result.ok
    assert "version metadata is inconsistent" in result.message


def test_changelog_requires_current_version_section(tmp_path):
    write_release_fixture(tmp_path, pyproject_version="0.2.1", changelog_version="0.2.0")

    result = check_release.check_changelog_version(tmp_path)

    assert not result.ok
    assert "no dated section for 0.2.1" in result.message


def test_release_workflow_requires_bumper_and_release_creator(tmp_path):
    write_release_fixture(tmp_path)
    (tmp_path / ".github/workflows/bump.yml").write_text(
        """
name: Version Bump and Release
on:
  pull_request:
    types: ["closed"]
    branches: ["main"]
jobs:
  bump-version:
    if: github.event.pull_request.merged == true
""",
        encoding="utf-8",
    )

    result = check_release.check_release_workflow(tmp_path)

    assert not result.ok
    assert "custom-semver-bumper" in result.message
    assert "release-creator" in result.message


def test_update_aur_package_updates_pkgbuild(tmp_path):
    pkgbuild = tmp_path / "PKGBUILD"
    pkgbuild.write_text(
        "\n".join(
            [
                "pkgname=plex-tui",
                "pkgver=0.2.1",
                "pkgrel=3",
                'source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")',
                'sha256sums=("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")',
                "",
            ]
        ),
        encoding="utf-8",
    )

    update_aur_package.update_pkgbuild(
        pkgbuild,
        "0.3.0",
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    )

    assert pkgbuild.read_text(encoding="utf-8") == "\n".join(
        [
            "pkgname=plex-tui",
            "pkgver=0.3.0",
            "pkgrel=1",
            'source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")',
            'sha256sums=("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")',
            "",
        ]
    )


def write_release_fixture(
    root: Path,
    *,
    pyproject_version: str = "0.2.1",
    init_version: str = "0.2.1",
    aur_version: str = "0.2.1",
    srcinfo_version: str = "0.2.1",
    changelog_version: str = "0.2.1",
) -> None:
    (root / "src/plextui").mkdir(parents=True)
    (root / "packaging/aur").mkdir(parents=True)
    (root / ".github/workflows").mkdir(parents=True)

    (root / "pyproject.toml").write_text(
        f'[project]\nname = "plex-tui"\nversion = "{pyproject_version}"\n',
        encoding="utf-8",
    )
    (root / "src/plextui/__init__.py").write_text(
        f'__version__ = "{init_version}"\n',
        encoding="utf-8",
    )
    (root / "packaging/aur/PKGBUILD").write_text(
        f"pkgver={aur_version}\n",
        encoding="utf-8",
    )
    (root / "packaging/aur/.SRCINFO").write_text(
        "\n".join(
            [
                "pkgbase = plex-tui",
                f"\tpkgver = {srcinfo_version}",
                f"\tsource = plex-tui-{srcinfo_version}.tar.gz::https://github.com/so1omon563/plex-tui/archive/refs/tags/v{srcinfo_version}.tar.gz",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## {changelog_version} - 2026-06-11\n\n- Entry.\n",
        encoding="utf-8",
    )
    (root / ".github/workflows/bump.yml").write_text(
        (Path(__file__).resolve().parents[1] / ".github/workflows/bump.yml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

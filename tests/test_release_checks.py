from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


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

UPDATE_HOMEBREW_PATH = Path(__file__).resolve().parents[1] / "scripts/update_homebrew_formula.py"
UPDATE_HOMEBREW_SPEC = importlib.util.spec_from_file_location("update_homebrew_formula", UPDATE_HOMEBREW_PATH)
assert UPDATE_HOMEBREW_SPEC is not None
update_homebrew_formula = importlib.util.module_from_spec(UPDATE_HOMEBREW_SPEC)
assert UPDATE_HOMEBREW_SPEC.loader is not None
sys.modules[UPDATE_HOMEBREW_SPEC.name] = update_homebrew_formula
UPDATE_HOMEBREW_SPEC.loader.exec_module(update_homebrew_formula)

STAGE_RELEASE_PATH = Path(__file__).resolve().parents[1] / "scripts/stage_release.py"
STAGE_RELEASE_SPEC = importlib.util.spec_from_file_location("stage_release", STAGE_RELEASE_PATH)
assert STAGE_RELEASE_SPEC is not None
stage_release = importlib.util.module_from_spec(STAGE_RELEASE_SPEC)
assert STAGE_RELEASE_SPEC.loader is not None
sys.modules[STAGE_RELEASE_SPEC.name] = stage_release
STAGE_RELEASE_SPEC.loader.exec_module(stage_release)


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


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Fix playback #patch", (True, False)),
        ("Ship feature #MINOR #RELEASE", (True, True)),
        ("No release markers", (False, False)),
        ("Publish only #ship", (False, False)),
        ("Words #patchwork #minority #major-version #release-notes", (False, False)),
        ("Punctuation (#patch) pre#publish", (False, False)),
    ],
)
def test_pr_title_markers_require_exact_tokens(title, expected):
    assert check_release.parse_pr_title_markers(title) == expected


@pytest.mark.parametrize("title", ["Fix #patch #minor", "Fix #major #major"])
def test_pr_title_markers_reject_multiple_bumps(title):
    with pytest.raises(ValueError, match="exactly one"):
        check_release.parse_pr_title_markers(title)


def test_pr_title_marker_cli_writes_github_outputs(tmp_path):
    output = tmp_path / "github-output"

    result = check_release.main(
        ["--pr-title", "Ship fix #patch #publish", "--github-output", str(output)]
    )

    assert result == 0
    assert output.read_text(encoding="utf-8") == (
        "bump_requested=true\nrelease_requested=true\n"
    )


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


def test_release_workflow_rejects_floating_major_minor_tags(tmp_path):
    write_release_fixture(tmp_path)
    source = Path(".github/workflows/bump.yml").read_text(encoding="utf-8")
    workflow = source.replace(
        "notes-format: grouped",
        'notes-format: grouped\n          move-major-tag: "true"\n          move-minor-tag: "true"',
    )
    (tmp_path / ".github/workflows/bump.yml").write_text(workflow, encoding="utf-8")

    result = check_release.check_release_workflow(tmp_path)

    assert not result.ok
    assert "must not move floating major/minor tags" in result.message


def test_release_workflow_rejects_substring_marker_checks(tmp_path):
    write_release_fixture(tmp_path)
    source = Path(".github/workflows/bump.yml").read_text(encoding="utf-8")
    workflow = source.replace(
        "if: github.event.pull_request.merged == true",
        "if: github.event.pull_request.merged == true && "
        "contains(github.event.pull_request.title, '#patch')",
    )
    (tmp_path / ".github/workflows/bump.yml").write_text(workflow, encoding="utf-8")

    result = check_release.check_release_workflow(tmp_path)

    assert not result.ok
    assert "exact standalone PR-title markers" in result.message


def test_homebrew_workflow_requires_bottle_publish_wiring(tmp_path):
    write_release_fixture(tmp_path)
    (tmp_path / ".github/workflows/post-release-homebrew.yml").write_text(
        """
name: Post-release Homebrew Publish
jobs:
  publish-tap:
    steps:
      - name: Update formula source
        run: python scripts/update_homebrew_formula.py Formula/plex-tui.rb 0.4.2
""",
        encoding="utf-8",
    )

    result = check_release.check_homebrew_workflow(tmp_path)

    assert not result.ok
    assert "bottle publish wiring" in result.message
    assert "brew install --verbose --build-bottle" in result.message


def test_stage_release_updates_version_files_and_moves_changelog(tmp_path):
    write_release_fixture(tmp_path)
    (tmp_path / "CHANGELOG.md").write_text(
        "\n".join(
            [
                "# Changelog",
                "",
                "## Unreleased",
                "",
                "- Improved release staging.",
                "",
                "## 0.2.1 - 2026-06-11",
                "",
                "- Previous entry.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    init_git_fixture(tmp_path, "v0.2.1")

    stage_release.stage_release(tmp_path, "patch", None, "2026-06-15", fetch_tags=False)

    assert check_release.read_pyproject_version(tmp_path / "pyproject.toml") == "0.2.2"
    assert check_release.read_init_version(tmp_path / "src/plextui/__init__.py") == "0.2.2"
    assert (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8") == "\n".join(
        [
            "# Changelog",
            "",
            "## Unreleased",
            "",
            "## 0.2.2 - 2026-06-15",
            "",
            "- Improved release staging.",
            "",
            "## 0.2.1 - 2026-06-11",
            "",
            "- Previous entry.",
            "",
        ]
    )


def test_stage_release_requires_unreleased_changelog_entries(tmp_path):
    write_release_fixture(tmp_path)
    (tmp_path / "CHANGELOG.md").write_text(
        "\n".join(
            [
                "# Changelog",
                "",
                "## Unreleased",
                "",
                "## 0.2.1 - 2026-06-11",
                "",
                "- Previous entry.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    init_git_fixture(tmp_path, "v0.2.1")

    try:
        stage_release.stage_release(tmp_path, "patch", None, "2026-06-15", fetch_tags=False)
    except stage_release.ReleaseStageError as exc:
        assert "Unreleased section is empty" in str(exc)
    else:
        raise AssertionError("expected empty changelog to fail release staging")

    assert check_release.read_pyproject_version(tmp_path / "pyproject.toml") == "0.2.1"


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


def test_update_homebrew_formula_updates_top_level_source_and_test(tmp_path):
    formula = tmp_path / "plex-tui.rb"
    formula.write_text(
        "\n".join(
            [
                "class PlexTui < Formula",
                '  url "https://files.pythonhosted.org/packages/old/plex_tui-0.2.1.tar.gz"',
                '  sha256 "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"',
                "",
                '  resource "requests" do',
                '    url "https://files.pythonhosted.org/packages/requests.tar.gz"',
                '    sha256 "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"',
                "  end",
                "",
                "  test do",
                '    assert_match "plex-tui 0.2.1", shell_output("#{bin}/plex-tui --version")',
                "  end",
                "end",
                "",
            ]
        ),
        encoding="utf-8",
    )

    update_homebrew_formula.update_formula(
        formula,
        "0.3.0",
        "https://files.pythonhosted.org/packages/new/plex_tui-0.3.0.tar.gz",
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    )

    assert formula.read_text(encoding="utf-8") == "\n".join(
        [
            "class PlexTui < Formula",
            '  url "https://files.pythonhosted.org/packages/new/plex_tui-0.3.0.tar.gz"',
            '  sha256 "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"',
            "",
            '  resource "requests" do',
            '    url "https://files.pythonhosted.org/packages/requests.tar.gz"',
            '    sha256 "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"',
            "  end",
            "",
            "  test do",
            '    assert_match "plex-tui 0.3.0", shell_output("#{bin}/plex-tui --version")',
            "  end",
            "end",
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
    (root / ".github/workflows/post-release-homebrew.yml").write_text(
        (Path(__file__).resolve().parents[1] / ".github/workflows/post-release-homebrew.yml").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )


def init_git_fixture(root: Path, tag: str) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=root, check=True, capture_output=True, text=True)
    subprocess.run(["git", "tag", tag], cwd=root, check=True)

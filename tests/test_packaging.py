# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Checks on the packaging files (packaging/, scripts/build_package.py).

They do not build a package (that takes minutes and is done by the Package workflow): they catch
the mistakes that would only show at the next release, like a version that differs between
files or a data folder named in the build recipe that was renamed.
"""

from __future__ import annotations

import importlib.util
import os
import re

import pytest

from tests.conftest import REPO


def _load_build_module():
    path = os.path.join(REPO, "scripts", "build_package.py")
    spec = importlib.util.spec_from_file_location("build_package", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def build():
    return _load_build_module()


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as handle:
        return handle.read()


# ---------------------------------------------------------------- the QR code library (segno)


def test_segno_is_in_every_place_the_program_is_built_or_installed():
    """The labels need ``segno``; without it the QR code is missing (and once a button crashed)."""
    assert re.search(r"^segno\b", read("requirements.txt"), re.MULTILINE)
    assert '"segno' in read("pyproject.toml")  # a ``pip install .`` pulls it in
    assert '"segno"' in read(
        "packaging", "pyinstaller", "ola.spec"
    )  # frozen bundles (deb, rpm, exe)
    assert "check_qr_code" in read("packaging", "pyinstaller", "selftest.py")
    pkgbuild = read("packaging", "arch", "PKGBUILD")  # Arch: the wheel, with its checksum
    assert re.search(r"^_segno_ver=\S+", pkgbuild, re.MULTILINE)
    assert "segno-${_segno_ver}-py3-none-any.whl" in pkgbuild
    wheels = pkgbuild.count('"${_pypi}/')  # every downloaded wheel has a checksum
    sums = re.search(r"sha256sums=\((.*?)\)", pkgbuild, re.S).group(1)
    assert len(re.findall(r"'[0-9a-f]{64}'", sums)) == wheels >= 3


def test_every_runtime_requirement_is_a_dependency_of_the_package():
    deps = read("pyproject.toml")
    for name in ("PyQt6", "pyvisa", "pyvisa-py", "pyserial", "segno", "numpy", "matplotlib"):
        assert f'"{name}' in deps, f"{name} is in requirements.txt but not in pyproject.toml"


# ---------------------------------------------------------------- versions


def test_versions_agree(build):
    """pyproject.toml and frontend/appinfo.json (shown in the program) have the same version."""
    assert build.project_version() == build.appinfo_version()


def test_arch_pkgver_follows_the_project(build):
    match = re.search(r"^pkgver=(\S+)$", read("packaging", "arch", "PKGBUILD"), re.MULTILINE)
    assert match, "pkgver not found in packaging/arch/PKGBUILD"
    assert match.group(1) == build.project_version(), "bump pkgver with the version"


def test_nightly_and_dev_versions(build):
    info = build.compute_version("nightly", sha="0123456789abcdef", date="20260102")
    base = build.project_version()
    assert info["version"] == f"{base}-nightly.20260102.0123456"
    assert info["tag"] == "nightly"
    assert info["prerelease"] == "true"
    assert build.compute_version("dev", sha="abc", date="20260102")["tag"] == ""


def test_release_version_comes_from_the_tag(build):
    base = build.project_version()
    info = build.compute_version("release", tag=f"v{base}")
    assert info["version"] == base
    assert info["prerelease"] == "false"
    assert build.compute_version("release", tag=f"v{base}-rc1")["prerelease"] == "true"


@pytest.mark.parametrize("tag", ["", "0.0.2", "v1", "v99.0.0", "vx.y.z"])
def test_release_refuses_a_wrong_tag(build, tag):
    with pytest.raises(build.BuildError):
        build.compute_version("release", tag=tag)


def test_unknown_kind_is_refused(build):
    with pytest.raises(build.BuildError):
        build.compute_version("weekly")


# ---------------------------------------------------------------- recipe files


def test_build_recipe_points_to_existing_data():
    """Every repository folder the PyInstaller recipe copies still exists."""
    spec = read("packaging", "pyinstaller", "ola.spec")
    for rel in re.findall(r'ROOT / "([\w./-]+)"(?: / "([\w./-]+)")?', spec):
        path = os.path.join(REPO, *[part for part in rel if part])
        # Instruments_LIB may be an empty submodule folder: only check that the folder is there
        top = os.path.join(REPO, rel[0])
        assert os.path.exists(top), f"the recipe names {rel[0]}, which does not exist"
        if rel[0] != "Instruments_LIB" and not path.endswith(".ico"):
            assert os.path.exists(path), f"the recipe names {'/'.join(p for p in rel if p)}"


def test_linux_package_files_exist():
    config = read("packaging", "linux", "nfpm.yaml")
    for rel in re.findall(r"^\s+- src: (\S+)$", config, re.MULTILINE):
        if rel.startswith("/") or rel.startswith("dist-package"):
            continue  # a link target / the output of the bundle step
        assert os.path.exists(os.path.join(REPO, rel)), f"nfpm.yaml names {rel}"


def test_desktop_file_names_the_installed_program():
    desktop = read("packaging", "linux", "open-lab-automation.desktop")
    assert "Exec=open-lab-automation" in desktop
    assert "Icon=open-lab-automation" in desktop


def test_installer_is_built_from_the_script_defines():
    """The Inno Setup script takes everything from the defines of build_package.py."""
    script = read("packaging", "windows", "installer.iss")
    builder = read("scripts", "build_package.py")
    defines = ("AppVersion", "AppVersionNumeric", "BundleDir", "RepoRoot", "OutDir", "OutputBase")
    for define in defines:
        assert "{#" + define + "}" in script, f"installer.iss does not use {define}"
        assert f"/D{define}=" in builder, f"build_package.py does not pass {define}"


def test_workflows_name_existing_scripts():
    workflow = read(".github", "workflows", "package.yml")
    for rel in re.findall(r"(scripts/[\w./-]+\.py|packaging/[\w./-]+)", workflow):
        rel = rel.rstrip(".")  # the end of a sentence
        assert os.path.exists(os.path.join(REPO, rel)), f"package.yml names {rel}"


# ---------------------------------------------------------------- instrument library


@pytest.mark.parametrize(
    "kind, version, expected",
    [
        ("nightly", "0.0.2-nightly.20260101.abc1234", "main"),
        ("dev", "0.0.2-dev.20260101.local", "main"),
        ("release", "0.0.2-alpha.1", "release"),
        ("release", "0.0.2-beta.1", "release"),
        ("release", "0.0.2-rc1", "release"),
        ("release", "0.0.2", "release"),
    ],
)
def test_library_source_by_kind_of_build(build, kind, version, expected):
    assert build.library_source(kind, version) == expected


def test_library_repo_is_read_from_the_submodule_url(build):
    assert build.library_repo() == "mede-erik/Instruments_LIB"


def test_workflow_calls_only_existing_build_steps():
    """Every `build_package.py <step>` of the workflows is a step of the script."""
    script = read("scripts", "build_package.py")
    steps = set(re.findall(r'add_parser\("([\w-]+)"', script))
    for name in (".github/workflows/package.yml", ".github/workflows/ci.yml"):
        for step in re.findall(r"build_package\.py ([\w-]+)", read(*name.split("/"))):
            assert step in steps, f"{name} calls build_package.py {step}, which does not exist"


# ---------------------------------------------------------------- stale runs


def test_cancel_stale_runs_on_closed_pull_request_and_deleted_branch():
    """A closed pull request or a deleted branch cancels its queued and running runs; the
    workflow needs write permission on the actions to do it."""
    workflow = read(".github/workflows/cancel-stale.yml")
    assert "types: [closed]" in workflow
    assert "delete:" in workflow
    assert "actions: write" in workflow
    assert "gh run cancel" in workflow
    # the run of this workflow is never cancelled by itself
    assert "SELF: ${{ github.run_id }}" in workflow


def test_nightly_is_built_only_for_the_newest_commit_of_main():
    """The packages of an older commit of main are not built, and the tests of the same run
    wait for that decision."""
    workflow = read(".github/workflows/package.yml")
    assert "steps.fresh.outputs.current" in workflow
    assert "needs.meta.outputs.current != 'false'" in workflow
    assert "commits/main" in workflow


# ---------------------------------------------------------------- Windows installer


def read_installer():
    path = os.path.join(REPO, "packaging", "windows", "installer.iss")
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


# Inno Setup language name -> locale file of frontend/lang
INSTALLER_LANGUAGES = {
    "english": "en",
    "italian": "it",
    "french": "fr",
    "spanish": "es",
    "german": "de",
}


def test_installer_languages_are_the_locales_of_the_program():
    """The installer speaks the languages of frontend/lang: adding a locale file makes this fail
    until the installer has the language too."""
    names = re.findall(r'^Name: "(\w+)"; MessagesFile:', read_installer(), re.MULTILINE)
    assert set(names) <= set(INSTALLER_LANGUAGES), f"unknown language in installer.iss: {names}"
    codes = {INSTALLER_LANGUAGES[name] for name in names}
    locales = {
        os.path.splitext(name)[0]
        for name in os.listdir(os.path.join(REPO, "frontend", "lang"))
        if name.endswith(".json")
    }
    assert codes == locales, f"installer: {sorted(codes)}, frontend/lang: {sorted(locales)}"


def test_installer_has_every_message_in_every_language():
    """A message of the existing-installation page in English exists in every language."""
    script = read_installer()
    section = script.split("[CustomMessages]", 1)[1].split("\n[", 1)[0]
    english = set(re.findall(r"^(\w+)=", section, re.MULTILINE))
    assert english, "no custom messages found"
    for language in INSTALLER_LANGUAGES:
        if language == "english":
            continue
        found = set(re.findall(rf"^{language}\.(\w+)=", section, re.MULTILINE))
        assert found == english, f"{language}: missing {english - found}, unknown {found - english}"


def test_installer_guid_of_the_code_equals_the_app_id():
    """The uninstall entry is looked up under the AppId: the two copies of the GUID must agree."""
    script = read_installer()
    app_id = re.search(r"^AppId=\{(\{[0-9A-F-]{36}\})", script, re.MULTILINE)
    code_id = re.search(r"AppGuid = '(\{[0-9A-F-]{36}\})'", script)
    assert app_id and code_id, "AppId or AppGuid not found in installer.iss"
    assert app_id.group(1) == code_id.group(1)


def test_installer_has_a_windows_requirement_and_the_update_choice():
    script = read_installer()
    assert re.search(r"^MinVersion=10\.0\.\d+$", script, re.MULTILINE)
    assert "{param:MODE|}" in script  # a silent run chooses with /MODE=UPDATE or /MODE=REPAIR


def test_the_windows_job_tests_update_and_repair():
    workflow = read(".github", "workflows", "package.yml")
    assert "/MODE=UPDATE" in workflow and "/MODE=REPAIR" in workflow


def test_skipping_the_tests_is_only_for_manual_runs_and_never_publishes():
    """The input skip_tests lets a manual run build the packages without the tests; a push or a
    tag always runs them, and the publish job still needs a push."""
    workflow = read(".github", "workflows", "package.yml")
    assert "skip_tests:" in workflow
    assert "!inputs.skip_tests" in workflow  # the tests job is skipped only by the input
    assert "needs.tests.result == 'skipped' && inputs.skip_tests" in workflow
    publish = workflow.split("\n  publish:", 1)[1]
    assert "github.event_name == 'push'" in publish.split("steps:", 1)[0]


def test_update_waits_for_the_old_uninstaller_to_finish():
    """The uninstaller of Inno Setup starts a second copy and ends at once: Setup waits until the
    uninstaller file is gone, or the old uninstaller could delete the new files."""
    script = read_installer()
    assert "while FileExists(PreviousUninstaller)" in script
    assert "Sleep(" in script

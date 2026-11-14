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

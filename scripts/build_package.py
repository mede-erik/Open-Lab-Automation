#!/usr/bin/env python3
# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Build the distributable packages of Open Lab Automation (the same script on Windows and Linux).

Steps (each one is a sub-command; the CI runs them in this order, see docs/CI.md and
packaging/README.md):

    version     print the version of the package for a kind of build (nightly, release, dev)
    bundle      freeze the program with PyInstaller into dist-package/OpenLabAutomation/ and run
                its self-test (optionally building and including the Rust transport first)
    archive     zip (Windows) or tar.gz (Linux) of the bundle        -> dist-release/
    installer   Windows installer (Inno Setup)                        -> dist-release/
    linux       .deb and .rpm of the bundle (nfpm)                    -> dist-release/

Example, Linux, local build of a development package:

    git submodule update --init
    pip install -r requirements.txt -r packaging/requirements.txt
    python scripts/build_package.py version --kind dev        # prints version=...
    python scripts/build_package.py bundle --native
    python scripts/build_package.py archive --version <the version printed above>
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "pyinstaller" / "ola.spec"
BUNDLE_PARENT = ROOT / "dist-package"
BUNDLE = BUNDLE_PARENT / "OpenLabAutomation"
WORK = ROOT / "build-package"
RELEASE_DIR = ROOT / "dist-release"
IS_WINDOWS = os.name == "nt"
EXE_SUFFIX = ".exe" if IS_WINDOWS else ""
PACKAGE_NAME = "open-lab-automation"

KINDS = ("release", "nightly", "dev")


class BuildError(Exception):
    """A step cannot go on; the message says what to do."""


# ------------------------------------------------------------------ versions


def project_version() -> str:
    """Version in pyproject.toml, the single source of truth."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise BuildError("version not found in pyproject.toml")
    return match.group(1)


def appinfo_version() -> str:
    """Version shown by the program (frontend/appinfo.json)."""
    import json

    with open(ROOT / "frontend" / "appinfo.json", encoding="utf-8") as handle:
        return str(json.load(handle)["version"])


def check_versions() -> str:
    """pyproject.toml and appinfo.json must agree; returns the version."""
    base, shown = project_version(), appinfo_version()
    if base != shown:
        raise BuildError(
            f"version mismatch: pyproject.toml says {base}, frontend/appinfo.json says {shown}"
        )
    return base


def compute_version(kind: str, tag: str = "", sha: str = "", date: str = "") -> Dict[str, str]:
    """Version of the package for a kind of build.

    release  X.Y.Z, from the tag vX.Y.Z (the tag must agree with pyproject.toml);
             a tag vX.Y.Z-rc1 gives a pre-release
    nightly  X.Y.Z-nightly.YYYYMMDD.<sha>   build of main, replaced by the next commit
    dev      X.Y.Z-dev.YYYYMMDD.<sha>       manual build, never published

    The pre-release form sorts BEFORE X.Y.Z for dpkg (nfpm writes it with a tilde) and rpm, so
    bump pyproject.toml to the next version right after a release, or nightly builds would look
    older than the release.
    """
    if kind not in KINDS:
        raise BuildError(f"unknown kind '{kind}', use one of {', '.join(KINDS)}")
    base = check_versions()
    short = (sha or "local")[:7]
    stamp = date or datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    if kind == "release":
        if not re.fullmatch(r"v\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?", tag or ""):
            raise BuildError(f"a release needs a tag like v{base}, got '{tag}'")
        version = tag[1:]
        if version != base and not version.startswith(base + "-"):
            raise BuildError(f"tag {tag} does not match the version {base} in pyproject.toml")
    else:
        version = f"{base}-{kind}.{stamp}.{short}"
    return {
        "version": version,
        "base": base,
        "kind": kind,
        "tag": tag if kind == "release" else ("nightly" if kind == "nightly" else ""),
        "prerelease": "true" if "-" in version else "false",
    }


# ------------------------------------------------------------------ instrument library

LIBRARY_MAIN = "main"        # the newest commit of the library's main branch
LIBRARY_RELEASE = "release"  # the latest published release of the library (not a pre-release)


def library_source(kind: str, version: str) -> str:
    """Which instrument library a package takes.

    Release builds (alpha, beta, release candidates, final) take the latest published release of
    the library, so that they only get a library that has been released. nightly and dev builds
    take the newest commit of the library's main branch, for testing the library work in progress.
    """
    if kind == "release":
        return LIBRARY_RELEASE
    return LIBRARY_MAIN


def library_repo() -> str:
    """``owner/name`` of the instrument library, from the submodule URL in .gitmodules (the one
    place where the library's address is written)."""
    text = (ROOT / ".gitmodules").read_text(encoding="utf-8")
    match = re.search(r"url\s*=\s*https://github\.com/([^/\s]+/[^/\s]+?)(?:\.git)?\s*$", text, re.M)
    if not match:
        raise BuildError("the URL of the instrument library is not in .gitmodules")
    return match.group(1)


def gh_api(path: str, jq: str) -> str:
    """One value of the GitHub API, read with the gh command (GH_TOKEN in the environment)."""
    result = subprocess.run(
        ["gh", "api", path, "--jq", jq], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise BuildError(f"gh api {path} failed: {result.stderr.strip() or 'no output'}")
    return result.stdout.strip()


def resolve_library(source: str) -> Dict[str, str]:
    """Commit and a readable label of the instrument library for a source (see library_source)."""
    repo = library_repo()
    if source == LIBRARY_MAIN:
        sha = gh_api(f"repos/{repo}/commits/main", ".sha")
        label = f"main, {sha[:7]} (newest commit)"
    else:
        tag = gh_api(f"repos/{repo}/releases/latest", ".tag_name")
        sha = gh_api(f"repos/{repo}/commits/{tag}", ".sha")
        label = f"{tag}, {sha[:7]} (latest release)"
    return {"source": source, "sha": sha, "label": label}


# ------------------------------------------------------------------ helpers


def run(command: List[str], cwd: Optional[Path] = None, env: Optional[dict] = None) -> None:
    """Run a command, showing it; a failure stops the build."""
    print("+", " ".join(str(part) for part in command), flush=True)
    result = subprocess.run([str(part) for part in command], cwd=cwd, env=env, check=False)
    if result.returncode != 0:
        raise BuildError(f"command failed with code {result.returncode}: {command[0]}")


def platform_label() -> str:
    """Name of the platform in the file names."""
    return "windows-x64" if IS_WINDOWS else "linux-x64"


def need_bundle() -> None:
    if not (BUNDLE / f"OpenLabAutomation{EXE_SUFFIX}").is_file():
        raise BuildError("the bundle is missing: run the 'bundle' step first")


# ------------------------------------------------------------------ steps


def cmd_version(args: argparse.Namespace) -> None:
    info = compute_version(args.kind, args.tag, args.sha, args.date)
    info["library"] = library_source(info["kind"], info["version"])
    for key, value in info.items():
        print(f"{key}={value}")


def cmd_library(args: argparse.Namespace) -> None:
    """Print which instrument library the package takes, as key=value lines (GITHUB_OUTPUT)."""
    info = resolve_library(library_source(args.kind, args.version))
    print(f"library_source={info['source']}")
    print(f"library_sha={info['sha']}")
    print(f"library_label={info['label']}")


def cmd_checkout_library(args: argparse.Namespace) -> None:
    """Put the instrument library at the commit chosen for this package (Instruments_LIB)."""
    library = ROOT / "Instruments_LIB"
    run(["git", "-C", library, "fetch", "--depth=1", "origin", args.sha])
    run(["git", "-C", library, "checkout", "--detach", "FETCH_HEAD"])
    if not (library / "instruments_lib.json").is_file():
        raise BuildError("the library checked out has no instruments_lib.json")
    print(f"Instrument library at {args.sha}")


def build_native() -> None:
    """Build the Rust transport (ola_native) and install it, so the bundle includes it."""
    wheels = ROOT / "native" / "target" / "wheels"
    shutil.rmtree(wheels, ignore_errors=True)
    run([sys.executable, "-m", "maturin", "build", "--release", "--locked"], cwd=ROOT / "native")
    found = sorted(wheels.glob("ola_native-*.whl"))
    if not found:
        raise BuildError("maturin did not produce a wheel")
    run([sys.executable, "-m", "pip", "install", "--force-reinstall", "--no-deps", found[-1]])


def cmd_bundle(args: argparse.Namespace) -> None:
    check_versions()
    if not (ROOT / "Instruments_LIB" / "instruments_lib.json").is_file():
        raise BuildError("Instruments_LIB is empty: run  git submodule update --init")
    if args.native:
        build_native()
    shutil.rmtree(BUNDLE_PARENT, ignore_errors=True)
    shutil.rmtree(WORK, ignore_errors=True)
    run(
        [
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--distpath", BUNDLE_PARENT, "--workpath", WORK, SPEC,
        ],
        cwd=ROOT,
    )
    need_bundle()
    selftest = [BUNDLE / f"ola-selftest{EXE_SUFFIX}"]
    if args.native:
        selftest.append("--expect-native")
    # Run from a neutral folder: the bundle must not depend on the repository around it
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    run(selftest, cwd=BUNDLE_PARENT, env=env)
    print(f"Bundle ready: {BUNDLE}")


def cmd_archive(args: argparse.Namespace) -> None:
    need_bundle()
    RELEASE_DIR.mkdir(exist_ok=True)
    stem = f"OpenLabAutomation-{args.version}-{platform_label()}"
    if IS_WINDOWS:
        target = RELEASE_DIR / f"{stem}.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(BUNDLE.rglob("*")):
                if path.is_file():
                    archive.write(path, Path("OpenLabAutomation") / path.relative_to(BUNDLE))
    else:
        target = RELEASE_DIR / f"{stem}.tar.gz"
        with tarfile.open(target, "w:gz", compresslevel=9) as archive:
            archive.add(BUNDLE, arcname="OpenLabAutomation")
    print(f"Written {target}")


def cmd_installer(args: argparse.Namespace) -> None:
    if not IS_WINDOWS:
        raise BuildError("the installer is built on Windows (Inno Setup)")
    need_bundle()
    RELEASE_DIR.mkdir(exist_ok=True)
    iscc = args.iscc or shutil.which("ISCC") or shutil.which("iscc")
    if not iscc:
        for folder in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
            candidate = Path(folder or "") / "Inno Setup 6" / "ISCC.exe"
            if folder and candidate.is_file():
                iscc = str(candidate)
                break
    if not iscc:
        raise BuildError("Inno Setup (ISCC.exe) not found: install it, or pass --iscc")
    numeric = re.match(r"\d+\.\d+\.\d+", args.version)
    if not numeric:
        raise BuildError(f"cannot read a number X.Y.Z from the version '{args.version}'")
    base = f"OpenLabAutomation-{args.version}-{platform_label()}-setup"
    run(
        [
            iscc,
            f"/DAppVersion={args.version}",
            f"/DAppVersionNumeric={numeric.group(0)}.0",
            f"/DBundleDir={BUNDLE}",
            f"/DRepoRoot={ROOT}",
            f"/DOutDir={RELEASE_DIR}",
            f"/DOutputBase={base}",
            ROOT / "packaging" / "windows" / "installer.iss",
        ]
    )
    print(f"Written {RELEASE_DIR / (base + '.exe')}")


def cmd_linux(args: argparse.Namespace) -> None:
    if IS_WINDOWS:
        raise BuildError(".deb and .rpm are built on Linux")
    need_bundle()
    RELEASE_DIR.mkdir(exist_ok=True)
    nfpm = args.nfpm or shutil.which("nfpm")
    if not nfpm:
        raise BuildError("nfpm not found: install it, or pass --nfpm (see packaging/README.md)")
    # nfpm reads the version from the environment and the files from paths relative to the
    # repository root (packaging/linux/nfpm.yaml)
    env = dict(os.environ, OLA_VERSION=args.version)
    config = ROOT / "packaging" / "linux" / "nfpm.yaml"
    names = {
        "deb": f"{PACKAGE_NAME}_{args.version}_amd64.deb",
        "rpm": f"{PACKAGE_NAME}-{args.version}.x86_64.rpm",
    }
    for packager, name in names.items():
        run([nfpm, "package", "--config", config, "--packager", packager,
             "--target", RELEASE_DIR / name], cwd=ROOT, env=env)
        print(f"Written {RELEASE_DIR / name}")


# ------------------------------------------------------------------ command line


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    steps = top.add_subparsers(dest="step", required=True)

    sub = steps.add_parser("version", help="print the version of a kind of build")
    sub.add_argument("--kind", choices=KINDS, required=True)
    sub.add_argument("--tag", default="", help="the tag, for --kind release (vX.Y.Z)")
    sub.add_argument("--sha", default=os.environ.get("GITHUB_SHA", ""), help="commit")
    sub.add_argument("--date", default="", help="YYYYMMDD (default: today, UTC)")
    sub.set_defaults(func=cmd_version)

    sub = steps.add_parser("library", help="which instrument library a package takes")
    sub.add_argument("--kind", choices=KINDS, required=True)
    sub.add_argument("--version", required=True)
    sub.set_defaults(func=cmd_library)

    sub = steps.add_parser("checkout-library", help="library commit into Instruments_LIB")
    sub.add_argument("--sha", required=True, help="commit of the library (from the library step)")
    sub.set_defaults(func=cmd_checkout_library)

    sub = steps.add_parser("bundle", help="freeze the program and run its self-test")
    sub.add_argument("--native", action="store_true", help="build and include the Rust transport")
    sub.set_defaults(func=cmd_bundle)

    sub = steps.add_parser("archive", help="zip (Windows) or tar.gz (Linux) of the bundle")
    sub.add_argument("--version", required=True)
    sub.set_defaults(func=cmd_archive)

    sub = steps.add_parser("installer", help="Windows installer (Inno Setup)")
    sub.add_argument("--version", required=True)
    sub.add_argument("--iscc", default="", help="path of ISCC.exe")
    sub.set_defaults(func=cmd_installer)

    sub = steps.add_parser("linux", help=".deb and .rpm (nfpm)")
    sub.add_argument("--version", required=True)
    sub.add_argument("--nfpm", default="", help="path of the nfpm program")
    sub.set_defaults(func=cmd_linux)
    return top


def main(argv: Optional[List[str]] = None) -> int:
    args = parser().parse_args(argv)
    try:
        args.func(args)
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

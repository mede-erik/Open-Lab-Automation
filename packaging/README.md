# Packaging

How Open Lab Automation becomes something a user can install, and how the CI publishes it.

## What is published, and where

Packages are **not** kept in the repository (only the recipes are). They are built by the
workflow `.github/workflows/package.yml` and published as GitHub releases:

| When | Release | What it is |
|---|---|---|
| every commit on `main` | **`nightly`** (pre-release, replaced at each commit) | the newest `main`, for testing; its tag `nightly` always points at the built commit |
| a tag `vX.Y.Z` is pushed | **`vX.Y.Z`** (fixed, never replaced) | a real release; `vX.Y.Z-rc1` gives a pre-release |
| manual run (*Actions → Package → Run workflow*) | none | the same packages as downloadable artifacts of the run (14 days), nothing is published |

Pull requests and the other branches build nothing: they only run the tests (`ci.yml`).

Files of a release (the version is `X.Y.Z`, or `X.Y.Z-nightly.YYYYMMDD.<commit>` for nightly):

| File | For |
|---|---|
| `OpenLabAutomation-<version>-windows-x64-setup.exe` | Windows installer (Inno Setup): per-user by default, "all users" on request |
| `OpenLabAutomation-<version>-windows-x64.zip` | Windows, no installation: unzip and run `OpenLabAutomation.exe` |
| `open-lab-automation_<version>_amd64.deb` | Debian, Ubuntu and derivatives |
| `open-lab-automation-<version>.x86_64.rpm` | Fedora, openSUSE, RHEL and derivatives |
| `OpenLabAutomation-<version>-linux-x64.tar.gz` | Linux, no installation: unpack and run `OpenLabAutomation/OpenLabAutomation` |
| `SHA256SUMS` | checksums of all the files above |

**Arch Linux** has no binary file: `packaging/arch/PKGBUILD` is the package builder.
`cd packaging/arch && makepkg -si` builds the release `v<pkgver>` from the sources and installs it
with the system Python packages. (GitHub's automatic "Source code" archives of a release lack the
`Instruments_LIB` submodule, which is why the PKGBUILD clones with git and checks the library out.)

The Windows and Linux packages are **self-contained**: Python, Qt, numpy, matplotlib and the Rust
transport are inside. They are frozen with PyInstaller; the `.deb`/`.rpm` install the folder in
`/opt/open-lab-automation` and add the menu entry and `/usr/bin/open-lab-automation`.

## Layout of this folder

```
packaging/
  README.md                this file
  requirements.txt         build tools (PyInstaller, maturin), pinned
  pyinstaller/ola.spec     the recipe: what goes into the frozen folder
  pyinstaller/selftest.py  program `ola-selftest` shipped in the bundle (see below)
  windows/installer.iss    Inno Setup script
  linux/nfpm.yaml          .deb and .rpm (nfpm): files, dependencies
  linux/*.desktop          menu entry
  arch/PKGBUILD            package builder for Arch Linux
  arch/ci-check.sh         what the CI does to check the PKGBUILD
scripts/build_package.py   the one script that runs the steps (same on Windows and Linux)
```

## The one rule of the recipe

The program finds its data with paths relative to its own files (`Instruments_LIB/` next to
`frontend/` and `ola/`, `frontend/lang/`, `ola/modules/`). Inside a frozen bundle those files are
under the same relative paths, so `ola.spec` copies every data folder **to the same relative path
it has in the repository**, and the code has no special case for "frozen". If you move a data
folder in the repository, change it in `ola.spec` too; if you add a new data folder, add it there.
`tests/test_packaging.py` checks that the folders the recipe names exist.

`Instruments_LIB/docs` (hundreds of MB of manufacturer PDFs) is not packaged: nothing reads it.

## The self-test

`ola-selftest` (a console program in the bundle) checks what unit tests cannot: that the **frozen**
program holds everything it reads at run time. It imports every module, loads the instrument
library, the translations and the built-in measurement modules, and opens the main window
offscreen. The CI runs it on the bundle, on the installed Windows program, and inside clean
Ubuntu 22.04, Debian 12 and Fedora containers after installing the `.deb`/`.rpm`: that is what
proves the lists of dependencies in `nfpm.yaml`. It also helps a user: if the program does not
start, `ola-selftest` says what is missing.

## Building a package by hand

```bash
git submodule update --init
pip install -r requirements.txt -r packaging/requirements.txt
python scripts/build_package.py bundle --native     # needs Rust; leave out --native for the Python transport
python scripts/build_package.py version --kind dev  # prints version=0.0.2-dev.<date>.local ...
python scripts/build_package.py archive --version 0.0.2-dev.<date>.local
```

Results: `dist-package/OpenLabAutomation/` (the frozen program) and `dist-release/` (the files). On
Windows add `installer` (needs Inno Setup 6.3+); on Linux `linux` makes the `.deb`/`.rpm` (needs
[nfpm](https://nfpm.goreleaser.com), the CI uses v2.43.0). Each OS builds its own packages: PyInstaller does not
cross-compile. Linux packages are built on the oldest runner image (Ubuntu 22.04) so that they run
on distributions with an older glibc.

## Making a release

1. Set the version in **both** `pyproject.toml` and `frontend/appinfo.json` (the build refuses if
   they differ) and `pkgver` in `packaging/arch/PKGBUILD`; `tests/test_packaging.py` checks it.
2. Merge to `main`, wait for the green *Package* run of that commit.
3. `git tag vX.Y.Z && git push origin vX.Y.Z`. The workflow tests the tag again, builds, and creates the
   release `vX.Y.Z` with generated notes. A tag that does not match `pyproject.toml` fails at once.
4. Bump the version in the three places to the next one. Otherwise the nightly builds are named
   `X.Y.Z-nightly...`, which package managers consider **older** than the release `X.Y.Z`.

## Things to know

- **Not signed.** Windows SmartScreen will warn about the installer, and some antivirus programs
  are suspicious of PyInstaller programs. Signing needs a certificate (a decision for the
  maintainer); the build has one place to add it, after the `installer` step.
- **No icon of its own yet.** The menu entry uses `frontend/assets/icons/oscilloscope.png` and the
  Windows program has the default icon. To add one: put `app.ico` in `packaging/windows/` (the recipe
  uses it if present), and replace the PNG in `nfpm.yaml`/`PKGBUILD` with a larger one.
- **Installer language:** English only for now.
- **The `arch` job of the workflow is not blocking** (`continue-on-error`) until it has been seen
  green once. Remove that line from `package.yml` after the first green run.
- **Files the program writes** go to the user's home or the project folder (logs in the project,
  settings in `%APPDATA%` / `~/.config`), never to the installation folder, so installing in
  `Program Files` or `/opt` (read-only for the user) is fine.
- **Hardware drivers are not packaged:** NI-VISA or other vendor drivers, linux-gpib, the
  WaveForms runtime of Digilent. The program uses `pyvisa-py` (pure Python) and talks to the
  adapters it supports through their own drivers if they are installed (see `docs/gpib-adapters.md`).

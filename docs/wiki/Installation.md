# Installation

There are two ways: install a **package**, or run from the **source**.

## Option 1: a package

Packages are built by the repository's CI and published as GitHub releases on [the Releases page](https://github.com/mede-erik/Open-Lab-Automation/releases):

| Release | What it is |
|---|---|
| `nightly` (pre-release) | the newest `main`, replaced at every commit; for testing |
| `vX.Y.Z` | a fixed release, never replaced; a tag such as `vX.Y.Z-rc1` gives a pre-release |

Files of a release:

| File | For |
|---|---|
| `OpenLabAutomation-<version>-windows-x64-setup.exe` | Windows installer (per user by default, all users on request) |
| `OpenLabAutomation-<version>-windows-x64.zip` | Windows, no installation: unzip and run `OpenLabAutomation.exe` |
| `open-lab-automation_<version>_amd64.deb` | Debian, Ubuntu and derivatives |
| `open-lab-automation-<version>.x86_64.rpm` | Fedora, openSUSE, RHEL and derivatives |
| `OpenLabAutomation-<version>-linux-x64.tar.gz` | Linux, no installation |
| `SHA256SUMS` | checksums of the files above |

Arch Linux has no binary file: `cd packaging/arch && makepkg -si` builds the release from the sources.

Notes: the Windows installer is English only and not signed. The packages have not yet been tested on a clean machine (see [Software test status](Software-Test-Status)). Details: [`packaging/README.md`](https://github.com/mede-erik/Open-Lab-Automation/blob/main/packaging/README.md).

## Option 2: from the source

Requirements: Python 3.10 or newer, PyQt6 and the packages in `requirements.txt`, Git.

```bash
git clone --recurse-submodules https://github.com/mede-erik/Open-Lab-Automation.git
cd Open-Lab-Automation
pip install -r requirements.txt
python frontend/launcher.py
```

Already cloned without submodules?

```bash
git submodule update --init
```

Without the submodule the GUI starts, but no instrument can be configured and the library tests fail. `python -m frontend.main` also works from the repository root and is handy to debug imports.

### Optional: native transport

The transport works without it (pure Python, same behaviour, a little slower). To build the Rust module:

```bash
pip install maturin
cd native && maturin build --release && pip install target/wheels/ola_native-*.whl
```

## Optional: a VISA library

USB-TMC, GPIB and VXI-11 instruments go through VISA: NI-VISA, or the pure-Python `pyvisa-py` that `requirements.txt` installs.

## Platform notes

- **Linux, GPIB**: the Keysight 82357B and other adapters need their driver. *Tools > GPIB adapters* checks the driver and can run the Linux set-up through `pkexec`. See [GPIB adapters](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/gpib-adapters.md).
- **Linux, USB-TMC**: if the instrument is not listed, see [Troubleshooting](Troubleshooting).
- **Serial (RS-232)**: the port can be given as a number, as `COM3` or as `/dev/ttyUSB0`. Baud rate and framing come from the library and can be changed per instrument.
- **Windows**: the instrument shell needs `pyreadline3` for command history (listed in `requirements.txt`).

Next: [Quick start](Quick-Start).

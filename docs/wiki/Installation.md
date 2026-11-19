# Installation

## Requirements

- Python 3.10 or newer
- PyQt6 and the packages in `requirements.txt`
- Git (the instrument library is a submodule)
- Optional: a Rust toolchain (maturin) for the fast native transport; a C compiler for the legacy backend
- Optional: a VISA library (NI-VISA or the pure-Python `pyvisa-py`) for USB-TMC, GPIB and VXI-11 instruments

## 1. Clone with the instrument library

```bash
git clone --recurse-submodules https://github.com/mede-erik/Open-Lab-Automation.git
cd Open-Lab-Automation
```

Already cloned without submodules?

```bash
git submodule update --init
```

Without the submodule the GUI starts, but no instrument can be configured and the library tests fail.

## 2. Python dependencies

```bash
pip install -r requirements.txt
```

## 3. Run

```bash
python frontend/launcher.py
```

The launcher sets up the paths. `python -m frontend.main` also works from the repository root and is handy to debug imports.

## 4. Optional: native transport

The transport works without it (pure Python, same behaviour, a little slower). To build the Rust module:

```bash
pip install maturin
cd native && maturin build --release && pip install target/wheels/ola_native-*.whl
```

## 5. Optional: legacy C backend

Only needed by the legacy code path that the GUI no longer uses:

```bash
bash backend/build.sh          # Linux / macOS: backend/libbackend.so
```

On Windows, `backend/build.bat` builds `backend/backend.dll` (MinGW).

## Platform notes

- **Linux, GPIB**: the Keysight 82357B and other adapters need their driver. *Tools > GPIB adapters* checks the driver and can run the Linux set-up through `pkexec`. See [GPIB adapters](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/gpib-adapters.md).
- **Serial (RS-232)**: the port can be given as a number, as `COM3` or as `/dev/ttyUSB0`. Baud rate and framing come from the library and can be changed per instrument.
- **Windows**: the instrument shell needs `pyreadline3` for command history (listed in `requirements.txt`).

Next: [Quick start](Quick-Start).

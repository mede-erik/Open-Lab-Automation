# Contributing

Contributions are welcome: issues, feature requests, pull requests.

## Good first contributions

- **Test an instrument** of the library on real hardware and report it (see the library's `TESTING.md`). Most models are still experimental.
- **Add a model** to the instrument library (the library repository has its own contribution notes).
- **Improve a translation** in `frontend/lang/*.json`, checked by `scripts/check_translations.py`.
- **Write a measurement module** ([guide](Writing-a-Measurement-Module)).
- **Improve the documentation**: the repository `docs/` folder is the reference, these wiki pages are the entry point.

## Before you open a pull request

```bash
QT_QPA_PLATFORM=offscreen pytest
python scripts/check_translations.py
flake8 ola tests scripts
```

- Keep the change to what the issue or feature needs.
- A new user-visible string needs a key in all five language files.
- A new module or a changed behaviour needs its guide updated in `docs/`.
- An error needs its code documented in `ERROR_CODES.md`.

## Reporting a problem

Include the error code shown in the message (for example `[TRN-003]`), your operating system, the instrument model and the interface (LAN, USB, GPIB, serial). For an instrument problem, the output of `scripts/instrument_shell.py` is the most useful thing to attach.

## Licence

OLA is under the GNU General Public License v3. Contributions are released under the same licence.

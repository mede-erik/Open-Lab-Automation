# GPIB adapters (*Tools > GPIB adapters*)

A tool to set up the adapters that connect GPIB (IEEE 488) instruments to the computer, check that
their driver works, find the instruments on the bus and use them in a project. It is not tied to one
model: several adapters can be configured together (for example a Keysight 82357B on `GPIB0` and a
Prologix on a serial port), each with its own name.

| Model | Family | Instrument address in the project |
|---|---|---|
| Keysight 82357B, Agilent/Keysight 82357A | VISA board | `GPIB<board>::<address>::INSTR` |
| NI GPIB-USB-HS / GPIB-USB-HS+ | VISA board | `GPIB<board>::<address>::INSTR` |
| Measurement Computing USB-488, any other board the VISA library shows as `GPIBn` | VISA board | `GPIB<board>::<address>::INSTR` |
| Prologix GPIB-USB, AR488 (Arduino) | Prologix-compatible, serial port | `PROLOGIX::<port>::<address>::INSTR` |
| Prologix GPIB-ETHERNET | Prologix-compatible, TCP port 1234 | `PROLOGIX::<ip>::<address>::INSTR` |

The engine is `ola/gpib_adapter.py` (no Qt, tested without hardware); `ola/prologix.py` is the transport
for the Prologix-compatible adapters; the window is `frontend/ui/GpibAdapterDialog.py`. Adding a model is
one entry in `PROFILES` of `ola/gpib_adapter.py`.

## Installing the driver

**Keysight 82357B / 82357A**

* *Windows*: install the **Keysight IO Libraries Suite**, plug the adapter in and look in **Keysight
  Connection Expert** for its interface (`GPIB0`, `GPIB1`...). With NI-VISA installed as well, enable
  *VISA coexistence* or choose the IVI library in the tool.
* *Linux*: install **linux-gpib**, set `board_type = "agilent_82357a"` in `/etc/gpib.conf` (the same
  driver covers the 82357B), load the firmware (`gpib_config`, or `fxload` with the linux-gpib firmware
  package; until then the adapter shows the USB id `0957:0518` instead of `0957:0718`), then
  `pip install gpib-ctypes` and choose the library **pyvisa-py**.

### A new Keysight 82357B on Linux: the *Linux set-up* tab

On Linux the window has a **Linux set-up** tab (for the adapters driven by linux-gpib). *Check the
steps* shows, one by one, what a new 82357B still needs; *Run set-up (administrator)* does the missing
ones as root through `pkexec` (the system asks for the password), after showing the list of what will
be changed. *Show script* / *Save script...* give the same bash script to read first or to run by hand
with `sudo bash ola-gpib-setup.sh`. The script (`ola/gpib_linux.py`) does only what is missing and can
be run again:

1. **Packages**: compiler, kernel headers, autotools, bison, flex, curl and **fxload**
   (apt, dnf, pacman or zypper; other distributions: by hand).
2. **linux-gpib**: the distribution's `linux-gpib` package if there is one, otherwise the release
   tarball (linux-gpib 4.3.7 from SourceForge): `linux-gpib-kernel` (`make`, `make install`,
   `depmod`; only for kernels older than 6.13, newer kernels have the drivers in
   `drivers/staging/gpib`) and `linux-gpib-user` (`./configure --sysconfdir=/etc`, `make`,
   `make install`, `ldconfig`). The user part installs the udev rules `98-gpib-generic.rules` and
   `99-agilent_82357a.rules` and the firmware loader.
3. **Firmware**: `measat_releaseX1.8.hex` (82357B; 82357A: `82357a_fw.hex`) copied to
   `/usr/local/share/usb/agilent_82357a` (source build) or `/usr/share/usb/agilent_82357a`. It comes
   from the linux-gpib firmware archive; if that cannot be downloaded, put the file in a folder and
   choose it with *Firmware folder...*. At every plug-in udev runs
   `fxload -t fx2 -I measat_releaseX1.8.hex` and the adapter changes from USB `0957:0518` to
   `0957:0718`; then `gpib_config` configures the board.
4. **udev rule**: when linux-gpib's own rules are not there (some packages), the script writes
   `/etc/udev/rules.d/99-ola-agilent-82357.rules` (fxload on `0518`, `gpib_config --minor N` on
   `0718`, `/dev/gpib*` to the `gpib` group).
5. **/etc/gpib.conf**: the `interface` with `minor = <board>` gets `board_type = "agilent_82357a"`;
   the other interfaces and devices are kept and a backup copy (`gpib.conf.ola-backup-<date>`) is
   made first.
6. **Group**: `groupadd -f gpib` and `usermod -aG gpib <you>`.
7. `udevadm control --reload-rules`, `modprobe agilent_82357a`, `gpib_config --minor N`.

Then: **unplug the adapter and plug it in again**, and **log out and back in** (for the new group).
*Install Python bindings* runs `pip install gpib-ctypes` as you (no password), so that the pyvisa-py
library can use the board. The last check, *pyvisa-py sees GPIB0::INTFC*, says that everything works.

Things the script cannot fix, shown as warnings: **Secure Boot** on (`[GPIB-009]`: a module built on the
machine is not signed; sign it with `mokutil` or turn Secure Boot off) and a kernel 6.13 or newer whose
distribution does not build the staging gpib drivers (`CONFIG_GPIB`). After a kernel update a module
built from source must be built again: *Check the steps* shows it and *Run set-up* rebuilds it.

**NI GPIB-USB-HS**: NI-VISA + NI-488.2 on Windows (interface number in NI MAX); on Linux linux-gpib
with `board_type = "ni_usb_b"`.

**Prologix / AR488**: no driver beyond the USB-serial one; on Linux add your user to the `dialout`
group. The GPIB-ETHERNET needs its IP address (Prologix NetFinder).

## Using the tool

1. **Adapters** (left): *Add*, *Remove*, or *Detect connected adapters* (adds the `GPIBn` boards seen by
   the VISA libraries and the serial ports that look like a Prologix or an AR488).
2. **Adapter** tab: model, board number (VISA) or port / network address (Prologix), VISA library,
   command timeout, scan timeout and range (addresses 0-30), identification commands tried in turn
   (`*IDN?`, and `ID?` for older HP instruments such as the 3478A). *Save* (the configuration is also
   saved when the window closes, if it is valid).
3. **Driver check**: pyvisa / pyserial, the adapter on the USB bus (and its firmware), the VISA
   libraries and whether they see the board, `/dev/gpibN` on Linux, the answer of a Prologix to `++ver`,
   and what to install on this system.
4. **Bus**: *Scan the bus* lists the addresses that answer, with their identification and the address
   to use in the project (*Copy address*). With Keysight or NI VISA the addresses the library reports
   as listeners are tried first. *Interface Clear* resets the bus; *All to local* releases REN
   (VISA adapters only).
5. **Console**: write, query or read at an address, to try a command by hand.

## In a project

In the address editor of an instrument, the connection type **GPIB** shows the configured adapters
and the button **Pick from the GPIB bus...**, which lists the instruments found by the last scan (or
scans now) and fills the address in. The address is built for the chosen adapter (`GPIB1::7::INSTR`,
`PROLOGIX::COM5::7::INSTR`). Measurements open these addresses like any other: `PROLOGIX::...`
addresses go to `ola/prologix.py`, the others to pyvisa.

Several instruments behind one Prologix share the adapter link; each connection sends `++addr` again
when the adapter was talking to another instrument. The adapter is set to controller mode, no automatic
read (`++auto 0`), EOI on the last byte and nothing appended (`++eos 3`): the connection sends its own
terminator, escaped. It waits at most 3 s between two characters of an answer (`++read_tmo_ms 3000`).

## Errors

`GPIB-001`...`GPIB-009` (adapter not found, driver missing, firmware not loaded, no instrument answers,
timeout, invalid configuration, operation not supported, Linux set-up failed, Secure Boot): see [`ERROR_CODES.md`](../ERROR_CODES.md).

Not tried yet on real hardware: the tests use a simulated VISA library, a simulated Prologix and a
simulated Linux system (the generated script is checked with `bash -n`).

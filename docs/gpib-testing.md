# Testing the GPIB adapters on real hardware

How to check the GPIB adapter tool (*Tools > GPIB adapters*) with a real adapter and a real
instrument, and what to send back when something does not work. The set-up and the Linux procedure
are in [`gpib-adapters.md`](gpib-adapters.md); this page is only the test.

## Status

| Platform | Adapter | Status |
|---|---|---|
| Windows | Keysight 82357B (Keysight IO Libraries) | **Works**: bus scan and console tested by the author. Measurement in a project still to be tested. |
| Linux | Keysight 82357B (linux-gpib) | **Not verified.** The tester hit driver problems on his own Linux set-up, which are not in the program. The steps below are ready for the next attempt. |

Only the results written here are known. Everything else in the tool was tested with the simulated
VISA library, the simulated Prologix and the simulated Linux system of the test suite.

## Before you start

- One GPIB instrument with a known address, powered on, and a GPIB cable.
- Note the **model** of the instrument: the test results are recorded per model.
- Write down the answer to `*IDN?` of the instrument from its front panel or manual, so you can
  check the scan.

## Windows checklist

1. Install **Keysight IO Libraries Suite** and plug the 82357B in.
2. Open **Keysight Connection Expert**. The adapter must be listed as an interface, normally `GPIB0`.
   Note its number.
3. In the program: *Tools > GPIB adapters*, tab **Adapter**. Model *Keysight 82357B USB/GPIB*, board
   number = the one from Connection Expert, library *Default*. Press **Save**.
4. Tab **Driver check** → **Check driver and adapter**. Every line must be ✔ (Keysight VISA in use,
   board found). The USB line may say that USB devices cannot be listed: that is normal without `pyusb`.
5. Tab **Bus** → **Scan the bus**. Each instrument that answers must appear with its address
   (`GPIB0::n::INSTR`) and its identification. Compare the identification with the front panel.
6. Tab **Console**: select the instrument, send `*IDN?` with **Query**. Also check **Interface Clear**
   and **All to local**: the front panel of the instrument must come back to local.
7. **In a project** (not yet tested): open the address editor of an instrument, connection type
   **GPIB**, press **Pick from the GPIB bus...**, choose the instrument, then run a measurement with
   that instrument.

Record: instrument model, which steps passed, and the step that failed (if any).

## Linux checklist (when the set-up works)

Do this only after the set-up has been completed; see the *Linux set-up* section of
[`gpib-adapters.md`](gpib-adapters.md).

1. Unplug the adapter, plug it in again, then check the firmware:
   ```bash
   lsusb | grep 0957          # 0957:0518 = no firmware, 0957:0718 = firmware loaded
   ```
2. Check the device node and the driver:
   ```bash
   ls -l /dev/gpib0           # crw-rw---- root gpib
   dmesg | grep -i -E "gpib|82357"
   cat /etc/gpib.conf         # interface with minor = 0 and board_type = "agilent_82357a"
   uname -r
   ```
3. Log out and back in (membership of the `gpib` group). Then, in the program: tab **Linux set-up** →
   **Check the steps**. Every step must be ✔, except the optional warnings.
4. Independent check, without the program (linux-gpib tools):
   ```bash
   ibtest                     # interactive test of the board, if installed
   ibterm                     # terminal to the instrument, if installed
   ```
   If the instrument answers in `ibterm` but not in the program, the problem is in the program: report it.
5. Then repeat the Windows steps 3–7 with the library **pyvisa-py (@py)**.

## When a test fails: what to send

Open an issue (or send it to the maintainer) with:

- the **instrument model** and the **adapter model** (and its firmware state, `lsusb` line);
- the step that failed, and the **exact message** shown by the program (copy from the tab, including
  the `[GPIB-xxx]` code if there is one);
- on Windows: the screen of **Keysight Connection Expert**;
- on Linux: the output of the commands above (`lsusb`, `ls -l /dev/gpib0`, `dmesg`, `cat /etc/gpib.conf`,
  `uname -r`), and the log of the **Linux set-up** tab.

Timeouts are shown as `TRN-003` (see [`ERROR_CODES.md`](../ERROR_CODES.md)). Keep the instrument model next
to every result, as in the [test status of the README](../README.md#software-test-status).

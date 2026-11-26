# Troubleshooting

The first thing to look at is the **error code** in the message, for example `[TRN-003]`. [Error codes](Error-Codes) says what each one means and what to do.

## A USB-TMC instrument on Linux is not found

**Symptoms**: the instrument is plugged in and `lsusb` lists it, but VISA lists no `USB0::...::INSTR` resource, the automatic search of the instrument window finds nothing, and `pyusb` fails with `The device has no langid (permission issue ...)`.

**Cause**: the kernel `usbtmc` driver takes the instrument, and its device node in `/dev/bus/usb/` is owned by `root:root` with mode `0664`. The user cannot open it, so the VISA backends cannot read the instrument's identity. The instrument itself is fine: `/dev/usbtmc0` answers `*IDN?`.

**Check**:

```bash
lsusb                              # find the vendor:product ids of the instrument
ls -l /dev/usbtmc*                 # the kernel driver created a node
ls -l /dev/bus/usb/<bus>/<dev>     # root:root 0664 = the VISA backend cannot open it
```

**Fix**: a udev rule that gives the device to a group the user belongs to (here `plugdev`). Replace the ids with the ones from `lsusb`, without `0x`, and do not add the serial number:

```bash
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="<vendor-id>", ATTR{idProduct}=="<product-id>", MODE="0664", GROUP="plugdev"' \
  | sudo tee /etc/udev/rules.d/99-usbtmc-instrument.rules
sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=usb
```

Unplug and plug the instrument again, and check that `id -nG` lists `plugdev`. The instrument window must use the `USB0::` resource, not `/dev/usbtmc0`.

The full text is in the repository README, section *Troubleshooting*.

## A GPIB adapter is not found

*Tools > GPIB adapters* checks the driver and scans the bus. On Linux it can run the set-up of linux-gpib (firmware, udev, `/etc/gpib.conf`, `gpib` group) through `pkexec`. After the set-up, unplug and plug the adapter again and log in again. Codes `GPIB-001` to `GPIB-009`. Guide: [GPIB adapters](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/gpib-adapters.md).

## A command times out

A timeout reaches you as `TRN-003`. Raise the timeout of the instrument in the instrument file, and check the terminators and, for a serial instrument, the baud rate and flow control (`scripts/instrument_shell.py`, command `probe`, finds the settings an instrument answers to).

## Still stuck

Open an issue and include the error code, your operating system, the instrument model and the interface (LAN, USB, GPIB, serial). The output of `scripts/instrument_shell.py` is the most useful thing to attach.

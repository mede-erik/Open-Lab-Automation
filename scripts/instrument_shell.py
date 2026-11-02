#!/usr/bin/env python3
"""Interactive terminal tester for the instrument library.

Pick a category (datalogger, power supply, ...), a model and an interface, connect, then run
logical calls on the instrument and see exactly which commands are sent and what comes back.

    python3 scripts/instrument_shell.py                  # real instrument
    python3 scripts/instrument_shell.py --sim            # no hardware: a fake instrument answers
    python3 scripts/instrument_shell.py --library path/to/instruments_lib.json

Commands once connected (type 'help'):
    calls                 list the calls this model defines ([M] mandatory, [O] optional)
    missing               mandatory calls the model does not define
    call NAME [a=v ...]   run a call (missing arguments are asked)
    plan NAME [a=v ...]   show the commands without sending them
    readback NAME [a=v]   read back a set call
    test [writes] [all]   run every call that needs no argument ('writes' also actions,
                          'all' also lists the skipped calls)
    serial                show / change the serial settings (RS-232) and reconnect
    raw TEXT              send TEXT as it is and show what comes back (debugging)
    probe [all]           RS-232: find the baud rate / flow control the instrument answers to
                          ('all' also tries parity even / odd)
    loopback              adapter test: join pins 2 and 3 of the adapter, 'hello' must come back
    reconnect             open the connection again
    quit
"""

import argparse
import os
import shlex
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ola import tester  # noqa: E402
from ola.call_errors import CallError  # noqa: E402
from ola.library import Library  # noqa: E402


def default_library():
    for p in (
        os.path.join(ROOT, "Instruments_LIB", "instruments_lib.json"),
        os.path.join(os.path.dirname(ROOT), "Instruments_LIB", "instruments_lib.json"),
    ):
        if os.path.isfile(p):
            return p
    return os.path.join(ROOT, "Instruments_LIB", "instruments_lib.json")


class Shell:
    def __init__(self, library, input_fn=input, print_fn=print, simulate=False, source=""):
        self.library = library
        self.source = source
        self.ask = input_fn
        self.say = print_fn
        self.simulate = simulate
        self.model_id = None
        self.handle = None
        self.connection = None
        self.address = None
        self.serial_override = {}

    # ---- selection ----------------------------------------------------------------
    def choose(self, title, options):
        """options: list of (value, label). Returns the chosen value, or None to quit."""
        self.say(f"\n{title}")
        for i, (_, label) in enumerate(options, 1):
            self.say(f"  {i}) {label}")
        while True:
            text = self.ask("number (q = quit): ").strip().lower()
            if text in ("q", "quit", "exit"):
                return None
            if text.isdigit() and 1 <= int(text) <= len(options):
                return options[int(text) - 1][0]
            self.say("  not a valid choice")

    def describe_library(self):
        cats = tester.categories(self.library)
        n_models = sum(len(tester.models_of(self.library, k)) for k, _ in cats)
        version = self.library.schema_version
        self.say(f"Library: {self.source or '(in memory)'}")
        self.say(
            f"  schema_version {version}, {len(cats)} categories, {n_models} models, "
            f"{len(self.library.schemas)} call schemas"
        )
        if not self.library.schemas:
            self.say(
                "  WARNING: no 'schema' folder found next to the library file: the library is "
                "probably an old version (update the Instruments_LIB submodule)"
            )

    def select_and_connect(self):
        self.describe_library()
        cats = tester.categories(self.library)
        category = self.choose("Instrument type:", [(k, f"{label} ({k})") for k, label in cats])
        if category is None:
            return False
        models = tester.models_of(self.library, category)
        model_id = self.choose(
            "Model:", [(m, f"{name}  [{series}]  ({m})") for m, name, series in models]
        )
        if model_id is None:
            return False
        self.model_id = model_id
        connection = self.open_interface(model_id)
        if connection is None:
            return False
        self.connection = connection
        self.handle = tester.make_handle(self.library, model_id, connection, model_id)
        self.say(f"\nConnected to {model_id}.")
        if getattr(connection, "peer", "").upper().startswith("ASRL") and self.handle.supports(
            "set_remote"
        ):
            # over RS-232 many instruments only listen once they are in remote mode
            try:
                self.handle.call("set_remote")
                self.say("  sent set_remote (RS-232)")
            except Exception as exc:
                self.say(f"  set_remote not accepted: {exc}")
        if self.handle.supports("identification_query"):
            self.run_call("identification_query", [])
        return True

    def open_interface(self, model_id):
        options = []
        for itf in tester.interfaces(self.library, model_id):
            label = f"{itf['type']}   e.g. {itf['example']}" if itf["example"] else itf["type"]
            options.append((("visa", itf), label))
            for tr in itf["transports"]:
                if tr.get("kind") == "raw_socket":
                    options.append(
                        (("tcp", tr), f"{itf['type']} raw socket (port {tr.get('port')})")
                    )
        options.append((("sim", None), "Simulated instrument (no hardware)"))
        if self.simulate:
            options = [o for o in options if o[0][0] == "sim"]
        choice = self.choose("Interface:", options)
        if choice is None:
            return None
        kind, data = choice
        try:
            if kind == "sim":
                answer = (
                    self.ask("answer of the simulated instrument to every query [1]: ").strip()
                    or "1"
                )
                return tester.open_simulated(answer)
            if kind == "tcp":
                host = self.ask("IP address: ").strip()
                port = int(
                    self.ask(f"port [{data.get('port', 5025)}]: ").strip() or data.get("port", 5025)
                )
                return tester.open_raw_socket(host, port)
            address = self.ask("VISA address: ").strip()
            self.address = address
            if address.upper().startswith("ASRL"):
                self.serial_settings_dialog(model_id)
            return tester.open_visa(
                address, self.library, model_id, serial_override=self.serial_override
            )
        except Exception as exc:
            self.say(f"cannot connect: {type(exc).__name__}: {exc}")
            if kind == "visa":
                self.say("\nVISA diagnostics:")
                self.say(tester.visa_diagnostics())
                self.say(
                    "Check: the address above is in the list of resources; the user can "
                    "open the port (Linux: group 'dialout'); no other program uses it."
                )
            return None

    def serial_settings_dialog(self, model_id):
        cfg = {**self.library.serial_settings(model_id), **self.serial_override}
        for itf in tester.interfaces(self.library, model_id):
            if itf["type"] == "SERIAL" and itf["notes"]:
                self.say(f"note: {itf['notes']}")
        self.say(f"serial settings from the library: {cfg or 'none'}")
        self.say("they must match the instrument's front-panel RS-232 menu.")
        text = self.ask("override (e.g. baud=19200 flow_control=dtr_dsr), Enter to keep: ").strip()
        for part in shlex.split(text):
            key, _, value = part.partition("=")
            self.serial_override[key] = tester.parse_value(value)

    # ---- commands ---------------------------------------------------------------
    def parse_args(self, name, words):
        args = {}
        for w in words:
            key, _, value = w.partition("=")
            args[key] = tester.parse_value(value)
        spec = tester.call_spec(self.library, self.model_id, name) or {}
        for arg, a in spec.get("args", {}).items():
            if arg in args or not (a.get("required", True) or arg == "channel_number"):
                continue
            hint = ", ".join(str(x) for x in (a.get("type"), a.get("unit"), a.get("keywords")) if x)
            default = a.get("default")
            text = self.ask(
                f"  {arg} ({hint}){f' [{default}]' if default is not None else ''}: "
            ).strip()
            if text:
                args[arg] = tester.parse_value(text)
            elif default is not None:
                args[arg] = default
        return args

    def run_call(self, name, words, readback=False, dry=False):
        args = self.parse_args(name, words)
        try:
            steps = tester.describe_plan(self.library, self.model_id, name, args, readback)
        except CallError as exc:
            self.say(f"  {exc}")
            return
        self.say("  commands: " + "  ;  ".join(steps))
        if dry:
            return
        info = next(
            (c for c in tester.model_calls(self.library, self.model_id) if c["name"] == name), {}
        )
        if info.get("kind") in ("set", "action") and not readback:
            if self.ask("  this writes to the instrument. Send? [y/N] ").strip().lower() != "y":
                self.say("  not sent")
                return
        try:
            value = (self.handle.readback if readback else self.handle.call)(name, **args)
            self.say(self.format_result(value))
        except CallError as exc:
            self.say(f"  {exc}")
        except Exception as exc:
            self.say(f"  {type(exc).__name__}: {exc}")

    @staticmethod
    def format_result(value):
        """Short text of a result: long data (waveforms) is summarised, not printed whole."""
        return "  done" if value is None else f"  result: {tester.summarise(value)}"

    def show_calls(self):
        for c in tester.model_calls(self.library, self.model_id):
            mark = {"mandatory": "M", "optional": "O"}.get(c["requirement"], "-")
            args = ", ".join(c["args"]) if c["args"] else ""
            self.say(f"  [{mark}] {c['name']:34} {c['kind']:7} {args}")

    def run_test(self, writes, show_all=False):
        def confirm(question):
            return self.ask(f"  {question} [y/N] ").strip().lower() == "y"

        results = tester.self_test(
            self.library,
            self.model_id,
            self.handle,
            include_writes=writes,
            confirm=confirm if writes else None,
        )
        counts = {"ok": 0, "fail": 0, "skip": 0}
        for r in results:
            counts[r.status] += 1
            if r.status != "skip" or show_all:
                self.say(f"  {r.status.upper():4} {r.call:34} {r.detail}")
        self.say(f"  {counts['ok']} ok, {counts['fail']} failed, {counts['skip']} skipped")

    def repl(self):
        self.say("\nType 'help' for the commands.")
        while True:
            try:
                line = self.ask("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            words = shlex.split(line)
            cmd, rest = words[0].lower(), words[1:]
            if cmd in ("quit", "exit", "q"):
                break
            elif cmd == "help":
                self.say(__doc__)
            elif cmd == "calls":
                self.show_calls()
            elif cmd == "missing":
                missing = tester.missing_mandatory(self.library, self.model_id)
                self.say(
                    "  "
                    + (", ".join(missing) if missing else "none: all mandatory calls are defined")
                )
            elif cmd in ("call", "plan", "readback") and rest:
                self.run_call(rest[0], rest[1:], readback=(cmd == "readback"), dry=(cmd == "plan"))
            elif cmd == "test":
                self.run_test("writes" in rest, "all" in rest)
            elif cmd == "serial" and self.address:
                self.serial_settings_dialog(self.model_id)
                self.reconnect()
            elif cmd == "reconnect" and self.address:
                self.reconnect()
            elif cmd == "raw" and rest:
                self.raw(" ".join(rest))
            elif cmd == "probe" and self.address:
                self.probe("all" in rest)
            elif cmd == "loopback" and self.address:
                self.loopback()
            elif cmd in {c["name"] for c in tester.model_calls(self.library, self.model_id)}:
                self.run_call(cmd, rest)  # a call name alone works like 'call NAME'
            else:
                self.say("  unknown command (type 'help')")
        if self.connection is not None and hasattr(self.connection, "close"):
            self.connection.close()

    def reconnect(self):
        """Close the connection and open it again with the current serial settings."""
        if self.connection is not None and hasattr(self.connection, "close"):
            try:
                self.connection.close()
            except Exception:
                pass
        try:
            self.connection = tester.open_visa(
                self.address, self.library, self.model_id, serial_override=self.serial_override
            )
        except Exception as exc:
            self.say(f"  cannot connect: {type(exc).__name__}: {exc}")
            return
        self.handle = tester.make_handle(
            self.library, self.model_id, self.connection, self.model_id
        )
        self.say("  reconnected")
        if self.address.upper().startswith("ASRL") and self.handle.supports("set_remote"):
            try:
                self.handle.call("set_remote")
            except Exception as exc:
                self.say(f"  set_remote not accepted: {exc}")
        if self.handle.supports("identification_query"):
            self.run_call("identification_query", [])

    def raw(self, text):
        """Send text exactly as typed and show the raw answer."""
        try:
            self.connection.send(text)
            self.say(f"  answer: {self.connection.read_line(2000)!r}")
        except Exception as exc:
            self.say(f"  no answer: {type(exc).__name__}: {exc}")
            if "closed" in str(exc).lower():
                self.say("  the connection is closed (probe/loopback close it): type 'reconnect'")

    def loopback(self):
        port = tester.serial_port_from_address(self.address)
        self.say(
            f"  closing the VISA connection; join pins 2 and 3 of the adapter ({port}), "
            "NOT connected to the instrument"
        )
        if self.connection is not None and hasattr(self.connection, "close"):
            try:
                self.connection.close()
            except Exception:
                pass
        try:
            echo = tester.loopback_serial(port)
        except Exception as exc:
            self.say(f"  cannot open {port}: {exc}")
            return
        if echo == "hello":
            self.say("  OK: 'hello' came back, the adapter and the port work")
        else:
            self.say(
                f"  NOT OK: got {echo!r}. Pins 2-3 not joined, wrong port, or a faulty adapter"
            )
        self.say("  type 'reconnect' to open the connection again")

    def probe(self, every_parity=False):
        port = tester.serial_port_from_address(self.address)
        self.say(f"  closing the VISA connection and probing {port} with *IDN? ...")
        self.say("  (the instrument must be set to RS-232 in its Interface menu)")
        if self.connection is not None and hasattr(self.connection, "close"):
            try:
                self.connection.close()
            except Exception:
                pass
        try:
            found = tester.probe_serial(
                port, parities=("N", "E", "O") if every_parity else ("N",), progress=self.say
            )
        except Exception as exc:
            self.say(f"  {exc}")
            return
        if not found:
            self.say(
                "  NO answer with any setting. Check: instrument set to RS-232 (not GPIB), "
                "cable (null-modem / crossover), the right port, and the adapter "
                "(loopback test: join pins 2 and 3 of the cable and run 'raw hello')."
            )
            return
        hit = found[0]
        self.say(f"  ANSWER: {hit.answer!r}")
        self.say(f"  settings: baud={hit.baud} flow_control={hit.flow_control} parity={hit.parity}")
        self.serial_override.update(baud=hit.baud, flow_control=hit.flow_control, parity=hit.parity)
        if hit.parity != "N":
            self.serial_override["data_bits"] = 7
        self.say("  type 'reconnect' to use them (the library factory values are in the manual).")

    def run(self):
        if self.select_and_connect():
            self.repl()


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--library", default=default_library())
    ap.add_argument("--sim", action="store_true", help="only the simulated instrument")
    args = ap.parse_args()
    if not os.path.isfile(args.library):
        sys.exit(f"library not found: {args.library}")
    Shell(Library.load(args.library), simulate=args.sim, source=os.path.abspath(args.library)).run()


if __name__ == "__main__":
    main()

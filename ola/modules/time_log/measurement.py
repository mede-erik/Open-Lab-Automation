"""Time log: read a set of values at a fixed interval.

Parameters::

    {"interval_s": 1.0, "duration_s": 3600,            # or "samples": 100
     "channels": [{"name": "vout", "instrument": "dmm1", "call": "read_voltage"},
                  {"name": "temp1", "instrument": "daq", "call": "measure_temperature",
                   "args": {"channels": "101"}}]}

``instrument`` is the name of an instrument bound to the ``instruments`` role. Samples are
scheduled from the start time (no drift): a slow read shortens the next wait, it does not
shift the whole log. ``t_s`` is the time at which the acquisition of the sample started,
so it follows the schedule even when reads are slow. If a read fails the log stops with an
error (what was recorded stays).
"""

import time

from ola.measurement import Measurement, MeasurementContext, MeasurementError


class TimeLog(Measurement):
    """Time log measurement; the parameters are described in the module docstring."""

    def validate(self):
        """Check the parameters; return the list of problems (empty if OK)."""
        p, problems = self.params, []
        interval = p.get("interval_s")
        if not isinstance(interval, (int, float)) or isinstance(interval, bool) or interval < 0.001:
            problems.append("interval_s must be a number >= 0.001")
        duration, samples = p.get("duration_s"), p.get("samples")
        if duration is None and samples is None:
            problems.append("give duration_s or samples (otherwise the log would never end)")
        if duration is not None and (not isinstance(duration, (int, float)) or duration <= 0):
            problems.append("duration_s must be a number > 0")
        if samples is not None and (
            not isinstance(samples, int) or isinstance(samples, bool) or samples < 1
        ):
            problems.append("samples must be an integer >= 1")
        channels = p.get("channels")
        if not isinstance(channels, list) or not channels:
            problems.append("channels must be a non-empty list")
            return problems
        names = set()
        for i, ch in enumerate(channels):
            if not isinstance(ch, dict) or not all(
                isinstance(ch.get(k), str) and ch.get(k) for k in ("name", "instrument", "call")
            ):
                problems.append(f"channel {i}: needs 'name', 'instrument' and 'call' (strings)")
                continue
            if ch["name"] in names:
                problems.append(f"duplicate channel name {ch['name']!r}")
            names.add(ch["name"])
            if "args" in ch and not isinstance(ch["args"], dict):
                problems.append(f"channel {ch['name']}: 'args' must be an object")
        return problems

    def setup(self, ctx: MeasurementContext) -> None:
        """Find each channel's instrument handle (fails before any read if one is unbound)."""
        by_name = {h.name: h for h in ctx.instruments("instruments")}
        self._readers = []
        for ch in self.params["channels"]:
            if ch["instrument"] not in by_name:
                raise MeasurementError(
                    f"channel {ch['name']!r}: instrument {ch['instrument']!r} is not bound "
                    f"(bound: {sorted(by_name)})"
                )
            self._readers.append(
                (ch["name"], by_name[ch["instrument"]], ch["call"], ch.get("args", {}))
            )

    def run(self, ctx: MeasurementContext) -> None:
        """Sample every ``interval_s`` until ``samples`` or ``duration_s`` is reached."""
        interval = float(self.params["interval_s"])
        duration = self.params.get("duration_s")
        samples = self.params.get("samples")
        t0 = time.monotonic()
        n = 0
        while True:
            ctx.checkpoint()
            t_sample = time.monotonic() - t0  # when the acquisition of this sample starts
            values = {name: handle.call(call, **args) for name, handle, call, args in self._readers}
            values["t_s"] = t_sample
            ctx.emit_point(values)
            n += 1
            total = (
                samples
                if samples is not None
                else (int(duration / interval) + 1 if duration is not None else None)
            )
            ctx.progress(n, total)
            if samples is not None and n >= samples:
                return
            next_t = n * interval
            if duration is not None and next_t > duration:
                return
            ctx.sleep(max(0.0, t0 + next_t - time.monotonic()))

"""Cable characterization: the loss of an RF cable against frequency, with a VNA.

Parameters (``.cbl`` file)::

    {"mode": "transmission",                      # or "reflection" (open / short on the far end)
     "sweep": {"start_hz": 1e6, "stop_hz": 3e9, "points": 401, "scale": "linear",
               "if_bandwidth_hz": 1000, "power_dbm": -10},          # the last two are optional
     "cable": {"label": "RG58 #3", "length_m": 1.0},                # both optional
     "frequencies_of_interest": [433e6, 868e6, 2.4e9],              # optional
     "limits": {"max": [[1e6, 0.5], [3e9, 2.0]]},                   # optional, on the loss in dB
     "also_s11": true, "averages": 1, "confirm_setup": true}

The VNA is calibrated by the user beforehand (at the ends of the test leads); the measurement asks
for it once and then does not touch the calibration. What it asks of the instrument are two *logical
calls*, the same for every VNA (the library translates them for the model):

    set_sweep(start_frequency, stop_frequency, points, sweep_type, if_bandwidth, power)
    read_sparameter(parameter="S21")  ->  {"frequency": [...], "values": [[re, im], ...]}

The answer of ``read_sparameter`` may also be a plain list of complex numbers (or ``[re, im]``
pairs); the frequencies are then those of the sweep.

Results: the curves ``loss_db`` (positive = loss), ``loss_db_per_m`` (with the length) and
``group_delay_ns`` plus the raw S-parameters (hidden at first: they are what the Touchstone export
and the Smith chart use); the table ``sweep`` (a row per frequency); and one summary row in
``points`` (loss at the frequencies of interest, the worst loss, delay, velocity factor, return
loss, verdict). A failed limit is a *result*, not an error: the run still finishes.

In reflection mode the signal goes to the end and back, so the loss of the cable is half of the
loss measured on S11 (``-|S11|dB / 2``) and the delay is half of the delay of S11.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from ola import rf
from ola.efficiency_spec import Problem
from ola.limits import LimitError, parse_limits
from ola.measurement import Measurement, MeasurementContext, MeasurementError, Stopped
from ola.run_view import format_si

MODES = ("transmission", "reflection")
TERMINATIONS = ("open", "short")
SCALES = ("linear", "log")
MAX_POINTS = 100_001
MAX_AVERAGES = 1000
SPEED_OF_LIGHT = rf.SPEED_OF_LIGHT


def default_params() -> Dict[str, Any]:
    """The starting parameters of a new cable measurement (used by the editor)."""
    return {
        "mode": "transmission",
        "sweep": {"start_hz": 1e6, "stop_hz": 3e9, "points": 401, "scale": "linear"},
        "cable": {"label": "", "length_m": 1.0},
        "frequencies_of_interest": [],
        "averages": 1,
        "confirm_setup": True,
    }


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value


def _frequency_label(f: float) -> str:
    """``433e6 -> "433MHz"``: for the names of the result columns."""
    return format_si(f, "Hz").replace(" ", "")


def check_params(params: Dict[str, Any]) -> List[Problem]:
    """Everything wrong with the parameters, each with the path of the field. Does no I/O."""
    out: List[Problem] = []

    def err(path: str, message: str) -> None:
        out.append(Problem(path, message))

    mode = params.get("mode", "transmission")
    if mode not in MODES:
        err("mode", f"must be one of {', '.join(MODES)} (not {mode!r})")
    termination = params.get("termination", "open")
    if mode == "reflection" and termination not in TERMINATIONS:
        err("termination", f"must be one of {', '.join(TERMINATIONS)} (not {termination!r})")

    sweep = params.get("sweep")
    start = stop = None
    if not isinstance(sweep, dict):
        err("sweep", "the sweep (start, stop, points) is missing")
    else:
        start, stop = sweep.get("start_hz"), sweep.get("stop_hz")
        if not _is_number(start) or start <= 0:
            err("sweep.start_hz", "the start frequency must be a number above 0 (Hz)")
            start = None
        if not _is_number(stop) or stop <= 0:
            err("sweep.stop_hz", "the stop frequency must be a number above 0 (Hz)")
            stop = None
        if start is not None and stop is not None and start >= stop:
            err("sweep.stop_hz", "the stop frequency must be above the start frequency")
        points = sweep.get("points")
        if not isinstance(points, int) or isinstance(points, bool) or not 2 <= points <= MAX_POINTS:
            err(
                "sweep.points",
                f"the number of points must be a whole number from 2 to {MAX_POINTS}",
            )
        if sweep.get("scale", "linear") not in SCALES:
            err("sweep.scale", f"must be one of {', '.join(SCALES)}")
        if "if_bandwidth_hz" in sweep and (
            not _is_number(sweep["if_bandwidth_hz"]) or sweep["if_bandwidth_hz"] <= 0
        ):
            err("sweep.if_bandwidth_hz", "the IF bandwidth must be a number above 0 (Hz)")
        if "power_dbm" in sweep and not _is_number(sweep["power_dbm"]):
            err("sweep.power_dbm", "the power must be a number (dBm)")

    cable = params.get("cable", {})
    if not isinstance(cable, dict):
        err("cable", "must be an object with 'label' and 'length_m'")
    else:
        if "length_m" in cable and cable["length_m"] is not None:
            if not _is_number(cable["length_m"]) or cable["length_m"] <= 0:
                err("cable.length_m", "the length must be a number above 0 (metres)")
        if "label" in cable and not isinstance(cable["label"], str):
            err("cable.label", "the label must be text")

    warning = _step_warning(params)
    if warning:
        out.append(Problem("sweep.points", warning, "warning"))

    wanted = params.get("frequencies_of_interest", [])
    if not isinstance(wanted, list) or not all(_is_number(f) and f > 0 for f in wanted):
        err("frequencies_of_interest", "must be a list of frequencies above 0 (Hz)")
    elif start is not None and stop is not None:
        outside = [f for f in wanted if not start <= f <= stop]
        if outside:
            shown = ", ".join(format_si(f, "Hz") for f in outside)
            err(
                "frequencies_of_interest", f"outside the sweep ({shown}): nothing is measured there"
            )

    try:
        parse_limits(params.get("limits"))
    except LimitError as exc:
        err("limits", str(exc))

    averages = params.get("averages", 1)
    if (
        not isinstance(averages, int)
        or isinstance(averages, bool)
        or not 1 <= averages <= MAX_AVERAGES
    ):
        err("averages", f"must be a whole number from 1 to {MAX_AVERAGES}")
    for key in ("also_s11", "confirm_setup"):
        if key in params and not isinstance(params[key], bool):
            err(key, "must be true or false")
    return out


TYPICAL_VELOCITY_FACTOR = 0.6  # a little below most coaxial cables: errs on the safe side


def max_frequency_step(length_m: float) -> float:
    """The largest step between two frequency points for which the phase of a cable of this
    length changes by less than half a turn: beyond it the phase wraps and the group delay cannot
    be found. ``1 / (2 delay)``."""
    delay = length_m / (TYPICAL_VELOCITY_FACTOR * SPEED_OF_LIGHT)
    return 1.0 / (2.0 * delay)


def _step_warning(params: Dict[str, Any]) -> Optional[str]:
    """A sentence if the sweep is too coarse for the cable's length (needs a valid sweep)."""
    sweep, cable = params.get("sweep"), params.get("cable") or {}
    length = cable.get("length_m") if isinstance(cable, dict) else None
    try:
        start, stop, n = float(sweep["start_hz"]), float(sweep["stop_hz"]), sweep["points"]
        if isinstance(n, bool) or not isinstance(n, int) or n < 2:
            return None  # (a wrong number of points is reported as an error already)
        if not (length and length > 0 and 0 < start < stop):
            return None
    except (KeyError, TypeError, ValueError):
        return None
    if sweep.get("scale") == "log":
        step = stop - stop / ((stop / start) ** (1 / (n - 1)))  # the widest step: at the top
    else:
        step = (stop - start) / (n - 1)
    limit = max_frequency_step(length)
    if step <= limit:
        return None
    needed = int((stop - start) / limit) + 2
    return (
        f"the step between points ({format_si(step, 'Hz')}) is too large for a cable of "
        f"{length:g} m: the phase wraps between points, so the group delay and the velocity "
        f"factor cannot be found (the loss is not affected). Use at least {needed} points"
    )


def sweep_frequencies(sweep: Dict[str, Any]) -> List[float]:
    """The frequencies of a sweep: evenly spaced, or logarithmically spaced for ``scale: log``."""
    start, stop, n = float(sweep["start_hz"]), float(sweep["stop_hz"]), int(sweep["points"])
    if sweep.get("scale", "linear") == "log":
        ratio = (stop / start) ** (1 / (n - 1))
        return [start * ratio**k for k in range(n)]
    return [start + (stop - start) * k / (n - 1) for k in range(n)]


def as_trace(
    result: Any, fallback_freq: Sequence[float], what: str
) -> Tuple[List[float], List[complex]]:
    """Normalise what the VNA answered to ``(frequencies, complex values)``; the message says what
    was wrong when it does not fit."""
    freq: Optional[Sequence[float]] = None
    values: Any = result
    if isinstance(result, dict):
        freq = result.get("frequency", result.get("freq"))
        values = result.get("values", result.get("s"))
    if not isinstance(values, (list, tuple)) or not values:
        raise MeasurementError(f"the VNA gave no data for {what} (got {type(result).__name__})")
    try:
        complex_values = [
            complex(*v) if isinstance(v, (list, tuple)) else complex(v) for v in values
        ]
    except (TypeError, ValueError) as exc:
        raise MeasurementError(f"the VNA data for {what} is not a list of complex numbers") from exc
    freq = list(freq) if freq is not None else list(fallback_freq)
    if len(freq) != len(complex_values):
        raise MeasurementError(
            f"the VNA gave {len(complex_values)} values for {what} at {len(freq)} frequencies"
        )
    return [float(f) for f in freq], complex_values


def compute_results(
    freq: List[float], traces: Dict[str, List[complex]], params: Dict[str, Any]
) -> Dict[str, Any]:
    """The loss, delay and summary from the measured S-parameters. No I/O: ``traces`` has ``S21``
    (transmission) or ``S11`` (reflection), and optionally ``S11`` in transmission."""
    mode = params.get("mode", "transmission")
    length = (params.get("cable") or {}).get("length_m")
    if mode == "transmission":
        loss = rf.insertion_loss_db(traces["S21"])
        delay = rf.group_delay_s(freq, traces["S21"])
    else:  # the signal goes to the far end and back
        loss = [v / 2 for v in rf.return_loss_db(traces["S11"])]
        delay = [d / 2 for d in rf.group_delay_s(freq, traces["S11"])]
    result: Dict[str, Any] = {"loss_db": loss, "delay_s": delay}
    if length:
        result["loss_db_per_m"] = [v / length for v in loss]
    summary: Dict[str, Any] = {
        "mode": mode,
        "points": len(freq),
        "max_loss_db": max(loss),
        "max_loss_at_hz": freq[loss.index(max(loss))],
        "mean_delay_ns": sum(delay) / len(delay) * 1e9,
    }
    if length:
        summary["length_m"] = length
        mean_delay = sum(delay) / len(delay)
        if mean_delay > 0:
            factor = rf.velocity_factor(mean_delay, length)
            if 0.2 <= factor <= 1.05:  # beyond this the delay is not real: the phase wrapped
                summary["velocity_factor"] = factor
    for f in params.get("frequencies_of_interest") or []:
        name = _frequency_label(f)
        summary[f"loss_{name}_db"] = rf.value_at(freq, loss, f)
        if length:
            summary[f"loss_{name}_db_per_m"] = rf.value_at(freq, result["loss_db_per_m"], f)
    s11 = traces.get("S11")
    if s11 is not None and mode == "transmission":
        return_loss = rf.return_loss_db(s11)
        summary["min_return_loss_db"] = min(return_loss)
        summary["max_vswr"] = max(rf.vswr(s11))
        result["return_loss_db"] = return_loss
    result["summary"] = summary
    return result


class CableCharacterization(Measurement):
    """Loss of an RF cable with a VNA; see the module docstring."""

    def check(self) -> List[Problem]:
        """The problems of the parameters with the path of each field (for the editor)."""
        return check_params(self.params)

    def validate(self) -> List[str]:
        """The errors as readable sentences."""
        return [str(p) for p in self.check() if p.severity == "error"]

    # ----- the measurement --------------------------------------------------------------------
    def run(self, ctx: MeasurementContext) -> None:
        """Ask for the set-up, sweep, read, compute, report."""
        p = self.params
        mode = p.get("mode", "transmission")
        sweep = p["sweep"]
        handle = ctx.instrument("vna")
        if p.get("confirm_setup", True):
            self._confirm_setup(ctx, mode)
        handle.call(
            "set_sweep",
            start_frequency=sweep["start_hz"],
            stop_frequency=sweep["stop_hz"],
            points=sweep["points"],
            sweep_type=sweep.get("scale", "linear"),
            **{k: sweep[s] for k, s in (("if_bandwidth", "if_bandwidth_hz"), ("power", "power_dbm"))
               if s in sweep},
        )  # fmt: skip
        wanted = ["S21"] if mode == "transmission" else ["S11"]
        if mode == "transmission" and p.get("also_s11"):
            wanted.append("S11")
        nominal = sweep_frequencies(sweep)
        totals: Dict[str, List[complex]] = {}
        freq: List[float] = []
        averages = int(p.get("averages", 1))
        for sweep_no in range(1, averages + 1):
            for name in wanted:
                ctx.checkpoint()
                freq, values = as_trace(
                    handle.call("read_sparameter", parameter=name), nominal, name
                )
                if name in totals and len(totals[name]) != len(values):
                    raise MeasurementError(f"the number of points of {name} changed between sweeps")
                totals[name] = (
                    values if name not in totals else [a + b for a, b in zip(totals[name], values)]
                )
            ctx.progress(sweep_no, averages, f"sweep {sweep_no} of {averages}")
        traces = {name: [v / averages for v in values] for name, values in totals.items()}
        self._report(ctx, freq, traces)

    def _confirm_setup(self, ctx: MeasurementContext, mode: str) -> None:
        sweep = self.params["sweep"]
        if mode == "transmission":
            connect = "Connect the cable under test between port 1 and port 2 of the VNA."
        else:
            far = self.params.get("termination", "open")
            connect = (
                f"Connect one end of the cable under test to port 1 and put an {far} circuit "
                f"on the other end."
            )
        text = (
            "Is the VNA calibrated for this cable and this frequency range "
            f"({format_si(sweep['start_hz'], 'Hz')} to {format_si(sweep['stop_hz'], 'Hz')})? "
            f"{connect} Then continue."
        )
        data = {
            "kind": "calibration",
            "start_hz": sweep["start_hz"],
            "stop_hz": sweep["stop_hz"],
            "points": sweep["points"],
            "mode": mode,
        }
        if ctx.ask(text, ["continue", "abort"], default="abort", data=data) == "abort":
            raise Stopped()

    def _report(self, ctx: MeasurementContext, freq: List[float], traces: Dict[str, List[complex]]):
        p = self.params
        mode = p.get("mode", "transmission")
        cable = p.get("cable") or {}
        log_x = (p.get("sweep") or {}).get("scale") == "log"
        base = {"xlabel": "Frequency", "x_unit": "Hz", "log_x": log_x}
        for name, values in traces.items():  # the raw measurement: hidden at first
            ctx.emit_trace(name, freq, values, kind="complex", hidden=True, **base)
        result = compute_results(freq, traces, p)
        limits = parse_limits(p.get("limits"))
        meta = dict(base, ylabel="Loss (dB)")
        if not limits.empty:
            meta["limits"] = {"view": "value", **limits.lines(freq)}
        ctx.emit_trace("loss_db", freq, result["loss_db"], **meta)
        if "loss_db_per_m" in result:
            ctx.emit_trace(
                "loss_db_per_m",
                freq,
                result["loss_db_per_m"],
                hidden=True,
                **dict(base, ylabel="Loss (dB/m)"),
            )
        ctx.emit_trace(
            "group_delay_ns",
            freq,
            [d * 1e9 for d in result["delay_s"]],
            hidden=True,
            **dict(base, ylabel="Group delay (ns)"),
        )
        if "return_loss_db" in result:
            ctx.emit_trace(
                "return_loss_db",
                freq,
                result["return_loss_db"],
                hidden=True,
                **dict(base, ylabel="Return loss (dB)"),
            )
        for i, f in enumerate(freq):  # the whole sweep as a table, for the CSV export
            row = {"frequency_hz": f, "loss_db": result["loss_db"][i]}
            if "loss_db_per_m" in result:
                row["loss_db_per_m"] = result["loss_db_per_m"][i]
            row["group_delay_ns"] = result["delay_s"][i] * 1e9
            ctx.emit_point(row, table="sweep")
        summary = {"cable": cable.get("label", ""), **result["summary"]}
        if cable.get("length_m") and "velocity_factor" not in summary:
            ctx.log(
                "the group delay and the velocity factor could not be found: the phase changes "
                "too much between points. Use more points (the loss is not affected)",
                "warning",
            )
        if not limits.empty:
            verdict = limits.check(freq, result["loss_db"])
            summary["verdict"] = "PASS" if verdict.passed else "FAIL"
            summary["margin_db"] = verdict.margin
            ctx.log(f"limit check: {verdict.summary()}", "info" if verdict.passed else "warning")
        label = f" '{cable['label']}'" if cable.get("label") else ""
        top = result["summary"]
        worst = f"{top['max_loss_db']:.3g} dB at {format_si(top['max_loss_at_hz'], 'Hz')}"
        ctx.log(f"cable{label} ({mode}): worst loss {worst}")
        ctx.emit_point(summary)

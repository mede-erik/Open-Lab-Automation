"""What the measurements made with a VNA have in common (no Qt).

A VNA measurement (cable, return loss, filter, antenna...) checks the same sweep, asks the user
once to calibrate and connect, sets the sweep, reads S-parameters (several sweeps averaged) and
normalises what the instrument answered. The modules call these helpers, so each one is only about
what it measures::

    check_sweep(params, problems)         # start / stop / points / scale / IF bandwidth / power
    check_common(params, problems, ...)   # frequencies of interest, limits, averages, confirm_setup
    freq, traces = acquire(ctx, handle, sweep, ["S11"], averages)
    ask_setup(ctx, "Connect the antenna to port 1.", sweep)     # raises Stopped if the user aborts

The two logical calls asked of every VNA are described in ``docs/vna-calls.md``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .efficiency_spec import Problem
from .limits import LimitError, parse_limits
from .measurement import MeasurementContext, MeasurementError, Stopped
from .run_view import format_si

SCALES = ("linear", "log")
MAX_POINTS = 100_001
MAX_AVERAGES = 1000


def is_number(value: Any) -> bool:
    """True for a number that is not a bool and not NaN."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value


def frequency_label(f: float) -> str:
    """``433e6 -> "433MHz"``: for the names of result columns."""
    return format_si(f, "Hz").replace(" ", "")


# ----- checking the parameters -----------------------------------------------------------------
def check_sweep(
    params: Mapping[str, Any], out: List[Problem]
) -> Tuple[Optional[float], Optional[float]]:
    """Check ``params["sweep"]``; add the problems to ``out``. Returns ``(start, stop)`` in Hz,
    each None if it is not usable (so that later checks can skip what depends on them)."""
    sweep = params.get("sweep")
    if not isinstance(sweep, dict):
        out.append(Problem("sweep", "the sweep (start, stop, points) is missing"))
        return None, None
    start, stop = sweep.get("start_hz"), sweep.get("stop_hz")
    if not is_number(start) or start <= 0:
        out.append(Problem("sweep.start_hz", "the start frequency must be a number above 0 (Hz)"))
        start = None
    if not is_number(stop) or stop <= 0:
        out.append(Problem("sweep.stop_hz", "the stop frequency must be a number above 0 (Hz)"))
        stop = None
    if start is not None and stop is not None and start >= stop:
        out.append(Problem("sweep.stop_hz", "the stop frequency must be above the start frequency"))
    points = sweep.get("points")
    if not isinstance(points, int) or isinstance(points, bool) or not 2 <= points <= MAX_POINTS:
        text = f"the number of points must be a whole number from 2 to {MAX_POINTS}"
        out.append(Problem("sweep.points", text))
    if sweep.get("scale", "linear") not in SCALES:
        out.append(Problem("sweep.scale", f"must be one of {', '.join(SCALES)}"))
    if "if_bandwidth_hz" in sweep and (
        not is_number(sweep["if_bandwidth_hz"]) or sweep["if_bandwidth_hz"] <= 0
    ):
        out.append(
            Problem("sweep.if_bandwidth_hz", "the IF bandwidth must be a number above 0 (Hz)")
        )
    if "power_dbm" in sweep and not is_number(sweep["power_dbm"]):
        out.append(Problem("sweep.power_dbm", "the power must be a number (dBm)"))
    return start, stop


def check_asset(params: Mapping[str, Any], group: str, out: List[Problem]) -> None:
    """Check ``params[group]["asset_id"]``, the code of the cable or device from the registry
    (optional): it must be a code like ``CBL-0042``."""
    from .assets import normalize_code

    item = params.get(group)
    if isinstance(item, dict) and "asset_id" in item:
        value = item["asset_id"]
        if value not in (None, "") and not (isinstance(value, str) and normalize_code(value)):
            out.append(Problem(f"{group}.asset_id", "not a code (it looks like CBL-0042)"))


def apply_correction(
    ctx: MeasurementContext,
    params: Mapping[str, Any],
    freq: Sequence[float],
    s11: Sequence[complex],
    needs_phase: bool = False,
) -> Tuple[List[complex], Optional[Dict[str, Any]]]:
    """Take the cable named by ``params["correction"]`` out of a measured reflection (see
    ``ola.deembed``): ``(s11, None)`` untouched if there is no correction, else ``(corrected,
    info)`` and a line in the log, with a warning for each doubt. ``needs_phase``: the measurement
    uses the phase (an impedance), so a cable known only by its loss is an error."""
    from .deembed import DeembedError, corrected_reflection_for

    spec = (params.get("correction") or {}).get("cable")
    if not spec:
        return list(s11), None
    try:
        corrected, info = corrected_reflection_for(params, freq, s11)
    except DeembedError as exc:
        raise MeasurementError(f"cable correction: {exc}") from exc
    if needs_phase and info["mode"] != "complex":
        raise MeasurementError(
            "cable correction: the impedance needs the phase of the cable, which this cable "
            f"({info['source']}) does not have: measure it in transmission or use the "
            "return loss measurement, which corrects the VSWR with the loss alone"
        )
    name = info["code"] or info["source"]
    ctx.log(
        f"corrected for the cable {name} ({info['mode']}, {info['mean_one_way_loss_db']:.3g} dB "
        "one way on average)"
    )
    if info["over_unity_points"]:
        ctx.log(
            f"the correction makes the reflection exceed 1 at "
            f"{info['over_unity_points']} point(s): "
            "the cable data does not fit this measurement (another cable, or a calibration "
            "that is not at the same place); those points are limited just under 1",
            "warning",
        )
    for warning in info["warnings"]:
        ctx.log(f"cable {info['source']}: {warning}", "warning")
    return corrected, info


def apply_fixtures(
    ctx: MeasurementContext,
    params: Mapping[str, Any],
    freq: Sequence[float],
    traces: Mapping[str, Sequence[complex]],
) -> Tuple[Dict[str, List[complex]], Optional[Dict[str, Any]]]:
    """Take the fixtures named by ``params["correction"]`` out of the S-parameters of a transmission
    measurement (see ``ola.fixtures``): ``(traces, None)`` untouched if there is no correction,
    else ``(corrected, info)`` and a line in the log, with a warning for each doubt."""
    from .deembed import DeembedError
    from .fixtures import correct_traces

    if not params.get("correction"):
        return {k: list(v) for k, v in traces.items()}, None
    try:
        corrected, info = correct_traces(params, freq, traces)
    except DeembedError as exc:
        raise MeasurementError(f"fixture correction: {exc}") from exc
    parts = []
    for side, label in (("left", "port 1"), ("right", "port 2")):
        if side in info.get("sources", {}):
            name = info["codes"].get(side) or info["sources"][side]
            parts.append(f"{label}: {name} ({info[side + '_loss_db']:.3g} dB)")
    ctx.log(f"corrected for the fixtures, {'; '.join(parts)} ({info['model']}, {info['mode']})")
    if info["over_unity_points"]:
        ctx.log(
            f"the correction makes a reflection exceed 1 at {info['over_unity_points']} point(s): "
            "the fixture data does not fit this measurement (another cable, or a calibration "
            "that is not at the same place); those points are limited just under 1",
            "warning",
        )
    if info["gain_points"]:
        ctx.log(
            f"the device shows more than 0 dB of gain at {info['gain_points']} point(s) after the "
            "correction: right for an amplifier, otherwise the fixture data does not fit",
            "warning",
        )
    for warning in info["warnings"]:
        ctx.log(f"fixture: {warning}", "warning")
    return corrected, info


def check_common(
    params: Mapping[str, Any],
    out: List[Problem],
    start: Optional[float],
    stop: Optional[float],
    booleans: Sequence[str] = ("confirm_setup",),
) -> None:
    """Check the fields every VNA measurement has: ``frequencies_of_interest`` (inside the
    sweep), ``limits``, ``averages`` and the true / false ``booleans``."""
    wanted = params.get("frequencies_of_interest", [])
    if not isinstance(wanted, list) or not all(is_number(f) and f > 0 for f in wanted):
        out.append(Problem("frequencies_of_interest", "must be a list of frequencies above 0 (Hz)"))
    elif start is not None and stop is not None:
        outside = [f for f in wanted if not start <= f <= stop]
        if outside:
            shown = ", ".join(format_si(f, "Hz") for f in outside)
            text = f"outside the sweep ({shown}): nothing is measured there"
            out.append(Problem("frequencies_of_interest", text))
    try:
        parse_limits(params.get("limits"))
    except LimitError as exc:
        out.append(Problem("limits", str(exc)))
    averages = params.get("averages", 1)
    if (
        not isinstance(averages, int)
        or isinstance(averages, bool)
        or not 1 <= averages <= MAX_AVERAGES
    ):
        out.append(Problem("averages", f"must be a whole number from 1 to {MAX_AVERAGES}"))
    for key in booleans:
        if key in params and not isinstance(params[key], bool):
            out.append(Problem(key, "must be true or false"))


# ----- the sweep and the data -----------------------------------------------------------------
def sweep_frequencies(sweep: Mapping[str, Any]) -> List[float]:
    """The frequencies of a sweep: evenly spaced, or logarithmically spaced for ``scale: log``."""
    start, stop, n = float(sweep["start_hz"]), float(sweep["stop_hz"]), int(sweep["points"])
    if sweep.get("scale", "linear") == "log":
        ratio = (stop / start) ** (1 / (n - 1))
        return [start * ratio**k for k in range(n)]
    return [start + (stop - start) * k / (n - 1) for k in range(n)]


def as_trace(
    result: Any, fallback_freq: Sequence[float], what: str
) -> Tuple[List[float], List[complex]]:
    """Normalise what the VNA answered to ``(frequencies, complex values)``. Accepts
    ``{"frequency": [...], "values": [[re, im], ...]}`` or a plain list of complex numbers (or
    ``[re, im]`` pairs; the frequencies are then ``fallback_freq``). The message says what was
    wrong when it does not fit."""
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


LIBRARY_SWEEP = "set_frequency_sweep"
LIBRARY_READ = "read_sparameters"


def uses_library_calls(handle: Any) -> bool:
    """True if the instrument has the calls of the instrument library's network analyzer category
    (``set_frequency_sweep``, ``run_sweep``, ``read_sparameters``); else the two simple calls
    (``set_sweep`` and ``read_sparameter``, see ``docs/vna-calls.md``)."""
    supports = getattr(handle, "supports", None)
    return bool(callable(supports) and supports(LIBRARY_SWEEP) and supports(LIBRARY_READ))


def _has(handle: Any, call: str) -> bool:
    supports = getattr(handle, "supports", None)
    return bool(callable(supports) and supports(call))


def can_set_power(handle: Any) -> bool:
    """True if the source power of the VNA can be set: the simple calls do it with the sweep, the
    library's category has the optional ``set_source_power`` (not every instrument has it)."""
    return not uses_library_calls(handle) or _has(handle, "set_source_power")


def sweep_notes(handle: Any, sweep: Mapping[str, Any]) -> List[str]:
    """What of the sweep the instrument cannot do and will be left out: the library's category has
    a linear sweep only unless the instrument has ``set_sweep_type``, and the IF bandwidth and the
    source power are optional calls."""
    if not uses_library_calls(handle):
        return []
    notes = []
    if sweep.get("scale", "linear") == "log" and not _has(handle, "set_sweep_type"):
        notes.append("this VNA sweeps linearly: the logarithmic spacing is not used")
    if "if_bandwidth_hz" in sweep and not _has(handle, "set_if_bandwidth"):
        notes.append("this VNA has no IF bandwidth setting: it stays as it is on the instrument")
    if "power_dbm" in sweep and not _has(handle, "set_source_power"):
        notes.append("this VNA has no source power setting: it stays as it is on the instrument")
    return notes


def set_sweep(handle: Any, sweep: Mapping[str, Any]) -> None:
    """Send the sweep to the VNA. With the library's calls: ``set_sweep_type`` (if the instrument
    has it), ``set_if_bandwidth`` and ``set_source_power`` (the optional fields, if given and the
    instrument has them) and ``set_frequency_sweep``. Else ``set_sweep`` with the optional
    fields only if given."""
    if uses_library_calls(handle):
        if _has(handle, "set_sweep_type"):
            kind = "LOG" if sweep.get("scale", "linear") == "log" else "LINEAR"
            handle.call("set_sweep_type", sweep_type=kind)
        for key, call in (
            ("if_bandwidth_hz", "set_if_bandwidth"),
            ("power_dbm", "set_source_power"),
        ):
            if key in sweep and _has(handle, call):
                handle.call(call, value=float(sweep[key]))
        handle.call(
            LIBRARY_SWEEP,
            start_frequency=sweep["start_hz"],
            stop_frequency=sweep["stop_hz"],
            points=sweep["points"],
        )
        return
    extra = {
        name: sweep[key]
        for name, key in (("if_bandwidth", "if_bandwidth_hz"), ("power", "power_dbm"))
        if key in sweep
    }
    handle.call(
        "set_sweep",
        start_frequency=sweep["start_hz"],
        stop_frequency=sweep["stop_hz"],
        points=sweep["points"],
        sweep_type=sweep.get("scale", "linear"),
        **extra,
    )


def _library_sweep(
    handle: Any, parameters: Sequence[str], nominal: Sequence[float]
) -> Tuple[List[float], Dict[str, List[complex]], bool]:
    """Run one sweep with the library's calls and read the asked S-parameters:
    ``(frequencies, {parameter: values}, calibrated)``."""
    handle.call("run_sweep")
    result = handle.call(LIBRARY_READ, sparameters=list(parameters))
    if not isinstance(result, Mapping) or not isinstance(result.get("parameters"), Mapping):
        raise MeasurementError(
            f"the VNA gave no S-parameters (got {type(result).__name__}: expected frequency, "
            "parameters and calibrated)"
        )
    freq = [float(f) for f in result.get("frequency", nominal)]
    values: Dict[str, List[complex]] = {}
    for name in parameters:
        data = result["parameters"].get(name)
        if not isinstance(data, Mapping) or "real" not in data or "imaginary" not in data:
            have = ", ".join(sorted(result["parameters"])) or "none"
            raise MeasurementError(f"the VNA did not give {name} (it gave: {have})")
        real, imag = list(data["real"]), list(data["imaginary"])
        if not len(real) == len(imag) == len(freq):
            raise MeasurementError(
                f"the VNA gave {len(real)} + {len(imag)} values for {name} "
                f"at {len(freq)} frequencies"
            )
        values[name] = [complex(a, b) for a, b in zip(real, imag)]
    return freq, values, bool(result.get("calibrated", True))


def acquire(
    ctx: MeasurementContext,
    handle: Any,
    sweep: Mapping[str, Any],
    parameters: Sequence[str],
    averages: int = 1,
    notes: bool = True,
) -> Tuple[List[float], Dict[str, List[complex]]]:
    """Set the sweep, read the S-parameters ``parameters`` ``averages`` times, and return
    ``(frequencies, {parameter: mean values})``. Reports progress and honours Stop.

    An instrument with the library's calls reads all the parameters of one sweep together
    (``run_sweep``, then ``read_sparameters(sparameters=[...])``); one with the simple calls reads
    them one by one (``read_sparameter``). What the instrument cannot do (see ``sweep_notes``) is
    reported in the log (``notes=False`` for a sweep that is repeated many times), and so is a
    result that the instrument says is not calibrated."""
    library = uses_library_calls(handle)
    if notes:
        for note in sweep_notes(handle, sweep):
            ctx.log(note, "warning")
    set_sweep(handle, sweep)
    nominal = sweep_frequencies(sweep)
    totals: Dict[str, List[complex]] = {}
    freq: List[float] = []
    for sweep_no in range(1, averages + 1):
        ctx.checkpoint()
        if library:
            freq, got, calibrated = _library_sweep(handle, parameters, nominal)
            if not calibrated and sweep_no == 1 and notes:
                ctx.log(
                    "the VNA says its data are not calibrated: calibrate it (or apply its "
                    "calibration) before this measurement",
                    "warning",
                )
            reads = list(got.items())
        else:
            reads = []
            for name in parameters:
                ctx.checkpoint()
                freq, values = as_trace(
                    handle.call("read_sparameter", parameter=name), nominal, name
                )
                reads.append((name, values))
        for name, values in reads:
            if name in totals and len(totals[name]) != len(values):
                raise MeasurementError(f"the number of points of {name} changed between sweeps")
            totals[name] = (
                values if name not in totals else [a + b for a, b in zip(totals[name], values)]
            )
        ctx.progress(sweep_no, averages, f"sweep {sweep_no} of {averages}")
    return freq, {name: [v / averages for v in values] for name, values in totals.items()}


def ask_setup(ctx: MeasurementContext, connect: str, sweep: Mapping[str, Any], **data: Any) -> None:
    """Ask once whether the VNA is calibrated for this sweep and how to connect the device
    (``connect`` is that sentence). Raises ``Stopped`` if the user chooses to abort: nothing has
    been sent to the instrument yet."""
    text = (
        "Is the VNA calibrated for this device and this frequency range "
        f"({format_si(sweep['start_hz'], 'Hz')} to {format_si(sweep['stop_hz'], 'Hz')})? "
        f"{connect} Then continue."
    )
    info = {
        "kind": "calibration",
        "start_hz": sweep["start_hz"],
        "stop_hz": sweep["stop_hz"],
        "points": sweep["points"],
        **data,
    }
    if ctx.ask(text, ["continue", "abort"], default="abort", data=info) == "abort":
        raise Stopped()

"""Tests of the model behind the run window (no screen needed)."""

import pytest

from ola.measurement import Event
from ola.run_view import (
    QUESTION_GENERIC,
    QUESTION_OUTPUTS_ON,
    QUESTION_VERIFY,
    RunModel,
    nice_ticks,
    question_kind,
)


def ev(kind, t=0.0, **data):
    return Event(kind, data, t=t)


def point(t, **values):
    return ev("point", t, table="points", index=0, elapsed_s=t, values=values)


def test_state_and_end():
    m = RunModel()
    assert m.state == "idle" and not m.finished
    m.apply(ev("state", 1.0, state="running", run_id="abc"))
    assert m.state == "running" and m.run_id == "abc"
    m.apply(ev("state", 5.0, state="finished"))
    assert m.finished and m.elapsed() == 4.0


def test_points_columns_in_order_of_appearance_and_other_tables():
    m = RunModel()
    m.apply(point(0, vin=9, eff=90))
    m.apply(point(1, vin=12, eff=91, extra=1))
    m.apply(ev("point", 2, table="samples", index=0, elapsed_s=2, values={"s": 1}))
    assert m.columns == ["vin", "eff", "extra"]
    assert len(m.points) == 2 and len(m.tables["samples"]) == 1


def test_progress_fraction_and_remaining_time():
    m = RunModel()
    m.apply(ev("state", 0.0, state="running"))
    assert m.fraction is None and m.remaining() is None
    m.apply(ev("progress", 10.0, done=1, total=4, message="point 1 of 4"))
    assert m.fraction == 0.25 and m.message == "point 1 of 4"
    assert m.remaining() == pytest.approx(30.0)  # 10 s for a quarter
    m.apply(ev("state", 40.0, state="finished"))
    assert m.remaining() is None


def test_time_waiting_for_the_user_is_not_counted_in_the_estimate():
    m = RunModel()
    m.apply(ev("state", 0.0, state="running"))
    m.apply(ev("question", 5.0, id="q", text="?", choices=["a"], default="a", data={}))
    m.apply(ev("answered", 65.0, id="q", choice="a", auto=False))  # 60 s of waiting
    m.apply(ev("progress", 70.0, done=1, total=2))
    assert m.waited_s == 60.0
    assert m.remaining() == pytest.approx(10.0)  # 70 - 60 = 10 s of work for half


def test_questions_open_and_answered():
    m = RunModel()
    q = dict(id="q1", text="Mismatch", choices=["retry", "abort"], default="abort", data={})
    m.apply(ev("question", 1.0, **q))
    assert list(m.pending) == ["q1"]
    m.apply(ev("answered", 2.0, id="q1", choice="retry", auto=False))
    assert not m.pending and m.answers[0]["choice"] == "retry"


def test_question_kinds():
    assert question_kind({"data": {"set_value": 1, "read_value": 2}}) == QUESTION_VERIFY
    assert question_kind({"data": {"outputs": []}}) == QUESTION_OUTPUTS_ON
    assert question_kind({"data": {}}) == QUESTION_GENERIC
    assert question_kind({}) == QUESTION_GENERIC


def test_log_and_error_are_listed():
    m = RunModel()
    m.apply(ev("log", 1.0, level="warning", message="careful"))
    m.apply(ev("error", 2.0, message="boom", phase="run"))
    assert [(lvl, msg) for _, lvl, msg in m.logs] == [("warning", "careful"), ("error", "boom")]
    assert m.error["phase"] == "run"


def _sweep_model():
    m = RunModel()
    for iout in (0.5, 1.0):
        for vin in (12, 9, 15):  # not in order: lines must be sorted by x
            m.apply(
                point(
                    0,
                    vin=vin,
                    iout=iout,
                    **{"vin@daq": vin + 0.01},
                    efficiency=90 + vin / iout,
                    note="x",
                )
            )
    return m


def test_series_are_grouped_and_sorted():
    m = _sweep_model()
    lines = m.series("vin", "efficiency", group_by=["iout"])
    assert [label for label, _, _ in lines] == ["iout=0.5", "iout=1"]
    assert lines[0][1] == [9.0, 12.0, 15.0]
    assert m.series("vin", "efficiency")[0][0] == "efficiency"  # one line, no grouping


def test_text_columns_are_not_plottable():
    m = _sweep_model()
    assert "note" not in m.numeric_columns()
    assert m.series("vin", "note") == []


def test_suggested_axes():
    m = _sweep_model()
    assert m.suggest_axes() == ("vin", "efficiency", "iout")
    assert RunModel().suggest_axes() == (None, None, None)


def test_nice_ticks():
    assert nice_ticks(0, 10, 6) == [0, 2, 4, 6, 8, 10]
    ticks = nice_ticks(88.3, 91.7, 5)
    assert ticks[0] >= 88.3 - 1e-9 and ticks[-1] <= 91.7 + 1e-9 and len(ticks) >= 3
    assert len(nice_ticks(5, 5)) >= 2  # a flat line still gets an axis
    assert nice_ticks(float("nan"), 1) == []
    noisy = nice_ticks(90.0, 90.0 + 1e-14, 6)  # a constant result with rounding noise
    assert len(noisy) >= 3 and noisy[0] < 90 < noisy[-1]


def test_format_duration():
    assert RunModel.format_duration(None) == "-"
    assert RunModel.format_duration(75) == "1 min 15 s"
    assert RunModel.format_duration(3725) == "1 h 02 min"
    assert RunModel.format_duration(7) == "7 s"


# ---- traces -------------------------------------------------------------------------------------
from ola.run_view import trace_views, trace_xy  # noqa: E402


def trace_event(name, y, kind="real", t=0.0):
    return ev("trace", t, name=name, trace_kind=kind, x=[1.0, 2.0], y=y, meta={"unit": "dB"})


def test_traces_keep_the_latest_of_each_name_in_order_of_appearance():
    m = RunModel()
    m.apply(trace_event("S21", [[0.5, 0.0], [0.4, 0.0]], "complex"))
    m.apply(trace_event("temp", [20.0, 21.0]))
    m.apply(trace_event("S21", [[0.9, 0.0], [0.8, 0.0]], "complex"))  # a repeated sweep
    assert m.trace_order == ["S21", "temp"]
    assert m.traces["S21"]["y"] == [0.9 + 0j, 0.8 + 0j] and m.traces["S21"]["count"] == 2
    assert m.traces["temp"]["meta"] == {"unit": "dB"}


def test_views_of_a_complex_trace():
    m = RunModel()
    m.apply(trace_event("S21", [[0.5, 0.0], [0.0, 0.1]], "complex"))
    trace = m.traces["S21"]
    assert trace_views("complex")[0] == "magnitude_db" and trace_views("real") == ["value"]
    x, y = trace_xy(trace, "magnitude_db")
    assert x == [1.0, 2.0] and y == [pytest.approx(-6.0206, abs=1e-3), pytest.approx(-20)]
    assert trace_xy(trace, "loss_db")[1] == [pytest.approx(6.0206, abs=1e-3), pytest.approx(20)]
    assert trace_xy(trace, "real")[1] == [0.5, 0.0] and trace_xy(trace, "imag")[1] == [0.0, 0.1]
    assert trace_xy(trace, "phase_deg")[1] == [pytest.approx(0), pytest.approx(90)]
    assert trace_xy(trace, "smith") == ([0.5, 0.0], [0.0, 0.1])  # the plane, not the frequency
    with pytest.raises(ValueError):
        trace_xy(trace, "nonsense")


def test_a_real_trace_has_one_view():
    m = RunModel()
    m.apply(trace_event("temp", [20.0, 21.0]))
    assert trace_xy(m.traces["temp"], "value") == ([1.0, 2.0], [20.0, 21.0])


def test_log_ticks():
    from ola.run_view import log_ticks

    assert log_ticks(1e6, 1e9) == [1e6, 2e6, 5e6, 1e7, 2e7, 5e7, 1e8, 2e8, 5e8, 1e9]
    assert log_ticks(1e3, 1e10) == [10.0**k for k in range(3, 11)]  # wide: decades only
    narrow = log_ticks(2e6, 5e6)
    assert narrow[0] == 2e6 and 3e6 in narrow and narrow[-1] == 5e6
    assert log_ticks(0, 10) == [] and log_ticks(-1, 10) == []
    assert log_ticks(1e9, 1e6) == log_ticks(1e6, 1e9)


def test_format_si():
    from ola.run_view import format_si

    assert format_si(1.5e6) == "1.5 M" and format_si(2e9, "Hz") == "2 GHz"
    assert format_si(5e-4, "s") == "500 us" and format_si(0, "Hz") == "0 Hz"
    assert format_si(999e6, "Hz") == "999 MHz" and format_si(1e3, "Hz") == "1 kHz"

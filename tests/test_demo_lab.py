"""The demo lab must really run an efficiency measurement (the demo window depends on it)."""

from ola.demo_lab import INSTRUMENTS, DemoHandle, DemoLab, demo_params
from ola.registry import default_registry
from ola.runner import Runner, RunState


def run(lab, **kw):
    registry = default_registry(user_dir="/nonexistent")
    m = registry.create("efficiency", demo_params())
    runner = Runner(m, {"instruments": [DemoHandle(n, lab) for n in INSTRUMENTS]}, **kw)
    runner.start()
    assert runner.join(20)
    return runner


def test_demo_run_gives_90_percent_efficiency():
    runner = run(DemoLab())
    assert runner.state is RunState.FINISHED
    points = [
        e.data["values"]
        for e in runner.drain()
        if e.kind == "point" and e.data["table"] == "points"
    ]
    assert len(points) == 9
    assert all(abs(p["efficiency"] - 90.0) < 0.5 for p in points)


def test_demo_logger_error_asks_a_question():
    runner = run(DemoLab(vin_error=0.2), unattended="abort")
    assert runner.state is RunState.STOPPED
    assert any(e.kind == "question" for e in runner.drain())

#!/usr/bin/env python3
# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Make a demo project with a finished efficiency run that has waveforms, with no hardware.

The run is made with the simulated converter and oscilloscope (``ola/demo_lab.py``,
``ola/sim_scope.py``): every step takes a capture for each of the scope settings files ``long.was``
and ``rise.was``. Open the project in the program (Project > Open, the file ``demo.json`` in the
folder) and look at the run in the *Measurements* tab: select the run, then *Waveforms...*.

Example:
    python3 scripts/make_demo_project.py /tmp/demo
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ola.demo_lab import INSTRUMENTS, DemoHandle, DemoLab, demo_params  # noqa: E402
from ola.project import MeasurementFile, Project  # noqa: E402
from ola.project_session import ProjectSession  # noqa: E402
from ola.registry import default_registry  # noqa: E402
from ola.runner import RunState  # noqa: E402
from ola.sim_scope import SimScope  # noqa: E402

LONG = {
    "settings": {"time_per_div": 1e-3},
    "channels": [
        {"channel_id": "CH1", "enabled": True, "volt_per_div": "2V"},
        {"channel_id": "CH2", "enabled": True, "volt_per_div": "2V"},
    ],
    "trigger": {"source": "CH1", "level": 1.0, "slope": "RISE", "mode": "AUTO"},
}
RISE = {"settings": {"time_per_div": 1e-6}, "channels": [{"channel_id": "CH1", "enabled": True}]}


def make(folder: Path, depth: int = 5000, every: int = 1) -> Path:
    """Build the project in ``folder`` and run it once; return the run file."""
    folder.mkdir(parents=True, exist_ok=True)
    registry = default_registry(user_dir="/nonexistent")
    lab = DemoLab()
    # a slow, large ripple so that it can be seen in the 10 ms of the "long" capture
    scope = SimScope(
        name="osc1", dc_v=5.0, ripple_pp_v=0.5, fsw_hz=1000.0, spike_v=0.3, default_depth=depth
    )

    def connect(name, cancel=None):
        return scope if name == "osc1" else DemoHandle(name, lab)

    session = ProjectSession(
        Project.new("Demo", folder), registry, connect=connect, instruments=INSTRUMENTS + ["osc1"]
    )
    ref = session.create("efficiency", "Efficiency")
    params = demo_params(samples=1, interval_s=0.0)
    params["scope_capture"] = {"instruments": ["osc1"], "every": every, "wait_s": 0.0}
    MeasurementFile(
        type="efficiency",
        role_bindings={"instruments": INSTRUMENTS, "scope": ["osc1"]},
        params=params,
    ).save(session.path(ref))
    for name, content in (("long.was", LONG), ("rise.was", RISE)):
        (folder / name).write_text(json.dumps(content, indent=2), encoding="utf-8")
        session.project.add_scope_file(name)
    session.project.save()
    runner, path = session.build_runner(ref)
    runner.start()
    if not runner.join(120) or runner.state is not RunState.FINISHED:
        raise SystemExit(f"the demo run did not finish: {runner.state}")
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", help="the folder of the new project (made if needed)")
    parser.add_argument("--depth", type=int, default=5000, help="samples of each capture")
    parser.add_argument("--every", type=int, default=1, help="one capture every N steps")
    args = parser.parse_args(argv)
    path = make(Path(args.folder), args.depth, args.every)
    print(f"project: {Path(args.folder) / 'demo.json'}\nrun: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

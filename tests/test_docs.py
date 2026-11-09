# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Keeps the documentation honest: it fails when the code and the docs drift apart.

* every public module / class / function of ``ola/`` has a docstring;
* every module of ``ola/`` appears in the README table of the engine;
* the error codes of the transport are documented in ERROR_CODES.md;
* the relative links of the README and of ``docs/`` point to existing files;
* the example module written in ``docs/measurement-modules.md`` really works.
"""

import ast
import json
import re
from pathlib import Path

import pytest

from ola.registry import ModuleRegistry
from ola.runner import Runner, RunState
from tests.measurement_helpers import FakeHandle, run_to_end

ROOT = Path(__file__).resolve().parent.parent
OLA = ROOT / "ola"
DOCS = sorted((ROOT / "docs").glob("*.md"))


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def public_items_without_docstring():
    missing = []
    for path in sorted(OLA.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        tree = ast.parse(read(path))
        if not ast.get_docstring(tree):
            missing.append(f"{rel}: module")

        def visit(node, in_function):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    is_setter = any(
                        isinstance(d, ast.Attribute) and d.attr == "setter"
                        for d in getattr(child, "decorator_list", [])
                    )
                    public = not child.name.startswith("_")
                    if (
                        public
                        and not in_function
                        and not is_setter
                        and not ast.get_docstring(child)
                    ):
                        missing.append(f"{rel}:{child.lineno} {child.name}")
                    if public:  # the inside of a private class or function is not public API
                        visit(child, in_function or not isinstance(child, ast.ClassDef))
                else:
                    visit(child, in_function)

        visit(tree, False)
    return missing


def test_public_items_have_docstrings():
    assert public_items_without_docstring() == []


def test_every_ola_module_is_in_the_readme():
    readme = read(ROOT / "README.md")
    absent = [
        p.name for p in sorted(OLA.glob("*.py")) if p.name != "__init__.py" and p.name not in readme
    ]
    assert absent == [], f"add these files to the 'Engine' table of README.md: {absent}"
    for module_dir in sorted((OLA / "modules").iterdir()):
        if (module_dir / "module.json").exists():
            assert f"ola/modules/{module_dir.name}" in readme or module_dir.name in readme


def test_transport_error_codes_are_documented():
    text = read(ROOT / "ERROR_CODES.md")
    for n in range(1, 7):
        assert f"TRN-00{n}" in text, f"TRN-00{n} missing from ERROR_CODES.md"


def test_call_error_codes_are_documented_once_the_section_exists():
    text = read(ROOT / "ERROR_CODES.md")
    if "CALL-" not in text:
        pytest.skip("the CALL section of ERROR_CODES.md has not been added yet")
    codes = set(re.findall(r'code = "(CALL-\d{3})"', read(OLA / "call_errors.py")))
    codes.discard("CALL-000")
    assert codes, "no CALL codes found in ola/call_errors.py"
    assert [c for c in sorted(codes) if c not in text] == []


@pytest.mark.parametrize("doc", [ROOT / "README.md", *DOCS], ids=lambda p: p.name)
def test_relative_links_resolve(doc):
    broken = []
    for target in re.findall(r"\]\(([^)\s]+)\)", read(doc)):
        if re.match(r"^[a-z]+:", target) or target.startswith("#"):
            continue
        path = target.split("#", 1)[0]
        if path and not (doc.parent / path).exists():
            broken.append(target)
    assert broken == [], f"broken links in {doc.name}: {broken}"


def test_docs_exist():
    assert {p.name for p in DOCS} >= {
        "engine.md",
        "measurement-modules.md",
        "instrument-calls.md",
    }


# ---- the example module of docs/measurement-modules.md must work --------------------------------


def doc_example_files(tmp_path):
    text = read(ROOT / "docs" / "measurement-modules.md")
    blocks = dict(
        re.findall(r"```(?:json|python) (module\.json|measurement\.py)\n(.*?)```", text, re.S)
    )
    assert set(blocks) == {"module.json", "measurement.py"}, "example blocks not found in the doc"
    folder = tmp_path / "dc_check"
    folder.mkdir()
    for name, body in blocks.items():
        (folder / name).write_text(body, encoding="utf-8")
    json.loads(blocks["module.json"])  # valid JSON
    return tmp_path


def make_psu():
    state = {"v": 0.0}

    def set_v(value):
        state["v"] = value

    return FakeHandle(
        "psu1",
        {
            "set_voltage": set_v,
            "read_voltage": lambda: state["v"],
            "output_on": None,
            "output_off": None,
        },
    )


def test_doc_example_module_runs(tmp_path):
    registry = ModuleRegistry([(doc_example_files(tmp_path), False)])
    registry.discover()
    assert registry.problems == [] and [m.id for m in registry.list()] == ["dc_check"]
    psu = make_psu()
    m = registry.create("dc_check", {"voltages": [1, 2.5], "settle_s": 0}, allow_user_code=True)
    runner = run_to_end(Runner(m, {"psu": [psu]}))
    assert runner.state is RunState.FINISHED
    points = [e.data["values"] for e in runner.drain() if e.kind == "point"]
    assert points == [{"set_v": 1, "read_v": 1}, {"set_v": 2.5, "read_v": 2.5}]
    assert psu.calls[-1] == ("output_off", {})


def test_doc_example_switches_off_after_an_error_and_validates(tmp_path):
    registry = ModuleRegistry([(doc_example_files(tmp_path), False)])
    registry.discover()
    psu = FakeHandle(
        "psu1", {"output_on": None, "output_off": None, "set_voltage": None}, fail_on="read_voltage"
    )
    m = registry.create("dc_check", {"voltages": [1], "settle_s": 0}, allow_user_code=True)
    runner = run_to_end(Runner(m, {"psu": [psu]}))
    assert runner.state is RunState.FAILED and psu.calls[-1] == ("output_off", {})
    bad = registry.create("dc_check", {"voltages": []}, allow_user_code=True)
    assert bad.validate() == ["voltages must be a non-empty list"]


def test_efficiency_guide_example_is_valid_and_has_the_documented_order():
    import json as _json

    from ola.efficiency_spec import parse_params, validate_params
    from ola.sweep import iter_points

    text = read(ROOT / "docs" / "efficiency.md")
    block = re.search(r"```json efficiency\.eff\n(.*?)```", text, re.S)
    assert block, "example block not found in docs/efficiency.md"
    params = _json.loads(block.group(1))
    bound = ["psu1", "psu2", "daq1", "load1"]
    found = validate_params(params, bound)
    assert [str(p) for p in found if p.severity == "error"] == []
    # the one thing worth a warning in the example: the always-on auxiliary supply
    warned = [p.path for p in found if p.severity == "warning"]
    assert warned == ["variables[2].output"], warned
    spec = parse_params(params, bound)
    points = list(iter_points(spec.axes))
    assert [(p["vin"], p["iout"]) for p in points[:4]] == [(9, 0.5), (9, 1.5), (9, 2.5), (12, 0.5)]
    assert spec.timing.cooldown_s == 600 and spec.cooldown_count() == 2
    assert spec.power_order == ["vin", "iout"]  # the supply first, then the load
    assert spec.variables["vaux"].output.mode == "always_on" and spec.variables["vaux"].output.state


def test_cable_example_in_the_docs_is_valid_and_runs():
    """The example of docs/cable.md is a real file: it validates and gives the verdict it says."""
    import json as _json

    from ola.registry import default_registry
    from ola.runner import Runner
    from ola.sim_vna import SimVna

    text = read(ROOT / "docs" / "cable.md")
    block = re.search(r"```json cable\.cbl\n(.*?)```", text, re.S)
    assert block, "example block not found in docs/cable.md"
    params = _json.loads(block.group(1))
    m = default_registry(user_dir="/nonexistent").create("cable", params)
    assert m.check() == [], [str(p) for p in m.check()]
    params["confirm_setup"] = False
    m = default_registry(user_dir="/nonexistent").create("cable", params)
    runner = Runner(m, {"vna": [SimVna(length_m=2.0)]})
    runner.start()
    assert runner.join(20) and runner.state.value == "finished", runner.error
    row = [
        e.data["values"]
        for e in runner.drain()
        if e.kind == "point" and e.data["table"] == "points"
    ][0]
    assert row["verdict"] == "PASS" and row["cable"] == "RG58 #3" and "min_return_loss_db" in row


def test_return_loss_example_in_the_docs_is_valid_and_runs():
    """The example of docs/return-loss.md is a real file: it validates and gives its verdict."""
    import json as _json

    from ola.registry import default_registry
    from ola.runner import Runner
    from ola.sim_vna import SimVna

    text = read(ROOT / "docs" / "return-loss.md")
    block = re.search(r"```json return_loss\.rtl\n(.*?)```", text, re.S)
    assert block, "example block not found in docs/return-loss.md"
    params = _json.loads(block.group(1))
    m = default_registry(user_dir="/nonexistent").create("return_loss", params)
    assert m.check() == [], [str(p) for p in m.check()]
    params["confirm_setup"] = False
    m = default_registry(user_dir="/nonexistent").create("return_loss", params)
    runner = Runner(m, {"vna": [SimVna(termination="antenna")]})
    runner.start()
    assert runner.join(20) and runner.state.value == "finished", runner.error
    rows = [
        e.data["values"]
        for e in runner.drain()
        if e.kind == "point" and e.data["table"] == "points"
    ]
    assert rows[0]["verdict"] == "PASS" and rows[0]["usable_band_count"] == 1


def test_the_vna_contract_in_the_docs_matches_the_library_and_the_simulated_vna():
    """docs/vna-calls.md names the calls of the library's category and of the simple contract:
    the library defines the first, SimVna answers both."""
    import json as _json

    from ola.sim_vna import SimVna
    from ola.vna_common import uses_library_calls

    text = read(ROOT / "docs" / "vna-calls.md")
    names = (
        "set_frequency_sweep", "run_sweep", "read_sparameters", "set_if_bandwidth",
        "set_source_power", "set_sweep", "read_sparameter", "network_analyzers_series",
        "calibrated",
    )  # fmt: skip
    for name in names:
        assert name in text, name
    assert "vnas_series" not in text
    schema = ROOT / "Instruments_LIB" / "schema" / "vna.json"
    if schema.is_file():
        library = _json.loads(schema.read_text(encoding="utf-8"))
        assert library["category"] == "network_analyzers_series"
        for call in ("set_frequency_sweep", "run_sweep", "read_sparameters"):
            assert call in library["calls"], call
        if "set_source_power" in library["calls"]:  # the newer version of the category
            assert "select_sparameters" not in library["calls"]
            assert "args" in library["calls"]["read_sparameters"]
    simple = SimVna()
    assert not uses_library_calls(simple)
    simple.call("set_sweep", start_frequency=1e6, stop_frequency=2e6, points=5, sweep_type="linear")
    answer = simple.call("read_sparameter", parameter="S21")
    assert set(answer) == {"frequency", "values"} and len(answer["frequency"]) == 5
    lib = SimVna(library_calls=True)
    assert uses_library_calls(lib)
    lib.call("set_frequency_sweep", start_frequency=1e6, stop_frequency=2e6, points=5)
    lib.call("run_sweep")
    got = lib.call("read_sparameters", sparameters=["S21"])
    assert set(got) == {"frequency", "parameters", "calibrated"} and len(got["frequency"]) == 5
    assert set(got["parameters"]["S21"]) == {"real", "imaginary"}


def test_filter_example_in_the_docs_is_valid_and_runs():
    """The example of docs/filter.md is a real file: it validates and gives its verdict."""
    import json as _json

    from ola.registry import default_registry
    from ola.runner import Runner
    from ola.sim_vna import SimVna

    text = read(ROOT / "docs" / "filter.md")
    block = re.search(r"```json filter\.flt\n(.*?)```", text, re.S)
    assert block, "example block not found in docs/filter.md"
    params = _json.loads(block.group(1))
    m = default_registry(user_dir="/nonexistent").create("filter", params)
    assert m.check() == [], [str(p) for p in m.check()]
    params["confirm_setup"] = False
    m = default_registry(user_dir="/nonexistent").create("filter", params)
    vna = SimVna(filter_type="bandpass", filter_f0_hz=868e6, filter_bw_hz=20e6, filter_order=3)
    runner = Runner(m, {"vna": [vna]})
    runner.start()
    assert runner.join(20) and runner.state.value == "finished", runner.error
    rows = [
        e.data["values"]
        for e in runner.drain()
        if e.kind == "point" and e.data["table"] == "points"
    ]
    row = rows[0]
    assert row["verdict"] == "PASS" and row["type"] == "bandpass" and "q_factor" in row
    assert abs(row["center_hz"] - 868e6) < 0.001 * 868e6


def test_simulated_vna_takes_the_sweep_types_the_planner_takes():
    """The planner upper-cases an enum and applies the aliases: SimVna must accept the same."""
    import pytest

    from ola.sim_vna import SimVna

    for spelling in ("linear", "LINEAR", " Linear ", "LIN", "log", "LOG", "LOGARITHMIC"):
        vna = SimVna()
        vna.call(
            "set_sweep", start_frequency=1e6, stop_frequency=1e9, points=5, sweep_type=spelling
        )
        assert len(vna.call("read_sparameter", parameter="S21")["frequency"]) == 5
    log = SimVna()
    log.call(
        "set_sweep", start_frequency=1e6, stop_frequency=1e9, points=4, sweep_type="LOGARITHMIC"
    )
    freq = log.call("read_sparameter", parameter="S21")["frequency"]
    assert freq[1] / freq[0] == pytest.approx(10.0)  # spaced by a ratio: it really is logarithmic
    with pytest.raises(ValueError, match="unknown sweep type"):
        SimVna().call(
            "set_sweep", start_frequency=1e6, stop_frequency=1e9, points=5, sweep_type="decade"
        )


def test_antenna_example_in_the_docs_is_valid_and_runs():
    """The example of docs/antenna.md is a real file: it validates and gives its figures."""
    import json as _json

    from ola.registry import default_registry
    from ola.runner import Runner
    from ola.sim_vna import SimVna

    text = read(ROOT / "docs" / "antenna.md")
    block = re.search(r"```json antenna\.ant\n(.*?)```", text, re.S)
    assert block, "example block not found in docs/antenna.md"
    params = _json.loads(block.group(1))
    m = default_registry(user_dir="/nonexistent").create("antenna", params)
    assert m.check() == [], [str(p) for p in m.check()]
    params["confirm_setup"] = False
    m = default_registry(user_dir="/nonexistent").create("antenna", params)
    runner = Runner(m, {"vna": [SimVna(termination="antenna")]})
    runner.start()
    assert runner.join(20) and runner.state.value == "finished", runner.error
    rows = [
        e.data["values"]
        for e in runner.drain()
        if e.kind == "point" and e.data["table"] == "points"
    ]
    row = rows[0]
    assert row["verdict"] == "PASS" and row["series_resonance_count"] == 1
    assert abs(row["series_resonance_hz"] - 868e6) < 1e6 and row["cancel_840MHz"].startswith(
        "series inductor"
    )


def test_amplifier_example_in_the_docs_is_valid_and_runs():
    """The example of docs/amplifier.md is a real file: it validates and gives its figures."""
    import json as _json

    from ola.registry import default_registry
    from ola.runner import Runner
    from ola.sim_vna import SimAmplifier

    text = read(ROOT / "docs" / "amplifier.md")
    block = re.search(r"```json amplifier\.amp\n(.*?)```", text, re.S)
    assert block, "example block not found in docs/amplifier.md"
    params = _json.loads(block.group(1))
    m = default_registry(user_dir="/nonexistent").create("amplifier", params)
    assert m.check() == [], [str(p) for p in m.check()]
    params["confirm_setup"] = False
    m = default_registry(user_dir="/nonexistent").create("amplifier", params)
    vna = SimAmplifier()
    runner = Runner(m, {"vna": [vna]})
    runner.start()
    assert runner.join(30) and runner.state.value == "finished", runner.error
    rows = [
        e.data["values"]
        for e in runner.drain()
        if e.kind == "point" and e.data["table"] == "points"
    ]
    row = rows[0]
    assert row["verdict"] == "PASS" and row["unconditionally_stable"] == "yes"
    assert abs(row["p1db_input_dbm"] - vna.p1db_input_dbm) < 0.5


def test_compare_doc_names_the_things_the_window_really_has():
    """docs/compare.md names buttons and modes: each must exist in the window's strings."""
    import json as _json

    text = read(ROOT / "docs" / "compare.md")
    strings = _json.loads(read(ROOT / "frontend" / "lang" / "modules" / "compare" / "en.json"))
    for key in ("cmp_add", "cmp_rename", "cmp_reference", "cmp_export_csv", "cmp_save_image"):
        assert strings[key].rstrip(".") in text, (key, strings[key])
    assert strings["cmp_mode_overlay"].lower() in text.lower()
    assert "Difference from the reference" in text and strings["cmp_mode_difference"] in text
    assert "python -m frontend.ui.CompareDialog" in text


def test_assets_doc_matches_the_code():
    """docs/assets.md states prefixes, formats and file names: they must be the ones in the code."""
    from ola.assets import ENV_FILE, KINDS
    from ola.labels import PRESETS, SHEETS

    text = read(ROOT / "docs" / "assets.md")
    for kind, info in KINDS.items():
        assert f"`{info['prefix']}`" in text, kind
    assert ENV_FILE in text and "assets.json.bak" in text and "OLA:CBL-0042" in text
    for name in ("50 x 25", "40 x 20", "62 x 29", "70 x 37", "60 x 15"):
        assert name in text, name
    for sheet in SHEETS:
        grid = re.search(r"A4 (\d+x\d+)", sheet).group(1).replace("x", " x ")
        assert grid in text, sheet
    assert all(s in PRESETS for s in ("50x25", "40x20", "62x29", "70x37", "flag 60x15"))
    assert "pip install segno" in text and "segno" in read(ROOT / "requirements.txt")


def test_attenuator_example_in_the_docs_is_valid_and_runs():
    """The example of docs/attenuator.md is a real file: it validates and gives its verdict."""
    import json as _json

    from ola.registry import default_registry
    from ola.runner import Runner
    from ola.sim_vna import SimVna

    text = read(ROOT / "docs" / "attenuator.md")
    block = re.search(r"```json attenuator\.att\n(.*?)```", text, re.S)
    assert block, "example block not found in docs/attenuator.md"
    params = _json.loads(block.group(1))
    m = default_registry(user_dir="/nonexistent").create("attenuator", params)
    assert m.check() == [], [str(p) for p in m.check()]
    params["confirm_setup"] = False
    m = default_registry(user_dir="/nonexistent").create("attenuator", params)
    runner = Runner(m, {"vna": [SimVna(attenuator_db=10.2, attenuator_slope_db_per_ghz=0.05)]})
    runner.start()
    assert runner.join(20) and runner.state.value == "finished", runner.error
    rows = [
        e.data["values"]
        for e in runner.drain()
        if e.kind == "point" and e.data["table"] == "points"
    ]
    row = rows[0]
    assert row["verdict"] == "PASS" and "attenuation_433MHz_db" in row
    assert abs(row["mean_attenuation_db"] - 10.275) < 0.02
    for name in ("`attenuator.asset_id`", "ATT-0007"):
        assert name in text


def test_ripple_example_in_the_docs_is_valid_and_runs():
    """The example of docs/ripple.md is a real file: it validates and runs on the simulation."""
    import json as _json

    from ola.registry import default_registry
    from ola.runner import Runner
    from ola.sim_scope import SimLoad, SimScope

    text = read(ROOT / "docs" / "ripple.md")
    block = re.search(r"```json ripple\.rpl\n(.*?)```", text, re.S)
    assert block, "example block not found in docs/ripple.md"
    params = _json.loads(block.group(1))
    m = default_registry(user_dir="/nonexistent").create("ripple", params)
    assert m.check() == [], [str(p) for p in m.check()]
    scope = SimScope(ripple_pp_v=0.010, ripple_per_a_v=0.010, noise_rms_v=0.0005)
    runner = Runner(m, {"oscilloscope": [scope], "load": [SimLoad(scope)]})
    runner.start()
    assert runner.join(60) and runner.state.value == "finished", runner.error
    rows = [
        e.data["values"]
        for e in runner.drain()
        if e.kind == "point" and e.data["table"] == "points"
    ]
    assert [r["load_current_a"] for r in rows] == [0.0, 1.0, 2.0]
    assert [r["verdict"] for r in rows] == ["PASS", "PASS", "PASS"]
    assert rows[0]["captures"] == 3 and rows[2]["pp_v"] > rows[0]["pp_v"]
    assert abs(rows[1]["ripple_frequency_hz"] - 500e3) < 5e3
    for name in ("max_pp_v", "max_rms_v", "set_acquisition_depth", "read_waveform_full"):
        assert name in text


def test_wiring_doc_matches_the_code():
    """docs/wiring.md: its example is a valid file and the window and fields it names exist."""
    import json as _json

    from ola.wiring import diagram_for

    text = read(ROOT / "docs" / "wiring.md")
    block = re.search(r"```json\n(.*?)```", text, re.S)
    assert block, "example block not found in docs/wiring.md"
    diagram = diagram_for(_json.loads(block.group(1)), {"filter": {"label": "SAW"}}, {"vna": ["V"]})
    assert diagram.node("dut").title == "SAW" and len(diagram.links) == 2
    assert diagram.node("vna").subtitle == "V"
    for name in ("Show this before each measurement", "Connections...", "Save SVG..."):
        assert name in text
    # the picture names the guide asks the user to draw are the ones the modules look for
    from ola.registry import default_registry
    from ola.wiring import load_wiring

    registry = default_registry(user_dir="/nonexistent")
    wanted = {
        e["file"]
        for i in registry.list()
        if load_wiring(i.path)
        for e in load_wiring(i.path).get("images", [])
    }
    assert wanted, "no module lists pictures"
    for name in wanted:
        assert f"`{name}`" in text, f"docs/wiring.md does not name the picture {name}"
    assert "python -m frontend.ui.WiringDialog" in text and "foreach" in text
    # the work list names every picture, with its folder
    work = read(ROOT / "docs" / "wiring-images.md")
    for info in registry.list():
        for entry in (load_wiring(info.path) or {}).get("images", []):
            assert f"`{entry['file']}`" in work, f"docs/wiring-images.md lacks {entry['file']}"
            assert f"ola/modules/{info.id}/" in work
    assert "wiring-images.md" in text
    catalog = _json.loads(read(ROOT / "frontend" / "lang" / "modules" / "wiring" / "en.json"))
    assert catalog["wir_show_before"] == "Show this before each measurement"
    assert catalog["wir_button"] == "Connections..." and catalog["wir_save_svg"] == "Save SVG..."
    assert "wiring.md" in read(ROOT / "docs" / "measurement-modules.md")


def test_regulation_example_in_the_docs_is_valid_and_runs():
    """The example of docs/regulation.md is a real file: it validates and runs on the simulation."""
    import json as _json

    from ola.registry import default_registry
    from ola.runner import Runner
    from ola.sim_bench import SimBench

    text = read(ROOT / "docs" / "regulation.md")
    block = re.search(r"```json regulation\.reg\n(.*?)```", text, re.S)
    assert block, "example block not found in docs/regulation.md"
    params = _json.loads(block.group(1))
    m = default_registry(user_dir="/nonexistent").create("regulation", params)
    assert m.check() == [], [str(p) for p in m.check()]
    bench = SimBench(line_mv_per_v=2.0, output_mohm=40.0)
    runner = Runner(m, {"supply": [bench.supply], "load": [bench.load], "meter": [bench.meter]})
    runner.start()
    assert runner.join(60) and runner.state.value == "finished", runner.error
    rows = {
        e.data["values"]["test"]: e.data["values"]
        for e in runner.drain()
        if e.kind == "point" and e.data["table"] == "summary"
    }
    assert abs(rows["load"]["output_resistance_mohm"] - 40.0) < 2
    assert rows["line"]["verdict"] == "PASS" and rows["load"]["verdict"] == "PASS"
    assert "max_vin_drop_v" in rows["line"]
    for name in (
        "measure_dc_voltage",
        "34401A",
        "max_vin_v",
        "output_resistance_mohm",
        "datalogger",
    ):
        assert name in text


def test_cable_correction_in_the_docs_is_real(tmp_path):
    """docs/return-loss.md and docs/antenna.md describe the correction: the names exist, and the
    example parameter is valid."""
    import json as _json

    from ola import deembed
    from ola.registry import default_registry

    registry = default_registry(user_dir="/nonexistent")
    for name in ("return-loss", "antenna"):
        text = read(ROOT / "docs" / f"{name}.md")
        assert "## Through a cable" in text, name
        for word in ("asset_id", "touchstone", "return_loss_raw_db", "vswr_raw", "raw_min_vswr"):
            assert word in text, (name, word)
    block = re.search(
        r'```json\n"correction": (\{.*?\})\n```', read(ROOT / "docs" / "return-loss.md"), re.S
    )
    assert block, "the correction example is missing"
    correction = _json.loads(block.group(1))
    out = []
    deembed.check_correction({"correction": correction}, out, lambda path, msg: (path, msg))
    assert out == []
    params = {
        "sweep": {"start_hz": 8e8, "stop_hz": 9.5e8, "points": 31},
        "correction": correction,
        "confirm_setup": False,
    }
    for module in ("return_loss", "antenna"):
        assert registry.create(module, params).check() == []
    assert "ola/deembed.py" in read(ROOT / "README.md")
    assert "return_loss_with_cable" in read(ROOT / "docs" / "wiring-images.md")


def test_deembedding_doc_matches_the_code():
    """docs/deembedding.md names fields, models and files: they must exist in the code."""
    from ola import fixtures
    from ola.deembed import MODES, TERMINATIONS
    from ola.registry import default_registry

    text = read(ROOT / "docs" / "deembedding.md")
    words = (
        "correction.cable", "correction.port1", "correction.port2", "asset_id", "touchstone",
        "reversed", "ola/deembed.py", "ola/fixtures.py", "S21_raw", "attenuation_raw_db",
        "fixture_loss_port1_db", "raw_insertion_loss_db", "raw_mean_attenuation_db",
    )  # fmt: skip
    for word in words:
        assert word in text, word
    for model in fixtures.MODELS:
        assert f"`model: {model}`" in text, model
    for mode in MODES:
        assert f"`mode: {mode}`" in text, mode
    assert set(TERMINATIONS) == {"open", "short"} and "termination" in text
    registry = default_registry(user_dir="/nonexistent")
    for name in ("filter", "attenuator"):
        guide = read(ROOT / "docs" / f"{name}.md")
        assert "deembedding.md" in guide and "correction" in guide, name
        schema = registry.get(name).params_schema
        assert "correction" in schema and "model" in schema["correction"]["description"]
    assert "deembedding.md" in read(ROOT / "docs" / "return-loss.md")
    assert "ola/fixtures.py" in read(ROOT / "README.md")
    for image in ("filter_with_fixtures", "attenuator_with_fixtures"):
        assert image in read(ROOT / "docs" / "wiring-images.md")


def test_bode_example_in_the_docs_is_valid_and_runs():
    """The example of docs/bode.md is a real file: it validates and runs on the simulated bench."""
    import json as _json

    from ola.registry import default_registry
    from ola.runner import Runner
    from ola.sim_bode import SimBodeLab, integrator_with_pole

    text = read(ROOT / "docs" / "bode.md")
    block = re.search(r"```json bode\.bod\n(.*?)```", text, re.S)
    assert block, "example block not found in docs/bode.md"
    params = _json.loads(block.group(1))
    m = default_registry(user_dir="/nonexistent").create("bode", params)
    assert m.check() == [], [str(p) for p in m.check()]
    lab = SimBodeLab(plant=integrator_with_pole(2e4, 2e5), noise_v=0.0001)
    runner = Runner(m, {"generator": [lab.generator], "oscilloscope": [lab.scope]})
    runner.start()
    assert runner.join(120) and runner.state.value == "finished", runner.error
    rows = [
        e.data["values"]
        for e in runner.drain()
        if e.kind == "point" and e.data["table"] == "points"
    ]
    row = rows[0]
    assert abs(row["crossover_hz"] - 2e4) < 1e3 and abs(row["phase_margin_deg"] - 84.3) < 3
    assert row["verdict"] == "PASS" and not lab.generator_on
    for name in ("set_output_state", "set_frequency", "set_amplitude", "function_generator",
                 "read_waveform_full", "phase_margin_deg", "gain_margin_db"):  # fmt: skip
        assert name in text, name


def test_tdr_example_in_the_docs_is_valid_and_runs():
    """The example of docs/tdr.md is a real file: it validates and finds the end of the cable."""
    import json as _json

    from ola import tdr
    from ola.registry import default_registry
    from ola.runner import Runner
    from ola.sim_vna import SimVna

    text = read(ROOT / "docs" / "tdr.md")
    block = re.search(r"```json tdr\.tdr\n(.*?)```", text, re.S)
    assert block, "example block not found in docs/tdr.md"
    params = _json.loads(block.group(1))
    m = default_registry(user_dir="/nonexistent").create("tdr", params)
    assert m.check() == [], [str(p) for p in m.check()]
    vna = SimVna(length_m=5.0, termination="open", velocity_factor=0.66, fault_at_m=2.0,
                 fault_gamma=0.3)  # fmt: skip
    runner = Runner(m, {"vna": [vna]})
    runner.start()
    assert runner.join(60) and runner.state.value == "finished", runner.error
    rows = {}
    for e in runner.drain():
        if e.kind == "point":
            rows.setdefault(e.data["table"], []).append(e.data["values"])
    point = rows["points"][0]
    assert abs(point["last_reflection_m"] - 5.0) < 0.05 and abs(point["length_error_m"]) < 0.05
    assert point["verdict"] == "PASS" and len(rows["faults"]) == 2
    assert abs(point["resolution_m"] - tdr.resolution_m(1e9, 0.66)) < 0.02
    names = ("c * vf * t / 2", "higher impedance", "lower impedance", "velocity_factor_estimate")
    for name in names + ("step_response", "ola/tdr.py", "resolution", "range"):
        assert name in text, name


def test_sparameters_example_in_the_docs_is_valid_and_runs():
    """The example of docs/sparameters.md is a real file: it validates and runs."""
    import json as _json

    from ola.registry import default_registry
    from ola.runner import Runner
    from ola.sim_vna import SimVna

    text = read(ROOT / "docs" / "sparameters.md")
    block = re.search(r"```json sparameters\.spm\n(.*?)```", text, re.S)
    assert block, "example block not found in docs/sparameters.md"
    params = _json.loads(block.group(1))
    params["interval_s"] = 0.0
    m = default_registry(user_dir="/nonexistent").create("sparameters", params)
    assert m.validate() == [], m.validate()
    runner = Runner(m, {"vna": [SimVna(library_calls=True, library_extras=True)]})
    runner.start()
    assert runner.join(30) and runner.state.value == "finished", runner.error
    rows = [e.data["values"] for e in runner.drain() if e.kind == "point"]
    assert [r["sweep"] for r in rows] == [1, 2, 3]
    for key in ("S11_min_db", "S11_min_hz", "S21_max_db"):
        assert key in rows[0] and key in text, key


def test_time_log_example_in_the_docs_is_valid_and_runs():
    """The example of docs/time-log.md is a real file: it validates and runs."""
    import json as _json

    from ola.registry import default_registry
    from ola.runner import Runner
    from tests.measurement_helpers import FakeHandle, run_to_end

    text = read(ROOT / "docs" / "time-log.md")
    block = re.search(r"```json temperatures\.tlg\n(.*?)```", text, re.S)
    assert block, "example block not found in docs/time-log.md"
    params = _json.loads(block.group(1))
    params.pop("duration_s")
    params.update(samples=3, interval_s=0.01)
    m = default_registry(user_dir="/nonexistent").create("time_log", params)
    assert m.validate() == [], m.validate()
    handles = {
        "instruments": [
            FakeHandle("dmm1", {"read_voltage": 5.0}),
            FakeHandle("daq", {"measure_temperature": 25.0}),
        ]
    }
    runner = run_to_end(Runner(m, handles))
    assert runner.state.value == "finished", runner.error
    rows = [e.data["values"] for e in runner.drain() if e.kind == "point"]
    assert len(rows) == 3 and rows[0]["vout"] == 5.0 and rows[0]["temp1"] == 25.0
    for name in ("duration_s", "samples", "t_s", "instruments"):
        assert name in text, name


def test_golden_example_in_the_docs_is_valid_and_gives_a_verdict(tmp_path):
    """The tolerances of docs/golden.md are a real spec: a good cable passes, a worn one fails."""
    import json as _json

    from ola.compare import load_run
    from ola.golden import check_against_golden
    from tests.test_golden import cable_run
    from ola.registry import default_registry

    text = read(ROOT / "docs" / "golden.md")
    block = re.search(r"```json tolerances\.json\n(.*?)```", text, re.S)
    assert block, "example block not found in docs/golden.md"
    spec = _json.loads(block.group(1))
    registry = default_registry(user_dir="/nonexistent")
    golden = load_run(cable_run(registry, tmp_path, "golden", 0.6))
    good = load_run(cable_run(registry, tmp_path, "good", 0.6, stamp="20261104_100000"))
    worn = load_run(cable_run(registry, tmp_path, "worn", 1.2, stamp="20261105_100000"))
    assert check_against_golden(good, golden, spec).verdict == "PASS"
    assert check_against_golden(worn, golden, spec).verdict == "FAIL"
    for name in ("golden/", "min_overlap", "NO DATA", "set_golden", "upper", "lower"):
        assert name in text, name


def test_trend_doc_names_the_verdicts_and_the_figures_that_exist():
    """docs/trend.md names verdicts and options of the code, and the figures of a cable run."""
    from ola import trend

    text = read(ROOT / "docs" / "trend.md")
    for verdict in ("FAIL", "WARNING", "PASS", "NOT ENOUGH DATA"):
        assert f"`{verdict}`" in text
    assert trend.DEFAULT_FIGURE in text and "max_rate_per_year" in text
    for option in ("--figure", "--limit", "--max-rate", "--warn-days", "--list-figures", "--csv"):
        assert option in text, option
        assert option in read(ROOT / "scripts" / "cable_trend.py"), option

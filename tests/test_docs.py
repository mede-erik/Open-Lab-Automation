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


def test_the_vna_contract_in_the_docs_matches_the_simulated_vna():
    """docs/vna-calls.md names the calls and arguments that SimVna implements."""
    import json as _json

    from ola.sim_vna import SimVna

    text = read(ROOT / "docs" / "vna-calls.md")
    block = re.search(r"```json\n(\{\n  \"schema_version\".*?)```", text, re.S)
    assert block, "schema draft not found in docs/vna-calls.md"
    draft = _json.loads(block.group(1))
    assert draft["category"] == "vnas_series"
    vna = SimVna()
    args = {k: 1.0 for k in draft["calls"]["set_sweep"]["args"]}
    args.update(points=5, sweep_type="linear", start_frequency=1e6, stop_frequency=2e6)
    assert vna.call("set_sweep", **args) is None  # every argument of the draft is accepted
    answer = vna.call("read_sparameter", parameter="S21")
    assert set(answer) == {"frequency", "values"} and len(answer["frequency"]) == 5
    assert all(len(v) == 2 for v in answer["values"])  # [real, imaginary] pairs


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

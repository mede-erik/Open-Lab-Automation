# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Kits of resistors in the resistive efficiency: the kit made from typed resistors, the references
resolved inside the load of a parameter, and the panel of the editor (no screen needed)."""

import json

import pytest

from ola.efficiency_editor import EfficiencyEditor
from ola.project import Project
from ola.project_session import ProjectSession
from ola.registry import default_registry
from ola.resistor_kits import Kit, KitError, KitRegistry, KitResistor, kit_from_loads


def test_a_kit_is_made_from_the_resistors_typed_in():
    loads = [
        {"name": "A", "r_ohm": 10, "power_w": 5, "channel": "201"},
        {"name": "B||C", "parallel": [{"name": "B", "r_ohm": 22}, {"name": "C", "r_ohm": 47}]},
        {"name": "A", "r_ohm": 10, "power_w": 5, "channel": "201"},  # the same one, kept once
        {"kit": "PWR", "ref": "R1"},  # already in a kit: not copied
    ]
    kit = kit_from_loads("New", loads)
    assert [(r.name, r.r_ohm) for r in kit.resistors] == [("A", 10), ("B", 22), ("C", 47)]
    with pytest.raises(KitError, match="two different"):
        kit_from_loads("X", [{"name": "A", "r_ohm": 1}, {"name": "A", "r_ohm": 2}])
    with pytest.raises(KitError, match="no resistor"):
        kit_from_loads("X", [{"kit": "PWR", "ref": "R1"}])


def test_saving_a_new_kit_leaves_the_others_as_they_were(tmp_path):
    kits = KitRegistry(tmp_path / "kits.json")
    kits.put(Kit("PWR", [KitResistor("R10", 10)]))
    before = kits.get("PWR")
    kits.put(kit_from_loads("Extra", [{"name": "Z", "r_ohm": 3}]))
    assert kits.names() == ["Extra", "PWR"] and kits.get("PWR") == before


def test_the_kits_are_resolved_inside_the_load_of_a_parameter(tmp_path):
    kits = KitRegistry(tmp_path / "kits.json")
    kits.put(Kit("PWR", [KitResistor("R10", 10, 1, 5, "201"), KitResistor("R22", 22, 1, 5, "202")]))
    project = Project.new("Lab", tmp_path)
    session = ProjectSession(project, default_registry(user_dir=tmp_path / "none"))
    session.resistor_kits = kits
    params = EfficiencyEditor.template(["psu"], load=True)
    params["variables"][1]["load"]["loads"] = [
        {"kit": "PWR", "ref": "R10"},
        {"name": "both", "parallel": [{"kit": "PWR", "ref": "R10"}, {"kit": "PWR", "ref": "R22"}]},
    ]
    resolved = session.resolve_kits(params)
    loads = resolved["variables"][1]["load"]["loads"]
    assert loads[0]["r_ohm"] == 10 and loads[0]["name"] == "R10"
    assert [r["r_ohm"] for r in loads[1]["parallel"]] == [10, 22]
    assert json.dumps(params).count('"ref"') == 3  # the file itself is not changed
    params["variables"][1]["load"]["loads"][0]["ref"] = "R99"
    with pytest.raises(Exception, match="R99"):
        session.resolve_kits(params)


def test_the_run_is_checked_with_the_kit_not_yet_resolved():
    params = EfficiencyEditor.template(["psu"], load=True)
    params["variables"][1]["load"]["loads"] = [
        {"kit": "PWR", "ref": "R10"},
        {"kit": "PWR", "ref": "R22"},
    ]
    editor = EfficiencyEditor(params, type="resistive_efficiency")
    assert not [p for p in editor.problems() if "load" in p.path]
    params["variables"][1]["load"]["loads"][0] = {"ref": "R10"}
    editor = EfficiencyEditor(params, type="resistive_efficiency")
    assert any("names the kit" in p.message for p in editor.problems())


# ---- the panel ---------------------------------------------------------------------------------
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.mark.gui
def test_the_editor_shows_the_load_panel_only_for_a_load(app, tmp_path):
    from frontend.ui.EfficiencyEditorDialog import EfficiencyEditorDialog

    editor = EfficiencyEditor(
        EfficiencyEditor.template(["psu"], load=True), type="resistive_efficiency"
    )
    path = tmp_path / "x.rfe"
    editor.save(str(path))
    dialog = EfficiencyEditorDialog(str(path), None, ["psu"])
    assert dialog.editor.type == "resistive_efficiency"
    dialog.param_list.setCurrentRow(1)  # the load
    assert not dialog.load_panel.isHidden() and dialog.set_group.isHidden()
    assert dialog.load_panel.table.rowCount() == 1
    dialog.param_list.setCurrentRow(0)  # vin
    assert dialog.load_panel.isHidden() and not dialog.set_group.isHidden()
    dialog.close()


@pytest.mark.gui
def test_adding_resistors_from_a_kit_and_editing_the_connection(app, tmp_path):
    from frontend.ui.EfficiencyEditorDialog import EfficiencyEditorDialog

    editor = EfficiencyEditor(
        EfficiencyEditor.template(["psu", "mux"], load=True), type="resistive_efficiency"
    )
    path = tmp_path / "x.rfe"
    editor.save(str(path))
    dialog = EfficiencyEditorDialog(str(path), None, ["psu", "mux"])
    dialog.param_list.setCurrentRow(1)
    panel = dialog.load_panel
    panel._registry = KitRegistry(tmp_path / "kits.json")
    panel._registry.put(Kit("PWR", [KitResistor("R22", 22, 1, 5)]))
    panel._add([{"kit": "PWR", "ref": "R22"}])
    block = dialog.editor.get("variables[1].load")
    assert [load.get("ref") or load["name"] for load in block["loads"]] == ["10R", "R22"]
    assert panel.table.item(1, 0).text() == "PWR/R22" and panel.table.item(1, 1).text() == "22"
    panel.mode.setCurrentIndex(panel.mode.findData("mux"))
    panel.instrument.setCurrentText("mux")
    panel.max_vout.setText("12")
    block = dialog.editor.get("variables[1].load")
    assert block["switching"] == {"mode": "mux", "instrument": "mux"} and block["max_vout_v"] == 12
    panel.table.selectRow(0)
    panel.remove_selected()
    assert len(dialog.editor.get("variables[1].load")["loads"]) == 1
    dialog.close()


@pytest.mark.gui
def test_the_matrix_is_shown_but_cannot_be_chosen(app):
    from frontend.ui.LoadPanel import LoadPanel

    panel = LoadPanel(lambda key, **kw: key)
    item = panel.mode.model().item(panel.mode.findData("mux"))
    assert not item.isEnabled() and panel.mode.findData("manual") == 0


@pytest.mark.gui
def test_the_values_and_the_arguments_are_edited_in_tables(app, tmp_path):
    from frontend.ui.EfficiencyEditorDialog import EfficiencyEditorDialog
    from frontend.ui.efficiency_widgets import ArgsDialog

    editor = EfficiencyEditor(EfficiencyEditor.template(["psu"]))
    path = tmp_path / "x.eff"
    editor.save(str(path))
    dialog = EfficiencyEditorDialog(str(path), None, ["psu"])
    dialog.param_list.setCurrentRow(1)  # vin, a list of values
    table = dialog.sweep_rows["values"][1]
    assert table.text() == "9, 12, 15" and table.table.rowCount() == 3
    table.add_row("18")
    assert dialog.editor.get("variables[1].sweep.values") == [9, 12, 15, 18]
    table.table.selectRow(0)
    table.remove_selected()
    assert dialog.editor.get("variables[1].sweep.values") == [12, 15, 18]
    dialog.close()
    args = ArgsDialog({"channel_number": 1, "mode": "dc"})
    args.add_row("ok", "true")
    assert args.args() == {"channel_number": 1, "mode": "dc", "ok": True}


@pytest.mark.gui
def test_a_load_can_be_added_only_in_the_resistive_efficiency(app, tmp_path):
    from frontend.ui.EfficiencyEditorDialog import EfficiencyEditorDialog

    plain = tmp_path / "a.eff"
    EfficiencyEditor(EfficiencyEditor.template(["psu"])).save(str(plain))
    dialog = EfficiencyEditorDialog(str(plain), None, ["psu"])
    assert dialog.btn_eff_add_load.isHidden()
    dialog.close()
    resistive = tmp_path / "b.rfe"
    EfficiencyEditor(
        EfficiencyEditor.template(["psu"], load=True), type="resistive_efficiency"
    ).save(str(resistive))
    dialog = EfficiencyEditorDialog(str(resistive), None, ["psu"])
    assert not dialog.btn_eff_add_load.isHidden()
    dialog.editor.remove_parameter(1)  # the first load is removed...
    dialog._after_structure()
    assert "rload" not in dialog.editor.names()
    dialog._add_load()  # ...and a load can be added again, also a second one
    dialog._add_load()
    names = dialog.editor.names()
    assert names.count("rload") == 1 and "rload2" in names
    assert all("load" in v for v in dialog.editor.variables if v["name"].startswith("rload"))
    dialog.close()


@pytest.mark.gui
def test_the_kit_picker_adds_the_ticked_resistors(app, tmp_path):
    from PyQt6.QtWidgets import QDialogButtonBox

    from frontend.ui.LoadPanel import _KitPick

    kits = KitRegistry(tmp_path / "kits.json")
    kits.put(Kit("PWR", [KitResistor("R10", 10), KitResistor("R22", 22), KitResistor("R47", 47)]))
    pick = _KitPick(kits, lambda key, **kw: key)
    ok = pick.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled()  # nothing ticked yet
    pick.check_all(True)
    assert ok.isEnabled()
    assert [r["ref"] for r in pick.loads()] == ["R10", "R22", "R47"]
    pick.check_all(False)
    from PyQt6.QtCore import Qt

    pick.list.item(0).setCheckState(Qt.CheckState.Checked)
    pick.list.item(2).setCheckState(Qt.CheckState.Checked)
    pick.how.setCurrentIndex(pick.how.findData("parallel"))
    assert pick.loads() == [
        {
            "name": "R10 R47",
            "parallel": [{"kit": "PWR", "ref": "R10"}, {"kit": "PWR", "ref": "R47"}],
        }
    ]


@pytest.mark.gui
def test_a_kit_made_while_the_editor_is_open_is_seen(app, tmp_path, monkeypatch):
    from frontend.ui import LoadPanel as module

    path = tmp_path / "kits.json"
    monkeypatch.setattr(module, "KitRegistry", lambda: KitRegistry(path))
    panel = module.LoadPanel(lambda key, **kw: key)
    assert panel.registry.names() == []
    KitRegistry(path).put(Kit("New", [KitResistor("R1", 1)]))  # made in Tools > Resistor kits
    assert panel.registry.names() == ["New"]


@pytest.mark.gui
def test_the_relay_instrument_is_not_offered(app):
    from frontend.ui.LoadPanel import LoadPanel

    panel = LoadPanel(lambda key, **kw: key, ["daq"])
    panel.set_block({"loads": [], "switching": {"mode": "manual"}})
    assert not panel._form.isRowVisible(panel.instrument)

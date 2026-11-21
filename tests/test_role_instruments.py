# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The editor of a measurement lists, for each role, only the instruments that can take it:
a supply role does not offer a datalogger (``ola.inst_file.role_types`` / ``fits_role``,
``ProjectSession.instruments_by_role``)."""

import json
import os

import pytest

from ola.inst_file import entry_type, fits_role, role_types
from ola.measurement import Role
from ola.project import Project
from ola.project_session import ProjectSession
from ola.registry import default_registry

ENTRIES = [
    {"instance_name": "PSU", "instrument_type": "power_supply"},
    {"instance_name": "LOAD", "instrument_type": "electronic_load"},
    {"instance_name": "DMM", "instrument_type": "multimeter"},
    {"instance_name": "DAQ", "instrument_type": "datalogger"},
    {"instance_name": "SW", "instrument_type": "switch_unit"},
    {"instance_name": "VNA", "instrument_type": "network_analyzer"},
    {"instance_name": "SCOPE", "instrument_type": "oscilloscopes"},  # an old plural spelling
    {"instance_name": "GEN", "instrument_type": "function_generator"},
    {"instance_name": "OLD", "instrument_type": ""},  # a type that is not known
]


def session(tmp_path):
    (tmp_path / "lab.inst").write_text(json.dumps({"instruments": ENTRIES}), encoding="utf-8")
    project = Project.new("Lab", tmp_path, inst_file="lab.inst")
    project.save()
    return ProjectSession(project, default_registry(user_dir=tmp_path / "none"))


def test_a_role_takes_its_category_or_the_types_it_accepts():
    assert role_types(Role("s", "power_supply")) == {"power_supply"}
    assert role_types(Role("a", "any")) is None
    assert role_types(Role("m", "multimeter", accepts=("multimeter", "datalogger"))) == {
        "multimeter",
        "datalogger",
    }
    assert role_types(Role("o", "oscilloscope")) == {"oscilloscope"}
    supply = Role("s", "power_supply")
    assert fits_role(ENTRIES[0], supply) and not fits_role(ENTRIES[3], supply)
    assert fits_role(ENTRIES[-1], supply)  # a type that is not known is not excluded
    assert fits_role(ENTRIES[6], Role("o", "oscilloscope"))  # the plural spelling is understood


def test_the_regulation_editor_lists_the_right_instruments(tmp_path):
    s = session(tmp_path)
    by_role = s.instruments_by_role(s.registry.get("regulation"))
    assert by_role["supply"] == ["PSU", "OLD"]  # not the datalogger, not the multimeter
    assert by_role["meter"] == ["DMM", "DAQ", "OLD"]  # a multimeter or a datalogger


def test_every_form_role_lists_only_its_own_kind(tmp_path):
    s = session(tmp_path)
    for info in s.registry.list():
        by_role = s.instruments_by_role(info)
        for role in info.roles:
            types = role_types(role)
            if types is None:
                assert by_role[role.name] == s.instruments  # any instrument
                continue
            listed = [e for e in ENTRIES if e["instance_name"] in by_role[role.name]]
            assert all(fits_role(e, role) for e in listed), (info.id, role.name)
            assert "OLD" in by_role[role.name]
            assert any(entry_type(e) in types for e in listed), (info.id, role.name)


def test_without_an_instrument_file_every_role_lists_all_names(tmp_path):
    project = Project.new("Lab", tmp_path)
    project.save()
    registry = default_registry(user_dir=tmp_path / "none")
    s = ProjectSession(project, registry, instruments=["a", "b"])
    by_role = s.instruments_by_role(s.registry.get("regulation"))
    assert all(names == ["a", "b"] for names in by_role.values())


def test_a_manifest_can_list_accepted_types_and_rejects_bad_ones(tmp_path):
    from ola.registry import _parse_manifest

    base = {
        "id": "xmod", "name": "X", "version": "1", "api_version": 1, "extension": ".xyz",
        "entry": "m.py:M", "params_schema": {}, "description": "d",
    }

    def parse(accepts):
        role = {"name": "m", "category": "multimeter", "accepts": accepts}
        manifest = dict(base, roles=[role])
        (tmp_path / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
        return _parse_manifest(tmp_path, False)

    assert parse(["datalogger"]).roles[0].accepts == ("datalogger",)
    for bad in ("datalogger", [1], [""]):
        with pytest.raises(ValueError, match="accepts"):
            parse(bad)


# ----- the editor ---------------------------------------------------------------------------------
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.mark.gui
def test_the_form_editor_offers_each_field_its_instruments(app, tmp_path):
    from frontend.ui.FormEditorDialog import FormEditorDialog

    s = session(tmp_path)
    info = s.registry.get("regulation")
    dialog = FormEditorDialog(
        str(tmp_path / "r.reh"),
        s.registry,
        "regulation",
        None,
        s.instruments,
        role_instruments=s.instruments_by_role(info),
    )
    combos = {
        path: [row.widget.itemText(i) for i in range(row.widget.count()) if row.widget.itemText(i)]
        for path, row in dialog.rows.items()
        if row.field.kind == "instrument"
    }
    assert combos["supply"] == ["PSU", "OLD"]
    assert combos["meter"] == ["DMM", "DAQ", "OLD"]

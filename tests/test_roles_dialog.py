# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The window that maps the instruments of a received project to your own (no screen needed)."""

import glob
import json
import os
import re

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from frontend.ui.RolesDialog import RolesDialog  # noqa: E402
from tests.test_role_mapping import LIB, received  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pytestmark = pytest.mark.skipif(LIB is None, reason="library with the VNA models not available")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_the_dialog_lists_the_gaps_and_marks_what_a_candidate_cannot_do(app, tmp_path):
    session, connector, _ = received(
        tmp_path, params={"start_hz": 1e6, "stop_hz": 5e9, "points": 201}
    )
    dialog = RolesDialog(session, connector.characteristics, connector.abilities)
    assert [g.name for g in dialog.gaps] == ["OWNER_VNA"]
    assert dialog.table.item(0, 0).text() == "OWNER_VNA"
    assert dialog.table.item(0, 1).text() == "Sweep"
    texts = [dialog.combos["OWNER_VNA"].itemText(i) for i in range(3)]
    assert texts[0] == "(leave as it is)"
    assert texts[1] == "MY_LITE"  # 5 GHz is inside its 6.3 GHz
    assert "cannot do what the measurement asks" in texts[2]  # the SNA stops at 4.5 GHz
    assert dialog.chosen() == {"OWNER_VNA": None}


def test_apply_names_the_chosen_instrument_in_the_measurements(app, tmp_path):
    session, connector, ref = received(tmp_path)
    dialog = RolesDialog(session, connector.characteristics, connector.abilities)
    combo = dialog.combos["OWNER_VNA"]
    combo.setCurrentIndex(combo.findData("MY_LITE"))
    dialog.apply_button.click()
    assert dialog.result() == dialog.DialogCode.Accepted
    raw = json.loads(session.path(ref).read_text(encoding="utf-8"))
    assert raw["role_bindings"] == {"vna": ["MY_LITE"]}


def test_leaving_everything_as_it_is_changes_nothing(app, tmp_path):
    session, connector, ref = received(tmp_path)
    before = session.path(ref).read_text(encoding="utf-8")
    dialog = RolesDialog(session, connector.characteristics, connector.abilities)
    dialog.apply_button.click()
    assert session.path(ref).read_text(encoding="utf-8") == before


def test_a_kind_you_have_none_of_says_so(app, tmp_path):
    session, connector, ref = received(tmp_path)
    inst = tmp_path / "lab.inst"
    entries = [
        e
        for e in json.loads(inst.read_text())["instruments"]
        if "LITE" not in e["instance_name"] and "SNA" not in e["instance_name"]
    ]
    inst.write_text(json.dumps({"instruments": entries}), encoding="utf-8")
    dialog = RolesDialog(session, connector.characteristics, connector.abilities)
    combo = dialog.combos["OWNER_VNA"]
    assert combo.count() == 1 and combo.itemText(0) == "(you have no instrument of this kind)"


def test_a_failed_update_is_reported_and_nothing_is_accepted(app, tmp_path, monkeypatch):
    session, connector, ref = received(tmp_path)
    from ola import role_mapping
    from ola.project_rename import RenameError

    def boom(*args):
        raise RenameError("disk full")

    warned = []
    monkeypatch.setattr(role_mapping, "map_instrument", boom)
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))
    dialog = RolesDialog(session, connector.characteristics, connector.abilities)
    combo = dialog.combos["OWNER_VNA"]
    combo.setCurrentIndex(combo.findData("MY_LITE"))
    dialog.apply_button.click()
    assert warned and "disk full" in warned[0]
    assert dialog.result() != dialog.DialogCode.Accepted


def test_every_text_exists_in_all_languages():
    source = open(os.path.join(HERE, "frontend", "ui", "RolesDialog.py"), encoding="utf-8").read()
    window = open(os.path.join(HERE, "frontend", "ui", "ProjectWindow.py"), encoding="utf-8").read()
    keys = set(re.findall(r'"(roles_[a-z_]+)"', source + window))
    assert len(keys) >= 12
    for path in glob.glob(os.path.join(HERE, "frontend", "lang", "*.json")):
        catalog = json.load(open(path, encoding="utf-8"))
        missing = sorted(k for k in keys if k not in catalog)
        assert not missing, f"{os.path.basename(path)} lacks {missing}"

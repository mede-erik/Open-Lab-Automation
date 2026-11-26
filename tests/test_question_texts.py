# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The questions a measurement asks the operator are in the language of the application: the
engine gives a translation key with its arguments (or the rows of a table), the window builds the
text. The English sentence of the engine stays in the log."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
pytest.importorskip("pytestqt")

from ola.resistors import formula  # noqa: E402

ENGLISH_FRAGMENTS = (
    "Connect", "Disconnect", "switched on", "switched off", "Continue", "Then continue",
    "nothing connected", "to move", "Zero of channel", "read by", "differs", "allowed",
    "already on", "Calibrate",
)


def shown(qtbot, question, lang="it"):
    from frontend.ui.module_translator import CatalogTranslator
    from frontend.ui.RunWindow import QuestionDialog

    dialog = QuestionDialog(question, CatalogTranslator("run", lang=lang))
    qtbot.addWidget(dialog)
    return " ".join(label.text() for label in dialog.findChildren(QtWidgets.QLabel))


def question(text, data, choices=("continue", "abort")):
    return {"id": "q", "text": text, "choices": list(choices), "default": "abort", "data": data}


@pytest.mark.gui
@pytest.mark.parametrize("lang", ["it", "de"])
def test_the_setup_questions_are_translated(qtbot, lang):
    cases = [
        question("English bode", {"text_key": "run_q_bode_setup",
                                  "text_args": {"input": 1, "output": 2, "amp": "0.1"}}),
        question("English bode", {"text_key": "run_q_bode_nosw",
                                  "text_args": {"input": 1, "output": 2, "amp": "0.1"}}),
        question("English reg", {"text_key": "run_q_reg_setup_load"}),
        question("English ripple", {"text_key": "run_q_ripple_setup"}),
        question("English zero", {"text_key": "run_q_zero_main_back_offset",
                                  "text_args": {"label": "CH1", "offset": "+0.2"}}),
    ]
    for item in cases:
        text = shown(qtbot, item, lang)
        assert "English" not in text
        for fragment in ENGLISH_FRAGMENTS:
            if lang == "de":
                break
            assert fragment not in text, (item["data"], fragment)


@pytest.mark.gui
def test_the_verify_question_is_translated_with_its_numbers(qtbot):
    data = {"variable": "vin", "reading": "daq", "read_value": 10.8, "set_value": 9,
            "error_abs": 1.8, "tol_abs": 0.02, "tol_rel": 0.01, "point": 0, "sample": 0,
            "text_key": "run_q_verify_pct",
            "text_args": {"variable": "vin", "reading": "daq", "read": "10.8", "set": "9",
                          "pct": "20.0", "tol_abs": "0.02", "tol_rel": "1"}}
    text = shown(qtbot, question("English differs", data, ("retry", "abort", "skip")))
    assert "20.0" in text and "10.8" in text
    assert "differs" not in text and "allowed" not in text


@pytest.mark.gui
def test_the_plan_of_the_loads_is_built_from_its_rows(qtbot):
    rows = [
        {"target_a": 0.0, "combination": "open", "vout_v": 5.0},
        {"target_a": 1.0, "combination": "R1 || (R2 + R3)", "r_ohm": 2.5, "vout_v": 4.9,
         "current_a": 1.0, "changes": 2},
    ]
    text = shown(qtbot, question("English plan", {"kind": "plan", "rows": rows}))
    assert "R1 || (R2 + R3)" in text and "2.5" in text
    assert "nothing connected" not in text and "to move" not in text
    assert "0 A" in text and "1 A" in text


@pytest.mark.gui
def test_the_load_question_shows_the_formula_in_symbols(qtbot):
    from ola.resistors import Load, Resistor, Group

    parts = [Resistor("a", 22.0, 0, 0, 0), Resistor("b", 47.0, 0, 0, 0)]
    load = Load("R", Group("parallel", parts))
    text = formula(load)
    assert "||" in text and "Ω" in text and "in parallel" not in text
    data = {"kind": "load", "parameter": "vin", "load": "R", "formula": text,
            "text_key": "run_q_load_connect",
            "text_args": {"parameter": "vin", "load": "R", "formula": text}}
    shown_text = shown(qtbot, question("English connect", data))
    assert text in shown_text and "Connect" not in shown_text


def test_every_question_key_exists_in_all_languages():
    import json

    from tests.conftest import REPO

    keys = ["run_q_plan_head", "run_q_plan_open", "run_q_plan_row", "run_q_plan_continue",
            "run_q_load_open", "run_q_load_connect", "run_q_outputs_on_end", "run_q_verify_pct",
            "run_q_verify_zero", "run_q_bode_nosw", "run_q_bode_setup", "run_q_reg_setup",
            "run_q_reg_setup_load", "run_q_ripple_setup", "run_q_ripple_setup_load",
            "run_q_zero_main_short", "run_q_zero_main_back", "run_q_zero_main_back_offset"]
    for lang in ("en", "it", "fr", "es", "de"):
        catalog = json.load(open(os.path.join(REPO, "frontend", "lang", "modules", "run",
                                              f"{lang}.json"), encoding="utf-8"))
        missing = [k for k in keys if k not in catalog or not catalog[k].strip()]
        assert missing == [], (lang, missing)

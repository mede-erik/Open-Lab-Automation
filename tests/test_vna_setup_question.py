# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The question 'is the VNA calibrated, and how is the device connected' before a VNA measurement:
the engine gives a translation key with its arguments; the window shows it in the language of the
application (it used to show the English sentence of the engine with the Italian details)."""

import os

import pytest

from ola import vna_common


class RecordingContext:
    """Just what ``ask_setup`` uses: it records the question and answers 'continue'."""

    def __init__(self):
        self.questions = []

    def ask(self, text, choices, default=None, data=None):
        self.questions.append({"text": text, "data": data or {}})
        return "continue"


SWEEP = {"start_hz": 50e3, "stop_hz": 6.3e9, "points": 6000}


def test_the_question_carries_the_key_and_its_arguments():
    ctx = RecordingContext()
    vna_common.ask_setup(
        ctx, "English sentence.", SWEEP,
        connect_key="run_connect_cable_reflection",
        connect_args={"far": "short"},
        mode="reflection",
    )
    data = ctx.questions[0]["data"]
    assert data["connect_key"] == "run_connect_cable_reflection"
    assert data["connect_args"] == {"far": "short"}
    assert data["mode"] == "reflection" and data["kind"] == "calibration"
    assert "English sentence." in ctx.questions[0]["text"]  # the log keeps the English text


def test_without_a_key_the_question_has_no_key():
    ctx = RecordingContext()
    vna_common.ask_setup(ctx, "English sentence.", SWEEP)
    assert ctx.questions[0]["data"]["connect_key"] == ""


@pytest.mark.gui
@pytest.mark.parametrize("lang", ["it", "de"])
def test_the_question_is_shown_in_the_language_of_the_application(lang, qtbot):
    QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from frontend.ui.module_translator import CatalogTranslator
    from frontend.ui.RunWindow import QuestionDialog

    question = {
        "id": "q1",
        "text": (
            "Is the VNA calibrated for this device and this frequency range (50 kHz to 6.3 GHz)? "
            "Connect the cable under test between port 1 and port 2 of the VNA. Then continue."
        ),
        "choices": ["continue", "abort"], "default": "abort",
        "data": {"kind": "calibration", "start_hz": 50e3, "stop_hz": 6.3e9, "points": 6000,
                 "connect_key": "run_connect_cable", "connect_args": {},
                 "mode": "transmission"},
    }
    dialog = QuestionDialog(question, CatalogTranslator("run", lang=lang))
    qtbot.addWidget(dialog)
    shown = " ".join(label.text() for label in dialog.findChildren(QtWidgets.QLabel))
    assert "Is the VNA calibrated" not in shown  # the English sentence of the engine is not shown
    assert "Connect the cable under test" not in shown
    assert dialog.windowTitle()  # the title is translated too
    expected = CatalogTranslator("run", lang=lang).t("run_connect_cable")
    assert expected != "run_connect_cable"
    assert expected in shown


@pytest.mark.gui
def test_the_reflection_sentence_takes_the_translated_end(qtbot):
    QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from frontend.ui.module_translator import CatalogTranslator
    from frontend.ui.RunWindow import QuestionDialog

    question = {
        "id": "q2",
        "text": "English",
        "choices": ["continue", "abort"], "default": "abort",
        "data": {"kind": "calibration", "start_hz": 1e6, "stop_hz": 1e9, "points": 201,
                 "connect_key": "run_connect_cable_reflection",
                 "connect_args": {"far": "short"}},
    }
    dialog = QuestionDialog(question, CatalogTranslator("run", lang="it"))
    qtbot.addWidget(dialog)
    shown = " ".join(label.text() for label in dialog.findChildren(QtWidgets.QLabel))
    assert "in corto" in shown  # the short, in Italian
    assert "{far}" not in shown

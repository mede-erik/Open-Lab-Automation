# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Texts that used to be written in the code in one language: they follow the language of the
application now (instrument library details, error dialog)."""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from frontend.core import errorhandler  # noqa: E402
from frontend.core.LoadInstruments import LoadInstruments  # noqa: E402
from frontend.core.Translator import Translator  # noqa: E402
from frontend.ui.InstrumentLibraryDialog import InstrumentLibraryDialog  # noqa: E402

MODEL = {
    "name": "PSU 3000",
    "id": "PSU_X",
    "manufacturer": "ACME",
    "capabilities": {"number_of_channels": 2, "read_voltage": True},
    "interface": {
        "supported_connection_types": [{"type": "LXI", "address_format_example": "TCPIP0::x"}]
    },
}
SERIES = {"series_name": "PSU series", "series_id": "S1", "models": [MODEL]}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def details(lang, show, data):
    dialog = InstrumentLibraryDialog(LoadInstruments(), translator=Translator(default_lang=lang))
    getattr(dialog, show)(data)
    return dialog.details_text.toPlainText()


@pytest.mark.parametrize(
    "lang,words",
    [("en", ["MODEL", "Manufacturer: ACME", "Reads the voltage: Yes"]),
     ("it", ["MODELLO", "Produttore: ACME", "Lettura tensione: Sì"]),
     ("de", ["MODELL", "Hersteller: ACME", "Liest die Spannung: Ja"])],
)
def test_the_details_of_a_model_are_in_the_language_of_the_application(app, lang, words):
    text = details(lang, "show_model_details", MODEL)
    for word in words:
        assert word in text


def test_the_details_of_a_series_have_no_italian_left_in_english(app):
    text = details("en", "show_series_details", SERIES)
    assert "Models in the series" in text and "2 channels" in text
    assert "canali" not in text and "Modelli" not in text


def test_the_error_dialog_has_real_line_breaks(app, monkeypatch):
    shown = {}

    class Box:
        class Icon:
            Critical = 0

        def setIcon(self, icon):
            pass

        def setWindowTitle(self, title):
            shown["title"] = title

        def setText(self, text):
            shown["text"] = text

        def setInformativeText(self, text):
            shown["info"] = text

        def exec(self):
            pass

    monkeypatch.setattr(errorhandler, "QMessageBox", Box)
    monkeypatch.setattr(errorhandler, "_translator", lambda: Translator(default_lang="en"))
    errorhandler.ErrorHandler().show_error_dialog("[TRN-001]", "It failed", "socket closed")
    assert shown["title"] == "Error"
    assert shown["text"] == "It failed\n\nError code: [TRN-001]\nDetails: socket closed"
    assert "\\n" not in shown["text"] and shown["info"]
    assert QMessageBox  # the real class is left alone outside the test

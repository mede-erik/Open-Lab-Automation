# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The trace plot of the network analyzer before any sweep: an empty chart with a sentence in it,
not a stray character in the middle of a blank area."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
pytest.importorskip("pytestqt")


@pytest.mark.gui
def test_an_empty_trace_plot_shows_its_message(qtbot):
    from frontend.ui.trace_plot import TracePlot

    plot = TracePlot()
    qtbot.addWidget(plot)
    plot.resize(400, 200)
    plot.empty_text = "Nothing yet"
    plot.show()
    image = plot.grab().toImage()
    assert plot.ranges() is None
    # the message is drawn: some pixels of the text colour inside the frame, and none in the corner
    dark = [image.pixelColor(x, y).lightness() for x in range(60, 340) for y in range(60, 140)]
    assert min(dark) < 200 and max(dark) > 0


@pytest.mark.parametrize("lang", ["it", "en", "fr", "es", "de"])
def test_the_empty_message_is_translated(lang):
    from frontend.core.Translator import Translator

    translator = Translator()
    translator.set_language(lang)
    text = translator.t("vna_plot_empty")
    assert text != "vna_plot_empty" and text.strip()

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


@pytest.mark.gui
def test_an_empty_line_plot_shows_its_message_and_no_stray_character(qtbot):
    """The plot of a run window (``LinePlot``) had the same lone ``-`` as the trace plot."""
    from frontend.ui.plot_widget import LinePlot

    plot = LinePlot()
    qtbot.addWidget(plot)
    plot.resize(480, 260)
    plot.empty_text = "Nothing yet"
    plot.show()
    image = plot.grab().toImage()
    assert plot.ranges() is None
    text_pixels = [(x, y) for x in range(60, 440) for y in range(60, 200)
                   if image.pixelColor(x, y) != image.pixelColor(2, 2)]
    assert len(text_pixels) > 40  # the sentence, not a single character


def test_every_plot_a_window_creates_gets_the_text_of_the_empty_case():
    """A window that makes a ``TracePlot`` or a ``LinePlot`` says what the empty chart means
    (``plot.empty_text = self._t(...)``); without it the chart is an empty frame."""
    import glob
    import re

    from tests.conftest import REPO

    pattern = re.compile(
        r"^\s*((?:self\.\w+\s*,\s*)*self\.\w+)\s*=\s*((?:\w+\(\)\s*,?\s*)+)$", re.M
    )
    missing = []
    for path in sorted(glob.glob(os.path.join(REPO, "frontend", "ui", "*.py"))):
        name = os.path.basename(path)
        if name in ("trace_plot.py", "plot_widget.py"):
            continue
        source = open(path, encoding="utf-8").read()
        for match in pattern.finditer(source):
            targets = [t.strip() for t in match.group(1).split(",")]
            kinds = [k.strip().rstrip("(),").strip() for k in match.group(2).split("()")]
            for target, kind in zip(targets, [k for k in kinds if k]):
                if kind in ("TracePlot", "LinePlot") and f"{target}.empty_text" not in source:
                    missing.append(f"{name}: {target}")
    assert missing == [], "\n".join(missing)

# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The colours of the two themes in use are readable: text on its background at least 4.5:1 (WCAG
AA), the handle of a scroll bar on its track at least 3:1 (it was 1.9:1 in the dark theme, so the
bar could not be seen)."""

import os
import re

import pytest

from tests.conftest import REPO

STYLES = os.path.join(REPO, "frontend", "assets", "styles")
THEMES = ["dark_theme.qss", "light_theme.qss"]
TEXT_MIN = 4.5
HANDLE_MIN = 3.0


def luminance(color: str) -> float:
    color = color.lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def channel(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def rules(theme):
    text = open(os.path.join(STYLES, theme), encoding="utf-8").read()
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    found = re.finditer(r"([^{}]+)\{([^}]*)\}", text)
    return {" ".join(m.group(1).split()): m.group(2) for m in found}


def colour(body, prop):
    found = re.search(r"(?<![-\w])%s:\s*(#[0-9a-fA-F]{3,6})" % prop, body)
    return found.group(1) if found else None


@pytest.mark.parametrize("theme", THEMES)
def test_text_is_readable_on_its_background(theme):
    table = rules(theme)
    window_bg = colour(table["QWidget"], "background-color")
    for selector, body in table.items():
        fg = colour(body, "color")
        if fg is None:
            continue
        bg = colour(body, "background-color") or colour(body, "background") or window_bg
        assert contrast(fg, bg) >= TEXT_MIN - 0.01, f"{theme}: {selector}: {fg} on {bg}"


@pytest.mark.parametrize("theme", THEMES)
def test_scroll_bar_handle_is_visible(theme):
    table = rules(theme)
    for orientation in ("vertical", "horizontal"):
        track = colour(table[f"QScrollBar:{orientation}"], "background")
        handle = colour(table[f"QScrollBar::handle:{orientation}"], "background")
        hover = colour(table[f"QScrollBar::handle:{orientation}:hover"], "background")
        assert contrast(handle, track) >= HANDLE_MIN, f"{theme}: {orientation}"
        assert contrast(hover, track) >= HANDLE_MIN, f"{theme}: {orientation} hover"


@pytest.mark.parametrize("theme", THEMES)
def test_selected_rows_are_readable(theme):
    """The text of a selected row of a list or a table is on the selection colour, not on the
    colour of the rows."""
    table = rules(theme)
    for selector in ("QListWidget::item:selected", "QTableWidget::item:selected"):
        body = table[selector]
        fg = colour(body, "color") or colour(table["QWidget"], "color")
        background = colour(body, "background-color")
        assert contrast(fg, background) >= TEXT_MIN - 0.01, f"{theme}: {selector}"


@pytest.mark.parametrize("theme", THEMES)
def test_ticks_have_a_visible_border(theme):
    """The border of the empty tick of a check box, a radio button or a group box is on the
    window colour: at least 3:1 (it was 1.8:1 in the light theme, so an empty tick looked open)."""
    table = rules(theme)
    window_bg = colour(table["QWidget"], "background-color")
    for selector in ("QCheckBox::indicator", "QRadioButton::indicator", "QGroupBox::indicator"):
        border = re.search(r"border:\s*1px solid (#[0-9a-fA-F]{3,6})", table[selector]).group(1)
        assert contrast(border, window_bg) >= HANDLE_MIN, f"{theme}: {selector}"

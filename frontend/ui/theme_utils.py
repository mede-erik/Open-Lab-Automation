# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Style classes of the themes: a widget says what it is (``infobox``, ``error``...), the theme
(``frontend/assets/styles/*.qss``) decides the colours, so the text is readable in every theme."""

from PyQt6.QtWidgets import QWidget


def set_class(widget: QWidget, name: str) -> None:
    """Give a widget the style class ``name`` (``QLabel[class="name"]`` in the themes), also when
    it already has another one."""
    widget.setProperty("class", name)
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()

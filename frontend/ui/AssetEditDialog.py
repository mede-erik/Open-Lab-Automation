# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The card of a cable or device: create one or change one.

For a new card the kind is chosen first (it gives the code its prefix and decides which details are
suggested: a cable has a type, connectors and a length; an antenna a frequency range and a gain...).
A card that exists keeps its code and its kind. The name is required; every other field is
optional. The details are numbers where they are measures (``1.5 m``, ``868M``) and text otherwise;
anything the suggestions do not cover goes in *Other details*, one ``name = value`` per line.
Strings: ``frontend/lang/modules/assets/<lang>.json``.
"""

from typing import Any, Dict, Optional

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from frontend.ui.module_translator import CatalogTranslator
from ola.assets import KINDS, Asset, AssetError, AssetRegistry
from ola.run_view import format_si, parse_si


def parse_attribute(text: str, unit: str) -> Any:
    """A detail typed in a card: a number if it is a measure (``unit`` given: ``"1.5 m"``,
    ``"868M"``), else text; ``None`` if empty."""
    text = text.strip()
    if not text:
        return None
    if unit:
        value = parse_si(text, unit)
        if value is not None:
            return int(value) if float(value).is_integer() and abs(value) < 1e12 else value
    return text


def show_attribute(value: Any, unit: str) -> str:
    """A stored detail as it is shown in the field."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return format_si(float(value), unit) if unit else f"{value:g}"
    return "" if value is None else str(value)


def parse_extra(text: str) -> Dict[str, Any]:
    """``name = value`` lines to a dictionary; ``ValueError`` naming the line that is not one."""
    out: Dict[str, Any] = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        name, sep, value = line.partition("=")
        if not sep or not name.strip():
            raise ValueError(str(number))
        out[name.strip()] = parse_attribute(value, "") if value.strip() else None
    return {k: v for k, v in out.items() if v is not None}


class AssetEditDialog(QDialog):
    """Create a card (``asset=None``) or change one; ``saved`` is the card afterwards."""

    def __init__(
        self,
        registry: AssetRegistry,
        translator: Any = None,
        asset: Optional[Asset] = None,
        kind: str = "cable",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.tr_ = CatalogTranslator("assets", translator)
        self._t = self.tr_.t
        self.registry, self.asset = registry, asset
        self.saved: Optional[Asset] = None
        self.kind = asset.kind if asset else kind
        self.attr_edits: Dict[str, QLineEdit] = {}
        self.setWindowTitle(
            self._t("ast_edit_title", code=asset.id) if asset else self._t("ast_edit_title_new")
        )
        self.resize(520, 560)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        form = QFormLayout()
        if self.asset:
            form.addRow(self._t("ast_f_code"), QLabel(f"<b>{self.asset.id}</b>"))
            form.addRow(self._t("ast_f_kind"), QLabel(self._t(f"ast_kind_{self.kind}")))
        else:
            self.kind_box = QComboBox()
            for kind in KINDS:
                self.kind_box.addItem(self._t(f"ast_kind_{kind}"), kind)
            self.kind_box.setCurrentIndex(max(self.kind_box.findData(self.kind), 0))
            self.kind_box.currentIndexChanged.connect(self._kind_changed)
            form.addRow(self._t("ast_f_kind"), self.kind_box)
        self.name_edit = QLineEdit()
        self.description_edit = QLineEdit()
        self.manufacturer_edit, self.serial_edit = QLineEdit(), QLineEdit()
        self.owner_edit = QLineEdit()
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMaximumHeight(70)
        for key, widget in (
            ("ast_f_name", self.name_edit),
            ("ast_f_description", self.description_edit),
            ("ast_f_manufacturer", self.manufacturer_edit),
            ("ast_f_serial", self.serial_edit),
            ("ast_f_owner", self.owner_edit),
            ("ast_f_notes", self.notes_edit),
        ):
            form.addRow(self._t(key), widget)
        root.addLayout(form)
        root.addWidget(QLabel(f"<b>{self._t('ast_f_details')}</b>"))
        self.details = QFormLayout()
        root.addLayout(self.details)
        root.addWidget(QLabel(self._t("ast_f_extra")))
        self.extra_edit = QPlainTextEdit()
        self.extra_edit.setMaximumHeight(80)
        root.addWidget(self.extra_edit)
        self.message = QLabel()
        self.message.setWordWrap(True)
        root.addWidget(self.message)
        row = QHBoxLayout()
        row.addStretch(1)
        ok, cancel = QPushButton(self._t("ast_save")), QPushButton(self._t("ast_cancel"))
        ok.setDefault(True)
        ok.clicked.connect(self.save)
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        root.addLayout(row)
        self._fill()

    def _suggested(self):
        return KINDS[self.kind]["attributes"]

    def _kind_changed(self) -> None:
        self.kind = self.kind_box.currentData()
        self._fill_details({})

    def _fill(self) -> None:
        a = self.asset
        if a:
            self.name_edit.setText(a.name)
            self.description_edit.setText(a.description)
            self.manufacturer_edit.setText(a.manufacturer)
            self.serial_edit.setText(a.serial)
            self.owner_edit.setText(a.owner)
            self.notes_edit.setPlainText(a.notes)
        self._fill_details(dict(a.attributes) if a else {})

    def _fill_details(self, attributes: Dict[str, Any]) -> None:
        while self.details.rowCount():
            self.details.removeRow(0)
        self.attr_edits = {}
        known = {name for name, _ in self._suggested()}
        for name, unit in self._suggested():
            edit = QLineEdit(show_attribute(attributes.get(name), unit))
            label = self._t(f"ast_attr_{name}") + (f" ({unit})" if unit else "")
            self.details.addRow(label, edit)
            self.attr_edits[name] = edit
        extra = [f"{k} = {show_attribute(v, '')}" for k, v in attributes.items() if k not in known]
        self.extra_edit.setPlainText("\n".join(extra))

    # ================================================================ saving
    def attributes(self) -> Dict[str, Any]:
        """The details as typed (empty ones left out). ``ValueError`` if a line of the other
        details is not ``name = value``."""
        out: Dict[str, Any] = {}
        units = dict(self._suggested())
        for name, edit in self.attr_edits.items():
            value = parse_attribute(edit.text(), units[name])
            if value is not None:
                out[name] = value
        out.update(parse_extra(self.extra_edit.toPlainText()))
        return out

    def save(self) -> None:
        """Write the card to the registry and close; the reason is shown if it cannot be."""
        name = self.name_edit.text().strip()
        if not name:
            self.message.setText(self._t("ast_name_required"))
            return
        try:
            attributes = self.attributes()
        except ValueError as exc:
            self.message.setText(self._t("ast_extra_invalid", n=str(exc)))
            return
        fields = {
            "description": self.description_edit.text().strip(),
            "manufacturer": self.manufacturer_edit.text().strip(),
            "serial": self.serial_edit.text().strip(),
            "owner": self.owner_edit.text().strip(),
            "notes": self.notes_edit.toPlainText().strip(),
        }
        try:
            if self.asset:
                self.saved = self.registry.update(
                    self.asset.id, name=name, attributes=attributes, **fields
                )
            else:
                description = fields.pop("description")
                self.saved = self.registry.create(
                    self.kind, name, description, attributes, **fields
                )
        except (AssetError, OSError) as exc:
            QMessageBox.critical(self, self.windowTitle(), self._t("ast_error", error=exc))
            return
        self.accept()

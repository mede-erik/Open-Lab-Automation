# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The card of a device under test: create one or change one.

The window of the card of a component (``AssetEditDialog``) with the categories of the DUTs
(antenna, filter, converter, generic) in place of the kinds, and a first version, free text, for a
new DUT. A card that exists keeps its code and its category; its versions are edited in their own
window (``DutVersionsDialog``). Strings: ``frontend/lang/modules/duts/<lang>.json``, then
``frontend/lang/modules/assets/<lang>.json`` for the rest.
"""

from typing import Any, Dict, Optional

from PyQt6.QtWidgets import QFormLayout, QLineEdit, QWidget

from frontend.ui.AssetEditDialog import AssetEditDialog
from frontend.ui.module_translator import CatalogTranslator, ChainedTranslator
from ola.duts import CATEGORIES, Dut, DutRegistry


class DutEditDialog(AssetEditDialog):
    """Create a DUT (``dut=None``) or change one; ``saved`` is the card afterwards."""

    kinds = CATEGORIES

    def __init__(
        self,
        registry: DutRegistry,
        translator: Any = None,
        dut: Optional[Dut] = None,
        category: str = "converter",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(registry, translator, asset=dut, kind=category, parent=parent)

    def _make_translator(self, translator: Any) -> Any:
        return ChainedTranslator(
            CatalogTranslator("duts", translator), CatalogTranslator("assets", translator)
        )

    def _add_rows(self, form: QFormLayout) -> None:
        if self.asset is None:  # the versions of a DUT that exists are in their own window
            self.version_edit = QLineEdit()
            self.version_edit.setPlaceholderText(self._t("dut_version_hint"))
            form.addRow(self._t("dut_f_version"), self.version_edit)

    def _create(
        self, name: str, description: str, attributes: Dict[str, Any], fields: Dict[str, str]
    ) -> Dut:
        return self.registry.create(  # type: ignore[call-arg, return-value]
            self.kind, name, description, attributes, version=self.version_edit.text(), **fields
        )

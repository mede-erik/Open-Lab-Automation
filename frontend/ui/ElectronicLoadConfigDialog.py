# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

import sys
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem,
                              QCheckBox, QLineEdit, QDialogButtonBox, QLabel,
                              QSizePolicy, QHeaderView)
from PyQt6.QtGui import QDoubleValidator
from PyQt6.QtCore import Qt 
from frontend.ui.AddressEditorDialog import AddressEditorDialog
from frontend.core.Translator import Translator
import json

class ElectronicLoadConfigDialog(QDialog):
    def __init__(self, instrument, parent=None, load_instruments=None):
        super().__init__(parent)
        self.setWindowTitle("Configurazione canali carico elettronico")
        self.instrument = instrument
        self.load_instruments = load_instruments
        # --- Sincronizza canali con capabilities ---
        capabilities = instrument.get('capabilities', {})
        n = capabilities.get('number_of_channels',
                             capabilities.get('number_of_channel',
                                              instrument.get('num_channels', 0)))
        if n <= 0 and self.load_instruments and self.instrument.get('model_id'):
            n = len(self._get_channel_ids(capabilities))
        channel_ids = self._get_channel_ids(capabilities)
        # Limiti: nuovo formato capabilities.channels[].voltage_output/current_output
        # o flat legacy 'max_current'/'max_voltage'
        max_current = capabilities.get('max_current', None)
        max_voltage = capabilities.get('max_voltage', None)
        channels = instrument.get('channels', [])
        new_channels = []
        for i in range(n):
            ch = channels[i] if i < len(channels) else {}
            ch['enabled'] = ch.get('enabled', False)
            ch['name'] = ch.get('name', channel_ids[i] if i < len(channel_ids) else f'CH{i+1}')
            has_limits = (self.load_instruments
                          and self.instrument.get('model_id')
                          and ch.get('max_current') is None)
            if has_limits:
                limits = self.load_instruments.get_channel_limits(
                    self.instrument.get('instrument_type', 'electronic_load'),
                    self.instrument.get('series', ''),
                    self.instrument.get('model_id'),
                    channel_ids[i] if i < len(channel_ids) else None)
                max_current = max_current if max_current is not None else limits.get('max_current')
                max_voltage = max_voltage if max_voltage is not None else limits.get('max_voltage')
            ch['max_current'] = ch.get('max_current', max_current if max_current is not None else 0.0)
            ch['max_voltage'] = ch.get('max_voltage', max_voltage if max_voltage is not None else 0.0)
            new_channels.append(ch)
        self.channels = new_channels
        self.instrument['channels'] = self.channels
        self.init_ui()

    def _get_channel_ids(self, capabilities):
        """Deriva gli ID canali dal nuovo formato capabilities.channels[] o dai legacy."""
        channel_ids = capabilities.get('channel_ids', [])
        if channel_ids:
            return list(channel_ids)
        channels = capabilities.get('channels')
        if isinstance(channels, list) and channels:
            return [ch.get('channel_id', f'CH{i+1}') for i, ch in enumerate(channels)]
        if self.load_instruments and self.instrument.get('model_id'):
            return self.load_instruments.get_channel_ids(
                self.instrument.get('instrument_type', 'electronic_load'),
                self.instrument.get('series', ''),
                self.instrument.get('model_id'))
        return []

    def init_ui(self):
        layout = QVBoxLayout(self)
        # Tabella canali
        self.table = self.create_channel_table(self.channels, [f'CH{i+1}' for i in range(len(self.channels))], None, None, self)
        # Configurazione ridimensionamento tabella per adattarsi al dialog
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # Checkbox
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Nome
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # Corrente max
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)  # Tensione max
        
        layout.addWidget(self.table)
        # Pulsanti OK/Annulla
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    @staticmethod
    def create_channel_table(channels, channel_ids, max_current, max_voltage, parent):
        table = QTableWidget(len(channels), 5, parent)
        headers = ["Abilita", "ID Canale", "Corrente max (A)", "Tensione max (V)", "Nome variabile"]
        table.setHorizontalHeaderLabels(headers)
        for row, ch in enumerate(channels):
            chk = QCheckBox()
            chk.setChecked(ch.get('enabled', False))
            chk.stateChanged.connect(lambda state, r=row: ElectronicLoadConfigDialog.on_enabled_changed(r, state))
            table.setCellWidget(row, 0, chk)
            id_label = QLabel(channel_ids[row] if row < len(channel_ids) else f'CH{row+1}')
            table.setCellWidget(row, 1, id_label)
            curr_edit = QLineEdit(str(ch.get('max_current', 0.0)))
            if max_current is not None:
                curr_edit.setPlaceholderText(f"max {max_current}")
                curr_edit.setValidator(QDoubleValidator(0.0, float(max_current), 3, curr_edit))
            curr_edit.textChanged.connect(lambda val, r=row: ElectronicLoadConfigDialog.on_current_changed(r, val))
            table.setCellWidget(row, 2, curr_edit)
            volt_edit = QLineEdit(str(ch.get('max_voltage', 0.0)))
            if max_voltage is not None:
                volt_edit.setPlaceholderText(f"max {max_voltage}")
                volt_edit.setValidator(QDoubleValidator(0.0, float(max_voltage), 3, volt_edit))
            table.setCellWidget(row, 3, volt_edit)
            name_edit = QLineEdit(ch.get('name', f'CH{row+1}'))
            name_edit.textChanged.connect(lambda val, r=row: ElectronicLoadConfigDialog.on_name_changed(r, val))
            table.setCellWidget(row, 4, name_edit)
        table.resizeColumnsToContents()
        return table

    @staticmethod
    def on_enabled_changed(row, state):
        dialog = ElectronicLoadConfigDialog.get_dialog()
        dialog.channels[row]['enabled'] = bool(state)
        dialog.save_channels()

    @staticmethod
    def on_name_changed(row, val):
        dialog = ElectronicLoadConfigDialog.get_dialog()
        dialog.channels[row]['name'] = val
        dialog.save_channels()

    @staticmethod
    def on_current_changed(row, val):
        dialog = ElectronicLoadConfigDialog.get_dialog()
        try:
            dialog.channels[row]['max_current'] = float(val)
        except Exception:
            dialog.channels[row]['max_current'] = 0.0
        dialog.save_channels()

    def save_channels(self):
        self.instrument['channels'] = self.channels

    @staticmethod
    def get_dialog():
        return ElectronicLoadConfigDialog._dialog

    @staticmethod
    def set_dialog(dialog):
        ElectronicLoadConfigDialog._dialog = dialog

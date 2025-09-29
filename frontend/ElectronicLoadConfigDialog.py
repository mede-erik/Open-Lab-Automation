import sys
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTableWidget, QDialogButtonBox, QCheckBox, QLineEdit, QLabel
from PyQt5.QtGui import QDoubleValidator
from PyQt5.QtCore import Qt 
from AddressEditorDialog import AddressEditorDialog
from Translator import Translator
import json

class ElectronicLoadConfigDialog(QDialog):
    def __init__(self, instrument, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurazione canali carico elettronico")
        self.instrument = instrument
        # --- Sincronizza canali con capabilities ---
        capabilities = instrument.get('capabilities', {})
        n = capabilities.get('number_of_channel', instrument.get('num_channels', 0))
        channel_ids = capabilities.get('channel_ids', [])
        max_current = capabilities.get('max_current', None)
        max_voltage = capabilities.get('max_voltage', None)
        channels = instrument.get('channels', [])
        new_channels = []
        for i in range(n):
            ch = channels[i] if i < len(channels) else {}
            ch['enabled'] = ch.get('enabled', False)
            ch['name'] = ch.get('name', channel_ids[i] if i < len(channel_ids) else f'CH{i+1}')
            ch['max_current'] = ch.get('max_current', max_current if max_current is not None else 0.0)
            ch['max_voltage'] = ch.get('max_voltage', max_voltage if max_voltage is not None else 0.0)
            new_channels.append(ch)
        self.channels = new_channels
        self.instrument['channels'] = self.channels
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        # Tabella canali
        self.table = self.create_channel_table(self.channels, [f'CH{i+1}' for i in range(len(self.channels))], None, None, self)
        layout.addWidget(self.table)
        # Pulsanti OK/Annulla
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
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

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem,
                              QCheckBox, QLineEdit, QDialogButtonBox, QLabel, QComboBox,
                              QSizePolicy, QHeaderView)
from PyQt6.QtGui import QDoubleValidator

class DataloggerConfigDialog(QDialog):
    def __init__(self, instrument, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurazione canali datalogger/multimetro")
        self.instrument = instrument
        # --- Sincronizza canali con capabilities ---
        capabilities = instrument.get('capabilities', {})
        n = capabilities.get('number_of_channel', instrument.get('num_channels', 0))
        channel_ids = capabilities.get('channel_ids', [])
        measurement_types = capabilities.get('measurement_types', [])
        channels = instrument.get('channels', [])
        new_channels = []
        for i in range(n):
            ch = channels[i] if i < len(channels) else {}
            ch['enabled'] = ch.get('enabled', False)
            ch['name'] = ch.get('name', channel_ids[i] if i < len(channel_ids) else f'CH{i+1}')
            ch['meas_type'] = ch.get('meas_type', measurement_types[0] if measurement_types else '')
            ch['attenuation'] = ch.get('attenuation', 1.0)
            ch['unit'] = ch.get('unit', 'V')
            ch['integration_time'] = ch.get('integration_time', 0.0)
            new_channels.append(ch)
        self.channels = new_channels
        self.instrument['channels'] = self.channels
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        # Tabella canali
        self.table = QTableWidget(len(self.channels), 6)
        self.table.setHorizontalHeaderLabels(["Abilita", "Nome variabile", "Tipo misura", "Attenuazione", "Unità", "Tempo integrazione"])
        for row, ch in enumerate(self.channels):
            # Abilita
            chk = QCheckBox()
            chk.setChecked(ch.get('enabled', False))
            chk.stateChanged.connect(lambda state, r=row: self.on_enabled_changed(r, state))
            self.table.setCellWidget(row, 0, chk)
            # Nome variabile
            name_edit = QLineEdit(ch.get('name', f'CH{row+1}'))
            name_edit.textChanged.connect(lambda val, r=row: self.on_name_changed(r, val))
            self.table.setCellWidget(row, 1, name_edit)
            # Tipo misura
            type_edit = QLineEdit(ch.get('meas_type', ''))
            type_edit.textChanged.connect(lambda val, r=row: self.on_meas_type_changed(r, val))
            self.table.setCellWidget(row, 2, type_edit)
            # Attenuazione
            att_edit = QLineEdit(str(ch.get('attenuation', 1.0)))
            att_edit.setValidator(QDoubleValidator(0.0000000001, 1e6, 10, att_edit))  # 10 cifre decimali
            att_edit.setPlaceholderText("Es: 0.5 (shunt 0.5Ω), 10.0 (amplif. x10)")
            att_edit.setToolTip("Fattore di attenuazione/amplificazione (max 10 cifre decimali).\n" +
                              "• Shunt: Resistenza in Ω (es: 0.1 per shunt 0.1Ω)\n" +
                              "• Amplificatore: Guadagno (es: 10.0 per amplif. x10)\n" +
                              "• Default: 1.0 (nessuna attenuazione)")
            att_edit.textChanged.connect(lambda val, r=row: self.on_attenuation_changed(r, val))
            self.table.setCellWidget(row, 3, att_edit)
            # Unità
            unit_edit = QLineEdit(ch.get('unit', ''))
            unit_edit.textChanged.connect(lambda val, r=row: self.on_unit_changed(r, val))
            self.table.setCellWidget(row, 4, unit_edit)
            # Tempo integrazione
            tint_edit = QLineEdit(str(ch.get('integration_time', 0.0)))
            tint_edit.setValidator(QDoubleValidator(0.0, 1e6, 3, tint_edit))
            tint_edit.setPlaceholderText("Tempo in secondi")
            tint_edit.textChanged.connect(lambda val, r=row: self.on_integration_time_changed(r, val))
            self.table.setCellWidget(row, 5, tint_edit)
        self.table.resizeColumnsToContents()
        # Configurazione ridimensionamento tabella per adattarsi al dialog
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # Checkbox
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Nome variabile
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # Tipo misura
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)  # Attenuazione
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Unità
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)  # Tempo integrazione
        
        layout.addWidget(self.table)
        # Pulsanti OK/Annulla
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def on_enabled_changed(self, row, state):
        self.channels[row]['enabled'] = bool(state)
        self.save_channels()
    def on_name_changed(self, row, val):
        self.channels[row]['name'] = val
        self.save_channels()
    def on_meas_type_changed(self, row, val):
        self.channels[row]['meas_type'] = val
        self.save_channels()
    def on_attenuation_changed(self, row, val):
        try:
            # Sostituisci la virgola con il punto per garantire il formato corretto
            val = str(val).replace(',', '.')
            self.channels[row]['attenuation'] = float(val)
        except Exception:
            self.channels[row]['attenuation'] = 1.0
        self.save_channels()
    def on_unit_changed(self, row, val):
        self.channels[row]['unit'] = val
        self.save_channels()
    def on_integration_time_changed(self, row, val):
        try:
            self.channels[row]['integration_time'] = float(val)
        except Exception:
            self.channels[row]['integration_time'] = 0.0
        self.save_channels()
    def save_channels(self):
        self.instrument['channels'] = self.channels

    def create_channel_table(channels, channel_ids, measurement_types, parent, callbacks):
        table = QTableWidget(len(channels), 6, parent)
        headers = ["Abilita", "ID Canale", "Tipo misura", "Attenuazione", "Unità", "Tempo integrazione"]
        table.setHorizontalHeaderLabels(headers)
        for row, ch in enumerate(channels):
            chk = QCheckBox()
            chk.setChecked(ch.get('enabled', False))
            chk.stateChanged.connect(lambda state, r=row: callbacks['enabled'](r, state))
            table.setCellWidget(row, 0, chk)
            id_label = QLabel(channel_ids[row] if row < len(channel_ids) else f'CH{row+1}')
            table.setCellWidget(row, 1, id_label)
            type_combo = QComboBox()
            type_combo.addItems(measurement_types)
            type_combo.setCurrentText(ch.get('meas_type', measurement_types[0] if measurement_types else ''))
            type_combo.currentTextChanged.connect(lambda val, r=row: callbacks['meas_type'](r, val))
            table.setCellWidget(row, 2, type_combo)
            att_edit = QLineEdit(str(ch.get('attenuation', 1.0)))
            att_edit.setValidator(QDoubleValidator(0.0, 1e6, 3, att_edit))
            att_edit.textChanged.connect(lambda val, r=row: callbacks['attenuation'](r, val))
            table.setCellWidget(row, 3, att_edit)
            unit_edit = QLineEdit(ch.get('unit', ''))
            unit_edit.textChanged.connect(lambda val, r=row: callbacks['unit'](r, val))
            table.setCellWidget(row, 4, unit_edit)
            tint_edit = QLineEdit(str(ch.get('integration_time', 0.0)))
            tint_edit.setValidator(QDoubleValidator(0.0, 1e6, 3, tint_edit))
            tint_edit.textChanged.connect(lambda val, r=row: callbacks['integration_time'](r, val))
            table.setCellWidget(row, 5, tint_edit)
        table.resizeColumnsToContents()
        return table

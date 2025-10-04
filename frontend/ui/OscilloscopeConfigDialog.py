import json
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, 
                              QCheckBox, QLineEdit, QDialogButtonBox, QLabel, QComboBox)
from PyQt6.QtGui import QDoubleValidator

class OscilloscopeConfigDialog(QDialog):
    """
    Dialog per configurare i canali dell'oscilloscopio.
    Permette di abilitare/disabilitare canali, assegnare nomi ai segnali e impostare Volt/div.
    """
    def __init__(self, instrument, translator=None, parent=None):
        super().__init__(parent)
        self.translator = translator
        self.setWindowTitle(self.translator.t('oscilloscope_channel_config') if self.translator else "Configurazione Canali Oscilloscopio")
        self.instrument = instrument
        
        # --- Sincronizza canali con capabilities ---
        capabilities = instrument.get('capabilities', {})
        n = capabilities.get('number_of_channel', instrument.get('num_channels', 4))
        channel_ids = capabilities.get('channel_ids', [f'CH{i+1}' for i in range(n)])
        
        channels = instrument.get('channels', [])
        new_channels = []
        
        # Scale volt/div comuni per oscilloscopi
        self.volt_div_options = [
            "1mV", "2mV", "5mV",
            "10mV", "20mV", "50mV",
            "100mV", "200mV", "500mV",
            "1V", "2V", "5V",
            "10V", "20V", "50V",
            "100V"
        ]
        
        for i in range(n):
            ch = channels[i] if i < len(channels) else {}
            ch['enabled'] = ch.get('enabled', False)
            ch['name'] = ch.get('name', channel_ids[i] if i < len(channel_ids) else f'CH{i+1}')
            ch['channel_id'] = channel_ids[i] if i < len(channel_ids) else f'CH{i+1}'
            ch['volt_per_div'] = ch.get('volt_per_div', '1V')
            ch['probe_attenuation'] = ch.get('probe_attenuation', 1.0)
            new_channels.append(ch)
        
        self.channels = new_channels
        self.instrument['channels'] = self.channels
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Tabella canali
        self.table = QTableWidget(len(self.channels), 5)
        headers = [
            self.translator.t('enable') if self.translator else "Abilita",
            self.translator.t('channel_id') if self.translator else "ID Canale",
            self.translator.t('signal_name') if self.translator else "Nome Segnale",
            self.translator.t('volt_per_div') if self.translator else "Volt/div",
            self.translator.t('probe_attenuation') if self.translator else "Attenuazione Sonda"
        ]
        self.table.setHorizontalHeaderLabels(headers)
        
        for row, ch in enumerate(self.channels):
            # Colonna 0: Checkbox Abilita
            chk = QCheckBox()
            chk.setChecked(ch.get('enabled', False))
            chk.stateChanged.connect(lambda state, r=row: self.on_enabled_changed(r, state))
            self.table.setCellWidget(row, 0, chk)
            
            # Colonna 1: ID Canale (read-only)
            id_label = QLabel(ch.get('channel_id', f'CH{row+1}'))
            id_label.setStyleSheet("padding: 5px;")
            self.table.setCellWidget(row, 1, id_label)
            
            # Colonna 2: Nome Segnale (editabile)
            name_edit = QLineEdit(ch.get('name', f'CH{row+1}'))
            name_edit.setPlaceholderText(self.translator.t('signal_name_placeholder') if self.translator else "es: Vout, Gate_Signal")
            name_edit.textChanged.connect(lambda val, r=row: self.on_name_changed(r, val))
            self.table.setCellWidget(row, 2, name_edit)
            
            # Colonna 3: Volt/div (combobox)
            volt_combo = QComboBox()
            volt_combo.addItems(self.volt_div_options)
            current_vdiv = ch.get('volt_per_div', '1V')
            idx = volt_combo.findText(current_vdiv)
            if idx >= 0:
                volt_combo.setCurrentIndex(idx)
            volt_combo.currentTextChanged.connect(lambda val, r=row: self.on_volt_div_changed(r, val))
            self.table.setCellWidget(row, 3, volt_combo)
            
            # Colonna 4: Attenuazione Sonda (editabile)
            probe_edit = QLineEdit(str(ch.get('probe_attenuation', 1.0)))
            probe_edit.setPlaceholderText("1, 10, 100")
            probe_edit.setValidator(QDoubleValidator(0.1, 1000.0, 2, probe_edit))
            probe_edit.textChanged.connect(lambda val, r=row: self.on_probe_changed(r, val))
            self.table.setCellWidget(row, 4, probe_edit)
        
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table)
        
        # Info label
        info_label = QLabel(
            self.translator.t('oscilloscope_config_info') if self.translator else 
            "Configura i canali abilitati, i nomi dei segnali e le scale volt/div per l'acquisizione dati."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: gray; font-size: 10px; padding: 5px;")
        layout.addWidget(info_label)
        
        # Pulsanti OK/Annulla
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def on_enabled_changed(self, row, state):
        """Aggiorna lo stato enabled del canale."""
        self.channels[row]['enabled'] = bool(state)
        self.save_channels()
    
    def on_name_changed(self, row, val):
        """Aggiorna il nome del segnale."""
        self.channels[row]['name'] = val
        self.save_channels()
    
    def on_volt_div_changed(self, row, val):
        """Aggiorna la scala volt/div."""
        self.channels[row]['volt_per_div'] = val
        self.save_channels()
    
    def on_probe_changed(self, row, val):
        """Aggiorna l'attenuazione della sonda."""
        try:
            self.channels[row]['probe_attenuation'] = float(val)
        except ValueError:
            self.channels[row]['probe_attenuation'] = 1.0
        self.save_channels()
    
    def save_channels(self):
        """Salva i canali nell'oggetto strumento."""
        self.instrument['channels'] = self.channels

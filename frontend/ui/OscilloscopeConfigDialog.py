# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

import json
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, 
                              QCheckBox, QLineEdit, QDialogButtonBox, QLabel,
                              QSizePolicy, QHeaderView)
from PyQt6.QtGui import QDoubleValidator

class OscilloscopeConfigDialog(QDialog):
    """
    Dialog per configurare i canali dell'oscilloscopio.
    Permette di abilitare/disabilitare canali, assegnare nomi ai segnali e impostare
    l'attenuazione della sonda. La scala Volt/div si configura nel file .was.
    """
    def __init__(self, instrument, translator=None, parent=None, load_instruments=None):
        super().__init__(parent)
        self.translator = translator
        self.setWindowTitle(self.translator.t('oscilloscope_channel_config') if self.translator else "Configurazione Canali Oscilloscopio")
        self.instrument = instrument
        self.load_instruments = load_instruments
        
        # --- Sync channels with capabilities ---
        capabilities = instrument.get('capabilities', {})
        n = capabilities.get('number_of_channels',
                             capabilities.get('number_of_channel',
                                              instrument.get('num_channels', 4)))
        if n <= 0 and self.load_instruments and self.instrument.get('model_id'):
            n = len(self._get_channel_ids(capabilities, n))
        channel_ids = self._get_channel_ids(capabilities, n)
        
        channels = instrument.get('channels', [])
        new_channels = []
        
        for i in range(n):
            ch = channels[i] if i < len(channels) else {}
            ch['enabled'] = ch.get('enabled', False)
            ch['name'] = ch.get('name', channel_ids[i] if i < len(channel_ids) else f'CH{i+1}')
            ch['channel_id'] = channel_ids[i] if i < len(channel_ids) else f'CH{i+1}'
            ch['probe_attenuation'] = ch.get('probe_attenuation', 1.0)
            new_channels.append(ch)
        
        self.channels = new_channels
        self.instrument['channels'] = self.channels
        self.init_ui()

    def _get_channel_ids(self, capabilities, n):
        """Deriva gli ID canali dal nuovo formato capabilities.channels[] o dai legacy."""
        channel_ids = capabilities.get('channel_ids', [])
        if channel_ids:
            return list(channel_ids)
        channels = capabilities.get('channels')
        if isinstance(channels, list) and channels:
            return [ch.get('channel_id', f'CH{i+1}') for i, ch in enumerate(channels)]
        if self.load_instruments and self.instrument.get('model_id'):
            return self.load_instruments.get_channel_ids(
                self.instrument.get('instrument_type', 'oscilloscope'),
                self.instrument.get('series', ''),
                self.instrument.get('model_id'))
        return [f'CH{i+1}' for i in range(n)]

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Tabella canali
        self.table = QTableWidget(len(self.channels), 4)
        headers = [
            self.translator.t('enable') if self.translator else "Abilita",
            self.translator.t('channel_id') if self.translator else "ID Canale",
            self.translator.t('signal_name') if self.translator else "Nome Segnale",
            self.translator.t('probe_attenuation') if self.translator else "Attenuazione Sonda"
        ]
        self.table.setHorizontalHeaderLabels(headers)
        
        for row, ch in enumerate(self.channels):
            # Column 0: Enable Checkbox
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
            
            # Colonna 3: Attenuazione Sonda (editabile)
            probe_edit = QLineEdit(str(ch.get('probe_attenuation', 1.0)))
            probe_edit.setPlaceholderText("1, 10, 100")
            probe_edit.setValidator(QDoubleValidator(0.1, 1000.0, 2, probe_edit))
            probe_edit.textChanged.connect(lambda val, r=row: self.on_probe_changed(r, val))
            self.table.setCellWidget(row, 3, probe_edit)
        
        self.table.resizeColumnsToContents()
        # Configurazione ridimensionamento tabella per adattarsi al dialog
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # Checkbox
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # ID canale
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # Nome segnale
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)  # Attenuazione
        
        layout.addWidget(self.table)
        
        # Info label
        info_label = QLabel(
            self.translator.t('oscilloscope_config_info') if self.translator else 
            "Configura i canali abilitati e i nomi dei segnali. La scala volt/div si imposta nel file .was."
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

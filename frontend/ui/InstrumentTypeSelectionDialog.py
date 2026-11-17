#!/usr/bin/env python3
# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QComboBox, QGroupBox, QTextEdit)

class InstrumentTypeSelectionDialog(QDialog):
    """Dialog per la selezione del tipo di strumento da aggiungere"""
    
    def __init__(self, load_instruments, translator, parent=None):
        super().__init__(parent)
        self.load_instruments = load_instruments
        self.translator = translator
        self.selected_type = None
        
        self.init_ui()
        
    def init_ui(self):
        """Inizializza l'interfaccia utente"""
        self.setWindowTitle(self.translator.t("select_instrument_type"))
        self.setModal(True)
        self.resize(400, 300)

        layout = QVBoxLayout()

        # Titolo
        title_label = QLabel(self.translator.t("select_instrument_type_desc"))
        title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title_label)

        # Gruppo selezione tipo
        type_group = QGroupBox(self.translator.t("instrument_type"))
        type_layout = QVBoxLayout()

        # ComboBox for type selection (chiavi singolari, come get_all_types())
        self.type_combo = QComboBox()
        for kind in ("power_supply", "datalogger", "oscilloscope", "electronic_load", "multimeter"):
            self.type_combo.addItem(self.translator.t(kind), kind)

        # Connect signal to update description
        self.type_combo.currentIndexChanged.connect(self.update_description)

        type_layout.addWidget(QLabel(self.translator.t("instrument_type_label")))
        type_layout.addWidget(self.type_combo)

        # Description of selected type
        self.description_text = QTextEdit()
        self.description_text.setMaximumHeight(100)
        self.description_text.setReadOnly(True)
        type_layout.addWidget(QLabel(self.translator.t("description_label")))
        type_layout.addWidget(self.description_text)

        type_group.setLayout(type_layout)
        layout.addWidget(type_group)

        # Aggiorna la descrizione iniziale
        self.update_description()

        # Pulsanti
        button_layout = QHBoxLayout()

        cancel_button = QPushButton(self.translator.t("cancel"))
        cancel_button.clicked.connect(self.reject)

        ok_button = QPushButton(self.translator.t("continue"))
        ok_button.clicked.connect(self.accept_selection)
        ok_button.setDefault(True)

        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(ok_button)

        layout.addLayout(button_layout)
        self.setLayout(layout)
        
    def update_description(self):
        """Aggiorna la descrizione in base al tipo selezionato"""
        kind = self.type_combo.currentData() or ""
        self.description_text.setPlainText(self.translator.t(f"{kind}_desc"))
        
    def accept_selection(self):
        """Accetta la selezione e chiude il dialog"""
        self.selected_type = self.type_combo.currentData()
        self.accept()
        
    def get_selected_type(self):
        """Restituisce il tipo di strumento selezionato"""
        return self.selected_type
#!/usr/bin/env python3

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QComboBox, QGroupBox, QTextEdit)
from PyQt6.QtCore import Qt

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
        self.setWindowTitle(self.translator.get("select_instrument_type", "Seleziona Tipo di Strumento"))
        self.setModal(True)
        self.resize(400, 300)
        
        layout = QVBoxLayout()
        
        # Titolo
        title_label = QLabel(self.translator.get("select_instrument_type_desc", "Seleziona il tipo di strumento da aggiungere:"))
        title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title_label)
        
        # Gruppo selezione tipo
        type_group = QGroupBox(self.translator.get("instrument_type", "Tipo di Strumento"))
        type_layout = QVBoxLayout()
        
        # ComboBox for type selection
        self.type_combo = QComboBox()
        self.type_combo.addItem("Alimentatore", "power_supplies")
        self.type_combo.addItem("Datalogger", "dataloggers") 
        self.type_combo.addItem("Oscilloscopio", "oscilloscopes")
        self.type_combo.addItem("Carico Elettronico", "electronic_loads")
        self.type_combo.addItem("Multimetro", "multimeters")
        
        # Connect signal to update description
        self.type_combo.currentTextChanged.connect(self.update_description)
        
        type_layout.addWidget(QLabel(self.translator.get("instrument_type_label", "Tipo:")))
        type_layout.addWidget(self.type_combo)
        
        # Description of selected type
        self.description_text = QTextEdit()
        self.description_text.setMaximumHeight(100)
        self.description_text.setReadOnly(True)
        type_layout.addWidget(QLabel(self.translator.get("description_label", "Descrizione:")))
        type_layout.addWidget(self.description_text)
        
        type_group.setLayout(type_layout)
        layout.addWidget(type_group)
        
        # Aggiorna la descrizione iniziale
        self.update_description()
        
        # Pulsanti
        button_layout = QHBoxLayout()
        
        cancel_button = QPushButton(self.translator.get("cancel", "Annulla"))
        cancel_button.clicked.connect(self.reject)
        
        ok_button = QPushButton(self.translator.get("continue", "Continua"))
        ok_button.clicked.connect(self.accept_selection)
        ok_button.setDefault(True)
        
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(ok_button)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
        
    def update_description(self):
        """Aggiorna la descrizione in base al tipo selezionato"""
        descriptions = {
            "Alimentatore": self.translator.get("power_supply_desc", "Dispositivi per fornire tensione e corrente controllate ai circuiti in test. Include alimentatori lineari, switching e programmabili."),
            "Datalogger": self.translator.get("datalogger_desc", "Strumenti per l'acquisizione e registrazione automatica di dati da sensori multipli. Ideali per monitoraggio a lungo termine."),
            "Oscilloscopio": self.translator.get("oscilloscope_desc", "Strumenti per la visualizzazione e analisi di segnali elettrici nel dominio del tempo e della frequenza."),
            "Carico Elettronico": self.translator.get("electronic_load_desc", "Dispositivi programmabili per simulare carichi resistivi, capacitivi o induttivi durante i test di alimentatori."),
            "Multimetro": self.translator.get("multimeter_desc", "Strumenti di misura universali per tensione, corrente, resistenza e altre grandezze elettriche.")
        }
        
        current_text = self.type_combo.currentText()
        description = descriptions.get(current_text, "Descrizione non disponibile.")
        self.description_text.setPlainText(description)
        
    def accept_selection(self):
        """Accetta la selezione e chiude il dialog"""
        self.selected_type = self.type_combo.currentData()
        self.accept()
        
    def get_selected_type(self):
        """Restituisce il tipo di strumento selezionato"""
        return self.selected_type
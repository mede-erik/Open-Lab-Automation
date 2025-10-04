#!/usr/bin/env python3

import json
import os
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QLineEdit, QTextEdit, QGroupBox, QComboBox,
                             QSpinBox, QDoubleSpinBox, QFormLayout, QRadioButton,
                             QButtonGroup, QWidget, QScrollArea, QCheckBox,
                             QMessageBox)
from PyQt6.QtCore import Qt

class PowerSupplyInstrumentDialog(QDialog):
    """Dialog specifico per la configurazione di alimentatori"""
    
    def __init__(self, load_instruments, translator, parent=None):
        super().__init__(parent)
        self.load_instruments = load_instruments
        self.translator = translator
        
        self.init_ui()
        
    def init_ui(self):
        """Inizializza l'interfaccia utente"""
        self.setWindowTitle(self.translator.get("power_supply_config", "Configurazione Alimentatore"))
        self.setModal(True)
        self.resize(600, 800)
        
        # Scroll area per contenere tutto
        scroll = QScrollArea()
        scroll_widget = QWidget()
        layout = QVBoxLayout()
        
        # === SEZIONE SERIE ===
        series_group = QGroupBox(self.translator.get("series_group", "Serie di Appartenenza"))
        series_layout = QVBoxLayout()
        
        # Radio buttons per scegliere se usare serie esistente o crearne una nuova
        self.series_button_group = QButtonGroup()
        self.existing_series_radio = QRadioButton(self.translator.get("existing_series", "Usa serie esistente"))
        self.new_series_radio = QRadioButton(self.translator.get("new_series", "Crea nuova serie"))
        self.existing_series_radio.setChecked(True)
        
        self.series_button_group.addButton(self.existing_series_radio, 0)
        self.series_button_group.addButton(self.new_series_radio, 1)
        
        series_layout.addWidget(self.existing_series_radio)
        series_layout.addWidget(self.new_series_radio)
        
        # ComboBox per serie esistenti
        self.existing_series_combo = QComboBox()
        self.load_existing_series()
        
        # Campi per nuova serie
        self.new_series_widget = QWidget()
        new_series_layout = QFormLayout()
        self.new_series_id = QLineEdit()
        self.new_series_name = QLineEdit()
        new_series_layout.addRow(self.translator.get("series_id", "ID Serie:"), self.new_series_id)
        new_series_layout.addRow(self.translator.get("series_name", "Nome Serie:"), self.new_series_name)
        self.new_series_widget.setLayout(new_series_layout)
        self.new_series_widget.setEnabled(False)
        
        series_layout.addWidget(QLabel(self.translator.get("existing_series_label", "Serie esistente:")))
        series_layout.addWidget(self.existing_series_combo)
        series_layout.addWidget(self.new_series_widget)
        
        # Connetti i segnali per abilitare/disabilitare i controlli
        self.existing_series_radio.toggled.connect(self.toggle_series_controls)
        
        series_group.setLayout(series_layout)
        layout.addWidget(series_group)
        
        # === SEZIONE INFORMAZIONI MODELLO ===
        model_group = QGroupBox(self.translator.get("model_info", "Informazioni Modello"))
        model_layout = QFormLayout()
        
        self.model_name = QLineEdit()
        self.manufacturer = QLineEdit()
        self.model_id = QLineEdit()
        
        model_layout.addRow(self.translator.get("model_name_label", "Nome Modello:"), self.model_name)
        model_layout.addRow(self.translator.get("manufacturer_label", "Produttore:"), self.manufacturer)
        model_layout.addRow(self.translator.get("model_id_label", "ID Modello:"), self.model_id)
        
        model_group.setLayout(model_layout)
        layout.addWidget(model_group)
        
        # === SEZIONE CANALI ===
        channels_group = QGroupBox(self.translator.get("channels_config", "Configurazione Canali"))
        channels_layout = QFormLayout()
        
        self.num_channels = QSpinBox()
        self.num_channels.setMinimum(1)
        self.num_channels.setMaximum(10)
        self.num_channels.setValue(1)
        self.num_channels.valueChanged.connect(self.update_channels_config)
        
        channels_layout.addRow(self.translator.get("num_channels_label", "Numero di Canali:"), self.num_channels)
        
        # Container per i canali
        self.channels_container = QWidget()
        self.channels_container_layout = QVBoxLayout()
        self.channels_container.setLayout(self.channels_container_layout)
        
        channels_layout.addRow(self.translator.get("configuration_label", "Configurazione:"), self.channels_container)
        channels_group.setLayout(channels_layout)
        layout.addWidget(channels_group)
        
        # Inizializza con un canale
        self.update_channels_config()
        
        # === SEZIONE INTERFACCE ===
        interface_group = QGroupBox(self.translator.get("supported_interfaces", "Interfacce Supportate"))
        interface_layout = QVBoxLayout()
        
        # Checkboxes per le interfacce
        self.usb_checkbox = QCheckBox(self.translator.get("usb_tmc", "USB-TMC"))
        self.ethernet_checkbox = QCheckBox(self.translator.get("ethernet_lxi", "Ethernet/LXI"))
        self.serial_checkbox = QCheckBox(self.translator.get("rs232_485", "RS-232/RS-485"))
        self.gpib_checkbox = QCheckBox(self.translator.get("gpib", "GPIB"))
        
        interface_layout.addWidget(self.usb_checkbox)
        interface_layout.addWidget(self.ethernet_checkbox)
        interface_layout.addWidget(self.serial_checkbox)
        interface_layout.addWidget(self.gpib_checkbox)
        
        interface_group.setLayout(interface_layout)
        layout.addWidget(interface_group)
        
        # === SEZIONE DOCUMENTAZIONE ===
        docs_group = QGroupBox(self.translator.get("documentation_group", "Documentazione"))
        docs_layout = QFormLayout()
        
        self.documentation_path = QLineEdit()
        self.notes = QTextEdit()
        self.notes.setMaximumHeight(100)
        
        docs_layout.addRow(self.translator.get("documentation_path_label", "Percorso Documentazione:"), self.documentation_path)
        docs_layout.addRow(self.translator.get("notes_label", "Note:"), self.notes)
        
        docs_group.setLayout(docs_layout)
        layout.addWidget(docs_group)
        
        # === PULSANTI ===
        button_layout = QHBoxLayout()
        
        cancel_button = QPushButton(self.translator.get("cancel", "Annulla"))
        cancel_button.clicked.connect(self.reject)
        
        save_button = QPushButton(self.translator.get("save_instrument", "Salva Strumento"))
        save_button.clicked.connect(self.save_instrument)
        save_button.setDefault(True)
        
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(save_button)
        
        layout.addLayout(button_layout)
        
        scroll_widget.setLayout(layout)
        scroll.setWidget(scroll_widget)
        scroll.setWidgetResizable(True)
        
        main_layout = QVBoxLayout()
        main_layout.addWidget(scroll)
        self.setLayout(main_layout)
        
    def load_existing_series(self):
        """Carica le serie esistenti di alimentatori"""
        try:
            series_list = self.load_instruments.get_series("power_supplies") or []
            self.existing_series_combo.clear()
            
            for series in series_list:
                series_name = series.get('series_name', series.get('series_id', 'Serie sconosciuta'))
                self.existing_series_combo.addItem(series_name, series)
                
        except Exception as e:
            print(f"Errore nel caricamento serie esistenti: {e}")
            
    def toggle_series_controls(self, checked):
        """Abilita/disabilita i controlli per serie esistenti/nuove"""
        if self.existing_series_radio.isChecked():
            self.existing_series_combo.setEnabled(True)
            self.new_series_widget.setEnabled(False)
        else:
            self.existing_series_combo.setEnabled(False)
            self.new_series_widget.setEnabled(True)
            
    def update_channels_config(self):
        """Aggiorna la configurazione dei canali in base al numero selezionato"""
        # Rimuovi i widget esistenti
        for i in reversed(range(self.channels_container_layout.count())):
            child = self.channels_container_layout.itemAt(i)
            if child:
                widget = child.widget()
                if widget:
                    widget.setParent(None)
            
        self.channel_configs = []
        
        for i in range(self.num_channels.value()):
            channel_widget = QGroupBox(f"{self.translator.get('channel_label', 'Canale')} {i+1}")
            channel_layout = QFormLayout()
            
            # Configurazione del canale
            channel_config = {
                'id': QLineEdit(f"CH{i+1}"),
                'label': QLineEdit(f"Channel {i+1}"),
                'voltage_min': QDoubleSpinBox(),
                'voltage_max': QDoubleSpinBox(),
                'current_min': QDoubleSpinBox(),
                'current_max': QDoubleSpinBox()
            }
            
            # Configura i limiti degli spinbox
            for key in ['voltage_min', 'voltage_max', 'current_min', 'current_max']:
                channel_config[key].setDecimals(3)
                channel_config[key].setMaximum(1000.0)
                
            channel_config['voltage_max'].setValue(30.0)  # Default
            channel_config['current_max'].setValue(5.0)   # Default
            
            channel_layout.addRow(self.translator.get("channel_id_label", "ID Canale:"), channel_config['id'])
            channel_layout.addRow(self.translator.get("channel_label_label", "Etichetta:"), channel_config['label'])
            channel_layout.addRow(self.translator.get("voltage_min_label", "Tensione Min (V):"), channel_config['voltage_min'])
            channel_layout.addRow(self.translator.get("voltage_max_label", "Tensione Max (V):"), channel_config['voltage_max'])
            channel_layout.addRow(self.translator.get("current_min_label", "Corrente Min (A):"), channel_config['current_min'])
            channel_layout.addRow(self.translator.get("current_max_label", "Corrente Max (A):"), channel_config['current_max'])
            
            channel_widget.setLayout(channel_layout)
            self.channels_container_layout.addWidget(channel_widget)
            self.channel_configs.append(channel_config)
            
    def save_instrument(self):
        """Salva lo strumento nella libreria"""
        if not self.validate_input():
            return
            
        try:
            # Determina se usare serie esistente o crearne una nuova
            if self.existing_series_radio.isChecked():
                selected_series = self.existing_series_combo.currentData()
                if not selected_series:
                    QMessageBox.warning(self, self.translator.get("error", "Errore"), self.translator.get("select_existing_series", "Seleziona una serie esistente."))
                    return
                target_series_id = selected_series.get('series_id')
            else:
                target_series_id = self.new_series_id.text().strip()
                if not target_series_id or not self.new_series_name.text().strip():
                    QMessageBox.warning(self, self.translator.get("error", "Errore"), self.translator.get("complete_new_series_fields", "Completa tutti i campi per la nuova serie."))
                    return
            
            # Crea l'entry del nuovo strumento
            instrument_data = self.create_instrument_entry()
            
            # Salva nella libreria
            success = self.save_to_library(instrument_data, target_series_id)
            
            if success:
                QMessageBox.information(self, self.translator.get("success", "Successo"), self.translator.get("power_supply_added", "Alimentatore aggiunto con successo!"))
                self.accept()
                
        except Exception as e:
            QMessageBox.critical(self, self.translator.get("error", "Errore"), f"{self.translator.get('save_instrument_error', 'Errore nel salvare lo strumento:')} {str(e)}")
            
    def validate_input(self):
        """Valida l'input dell'utente"""
        if not self.model_name.text().strip():
            QMessageBox.warning(self, self.translator.get("error", "Errore"), self.translator.get("model_name_required", "Il nome del modello è obbligatorio."))
            return False
            
        if not self.manufacturer.text().strip():
            QMessageBox.warning(self, self.translator.get("error", "Errore"), self.translator.get("manufacturer_required", "Il produttore è obbligatorio."))
            return False
            
        return True
        
    def create_instrument_entry(self):
        """Crea l'entry per il nuovo strumento"""
        # Crea le interfacce supportate
        interfaces = []
        if self.usb_checkbox.isChecked():
            interfaces.append({
                "type": "USB-TMC",
                "visa_resource_id_template": f"USB_PSU_{{{self.model_id.text() or 'ID'}}}",
                "address_format_example": "USB0::{VENDOR_ID}::{PRODUCT_ID}::{SERIAL_NUMBER}::INSTR"
            })
        if self.ethernet_checkbox.isChecked():
            interfaces.append({
                "type": "LXI",
                "visa_resource_id_template": f"LXI_PSU_{{{self.model_id.text() or 'ID'}}}",
                "address_format_example": "TCPIP0::{IP_ADDRESS}::inst0::INSTR"
            })
        if self.gpib_checkbox.isChecked():
            interfaces.append({
                "type": "GPIB",
                "visa_resource_id_template": f"GPIB_PSU_{{{self.model_id.text() or 'ID'}}}",
                "address_format_example": "GPIB0::{GPIB_ADDRESS}::INSTR"
            })
            
        # Crea i canali
        channels = []
        for config in self.channel_configs:
            channel = {
                "channel_id": config['id'].text(),
                "label": config['label'].text(),
                "voltage_output": {
                    "min": config['voltage_min'].value(),
                    "max": config['voltage_max'].value(),
                    "resolution": 3,
                    "units": "V"
                },
                "current_output": {
                    "min": config['current_min'].value(),
                    "max": config['current_max'].value(),
                    "resolution": 3,
                    "units": "A"
                }
            }
            channels.append(channel)
            
        instrument = {
            "id": f"PSU_{self.manufacturer.text().replace(' ', '')}_{self.model_id.text()}",
            "name": self.model_name.text(),
            "manufacturer": self.manufacturer.text(),
            "model": self.model_id.text() or self.model_name.text(),
            "interface": {
                "supported_connection_types": interfaces
            },
            "capabilities": {
                "number_of_channels": len(channels),
                "channels": channels,
                "read_voltage": True,
                "read_current": True
            }
        }
        
        if self.documentation_path.text().strip():
            instrument["documentation_path"] = self.documentation_path.text()
            
        if self.notes.toPlainText().strip():
            instrument["notes"] = self.notes.toPlainText()
            
        return instrument
        
    def save_to_library(self, instrument_data, target_series_id):
        """Salva lo strumento nella libreria JSON"""
        try:
            # Carica la libreria esistente
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            library_path = os.path.join(base_path, 'Instruments_LIB', 'instruments_lib.json')
            
            with open(library_path, 'r', encoding='utf-8') as f:
                library = json.load(f)
                
            # Se serve creare una nuova serie
            if self.new_series_radio.isChecked():
                new_series = {
                    "series_id": target_series_id,
                    "series_name": self.new_series_name.text(),
                    "common_scpi_commands": {
                        "reset": "*RST",
                        "clear_status": "*CLS", 
                        "identification_query": "*IDN?",
                        "error_query": "SYST:ERR?"
                    },
                    "models": [instrument_data]
                }
                
                # Aggiungi alla libreria
                if "power_supplies_series" not in library:
                    library["power_supplies_series"] = []
                library["power_supplies_series"].append(new_series)
            else:
                # Aggiungi alla serie esistente
                found = False
                for series in library.get("power_supplies_series", []):
                    if series.get("series_id") == target_series_id:
                        series["models"].append(instrument_data)
                        found = True
                        break
                        
                if not found:
                    raise Exception(f"Serie {target_series_id} non trovata")
                    
            # Salva la libreria aggiornata
            with open(library_path, 'w', encoding='utf-8') as f:
                json.dump(library, f, indent=2, ensure_ascii=False)
                
            return True
            
        except Exception as e:
            print(f"Errore nel salvare nella libreria: {e}")
            return False
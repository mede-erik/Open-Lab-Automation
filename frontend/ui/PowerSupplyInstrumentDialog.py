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
        self.setWindowTitle(self.translator.t("power_supply_config"))
        self.setModal(True)
        self.resize(600, 800)

        main_layout = QVBoxLayout(self)

        # Main container
        container_widget = QWidget()
        container_layout = QVBoxLayout(container_widget)

        # Scroll area to contain everything
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(container_widget)
        main_layout.addWidget(scroll_area)

        # === SERIES SELECTION SECTION ===
        series_group = QGroupBox(self.translator.t('select_series'))
        series_layout = QVBoxLayout()
        
        # Radio buttons to choose whether to use existing series or create a new one
        self.series_button_group = QButtonGroup()
        self.existing_series_radio = QRadioButton(self.translator.t("existing_series"))
        self.new_series_radio = QRadioButton(self.translator.t("new_series"))
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
        new_series_layout.addRow(self.translator.t("series_id"), self.new_series_id)
        new_series_layout.addRow(self.translator.t("series_name"), self.new_series_name)
        self.new_series_widget.setLayout(new_series_layout)
        self.new_series_widget.setEnabled(False)

        series_layout.addWidget(QLabel(self.translator.t("existing_series_label")))
        series_layout.addWidget(self.existing_series_combo)
        series_layout.addWidget(self.new_series_widget)

        # Connetti i segnali per abilitare/disabilitare i controlli
        self.existing_series_radio.toggled.connect(self.toggle_series_controls)

        series_group.setLayout(series_layout)
        main_layout.addWidget(series_group)

        # === SEZIONE INFORMAZIONI MODELLO ===
        model_group = QGroupBox(self.translator.t("model_info"))
        model_layout = QFormLayout()

        self.model_name = QLineEdit()
        self.manufacturer = QLineEdit()
        self.model_id = QLineEdit()

        model_layout.addRow(self.translator.t("model_name_label"), self.model_name)
        model_layout.addRow(self.translator.t("manufacturer_label"), self.manufacturer)
        model_layout.addRow(self.translator.t("model_id_label"), self.model_id)

        model_group.setLayout(model_layout)
        main_layout.addWidget(model_group)

        # === SEZIONE CANALI ===
        channels_group = QGroupBox(self.translator.t("channels_config"))
        channels_layout = QFormLayout()

        self.num_channels = QSpinBox()
        self.num_channels.setMinimum(1)
        self.num_channels.setMaximum(10)
        self.num_channels.setValue(1)
        self.num_channels.valueChanged.connect(self.update_channels_config)

        channels_layout.addRow(self.translator.t("num_channels_label"), self.num_channels)

        # Container per i canali
        self.channels_container = QWidget()
        self.channels_container_layout = QVBoxLayout()
        self.channels_container.setLayout(self.channels_container_layout)

        channels_layout.addRow(self.translator.t("configuration_label"), self.channels_container)
        channels_group.setLayout(channels_layout)
        main_layout.addWidget(channels_group)

        # Inizializza con un canale
        self.update_channels_config()

        # === SEZIONE INTERFACCE ===
        interface_group = QGroupBox(self.translator.t("supported_interfaces"))
        interface_layout = QVBoxLayout()

        # Checkboxes per le interfacce
        self.usb_checkbox = QCheckBox(self.translator.t("usb_tmc"))
        self.ethernet_checkbox = QCheckBox(self.translator.t("ethernet_lxi"))
        self.serial_checkbox = QCheckBox(self.translator.t("rs232_485"))
        self.gpib_checkbox = QCheckBox(self.translator.t("gpib"))

        interface_layout.addWidget(self.usb_checkbox)
        interface_layout.addWidget(self.ethernet_checkbox)
        interface_layout.addWidget(self.serial_checkbox)
        interface_layout.addWidget(self.gpib_checkbox)

        interface_group.setLayout(interface_layout)
        main_layout.addWidget(interface_group)

        # === SEZIONE DOCUMENTAZIONE ===
        docs_group = QGroupBox(self.translator.t("documentation_group"))
        docs_layout = QFormLayout()

        self.documentation_path = QLineEdit()
        self.notes = QTextEdit()
        self.notes.setMaximumHeight(100)

        docs_layout.addRow(self.translator.t("documentation_path_label"), self.documentation_path)
        docs_layout.addRow(self.translator.t("notes_label"), self.notes)

        docs_group.setLayout(docs_layout)
        main_layout.addWidget(docs_group)

        # === PULSANTI ===
        button_layout = QHBoxLayout()

        cancel_button = QPushButton(self.translator.t("cancel"))
        cancel_button.clicked.connect(self.reject)

        save_button = QPushButton(self.translator.t("save_instrument"))
        save_button.clicked.connect(self.save_instrument)
        save_button.setDefault(True)
        
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(save_button)

        main_layout.addLayout(button_layout)
        # Il layout principale è già stato creato e usato, non serve ricrearlo né ridefinirlo.
        # Lo scroll_area è già aggiunto a main_layout all'inizio del metodo.
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
            channel_widget = QGroupBox(f"{self.translator.t('channel_label')} {i+1}")
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
            
            channel_layout.addRow(self.translator.t("channel_id_label"), channel_config['id'])
            channel_layout.addRow(self.translator.t("channel_label_label"), channel_config['label'])
            channel_layout.addRow(self.translator.t("voltage_min_label"), channel_config['voltage_min'])
            channel_layout.addRow(self.translator.t("voltage_max_label"), channel_config['voltage_max'])
            channel_layout.addRow(self.translator.t("current_min_label"), channel_config['current_min'])
            channel_layout.addRow(self.translator.t("current_max_label"), channel_config['current_max'])
            
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
                    QMessageBox.warning(self, self.translator.t("error"), self.translator.t("select_existing_series"))
                    return
                target_series_id = selected_series.get('series_id')
            else:
                target_series_id = self.new_series_id.text().strip()
                if not target_series_id or not self.new_series_name.text().strip():
                    QMessageBox.warning(self, self.translator.t("error"), self.translator.t("complete_new_series_fields"))
                    return
            
            # Crea l'entry del nuovo strumento
            instrument_data = self.create_instrument_entry()
            
            # Salva nella libreria
            success = self.save_to_library(instrument_data, target_series_id)
            
            if success:
                QMessageBox.information(self, self.translator.t("success"), self.translator.t("power_supply_added"))
                self.accept()
                
        except Exception as e:
            QMessageBox.critical(self, self.translator.t("error"), f"{self.translator.t('save_instrument_error')} {str(e)}")
            
    def validate_input(self):
        """Valida l'input dell'utente"""
        if not self.model_name.text().strip():
            QMessageBox.warning(self, self.translator.t("error"), self.translator.t("model_name_required"))
            return False
            
        if not self.manufacturer.text().strip():
            QMessageBox.warning(self, self.translator.t("error"), self.translator.t("manufacturer_required"))
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
#!/usr/bin/env python3
# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

import json
import logging
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QLineEdit, QTextEdit, QGroupBox, QComboBox,
                             QSpinBox, QFormLayout, QRadioButton, QButtonGroup,
                             QWidget, QScrollArea, QCheckBox, QMessageBox)
from frontend.core.errorhandler import show_problem

logger = logging.getLogger('frontend.ui.DataloggerInstrumentDialog')


class DataloggerInstrumentDialog(QDialog):
    """Dialog specifico per la configurazione di datalogger"""
    
    def __init__(self, load_instruments, translator, parent=None):
        super().__init__(parent)
        self.load_instruments = load_instruments
        self.translator = translator
        
        self.init_ui()
        
    def init_ui(self):
        """Inizializza l'interfaccia utente"""
        self.setWindowTitle(self.translator.t("datalogger_config"))
        self.setModal(True)
        self.resize(600, 700)
        
        # Scroll area per contenere tutto
        scroll = QScrollArea()
        scroll_widget = QWidget()
        layout = QVBoxLayout()
        
        # === SEZIONE SERIE ===
        series_group = QGroupBox(self.translator.t("series_group"))
        series_layout = QVBoxLayout()
        
        # Radio buttons per scegliere se usare serie esistente o crearne una nuova
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
        layout.addWidget(series_group)
        
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
        layout.addWidget(model_group)
        
        # === SEZIONE CAPACITÀ ACQUISIZIONE ===
        capabilities_group = QGroupBox(self.translator.t("acquisition_capabilities"))
        capabilities_layout = QFormLayout()
        
        self.num_channels = QSpinBox()
        self.num_channels.setMinimum(1)
        self.num_channels.setMaximum(1000)
        self.num_channels.setValue(20)
        
        self.max_sample_rate = QSpinBox()
        self.max_sample_rate.setMinimum(1)
        self.max_sample_rate.setMaximum(1000000)
        self.max_sample_rate.setValue(2000)
        self.max_sample_rate.setSuffix(" sps")
        
        self.internal_memory = QSpinBox()
        self.internal_memory.setMinimum(1)
        self.internal_memory.setMaximum(100000)
        self.internal_memory.setValue(50)
        self.internal_memory.setSuffix(" kpoints")
        
        capabilities_layout.addRow(self.translator.t("num_channels_dl"), self.num_channels)
        capabilities_layout.addRow(self.translator.t("sample_rate_max"), self.max_sample_rate)
        capabilities_layout.addRow(self.translator.t("internal_memory"), self.internal_memory)
        
        capabilities_group.setLayout(capabilities_layout)
        layout.addWidget(capabilities_group)
        
        # === SEZIONE TIPI DI MISURA ===
        measurements_group = QGroupBox(self.translator.t("measurement_types"))
        measurements_layout = QVBoxLayout()
        
        # Checkboxes per i tipi di misura
        self.voltage_dc_checkbox = QCheckBox(self.translator.t("voltage_dc"))
        self.voltage_ac_checkbox = QCheckBox(self.translator.t("voltage_ac"))
        self.current_dc_checkbox = QCheckBox(self.translator.t("current_dc"))
        self.current_ac_checkbox = QCheckBox(self.translator.t("current_ac"))
        self.temperature_checkbox = QCheckBox(self.translator.t("temperature"))
        self.resistance_checkbox = QCheckBox(self.translator.t("resistance"))
        self.frequency_checkbox = QCheckBox(self.translator.t("frequency"))
        
        # Imposta alcuni default
        self.voltage_dc_checkbox.setChecked(True)
        self.current_dc_checkbox.setChecked(True)
        self.temperature_checkbox.setChecked(True)
        
        measurements_layout.addWidget(self.voltage_dc_checkbox)
        measurements_layout.addWidget(self.voltage_ac_checkbox)
        measurements_layout.addWidget(self.current_dc_checkbox)
        measurements_layout.addWidget(self.current_ac_checkbox)
        measurements_layout.addWidget(self.temperature_checkbox)
        measurements_layout.addWidget(self.resistance_checkbox)
        measurements_layout.addWidget(self.frequency_checkbox)
        
        measurements_group.setLayout(measurements_layout)
        layout.addWidget(measurements_group)
        
        # === SEZIONE SORGENTI TRIGGER ===
        trigger_group = QGroupBox(self.translator.t("trigger_sources"))
        trigger_layout = QVBoxLayout()
        
        self.trigger_bus_checkbox = QCheckBox(self.translator.t("bus_software"))
        self.trigger_ext_checkbox = QCheckBox(self.translator.t("external"))
        self.trigger_imm_checkbox = QCheckBox(self.translator.t("immediate"))
        self.trigger_timer_checkbox = QCheckBox(self.translator.t("timer"))
        
        # Imposta alcuni default
        self.trigger_bus_checkbox.setChecked(True)
        self.trigger_imm_checkbox.setChecked(True)
        
        trigger_layout.addWidget(self.trigger_bus_checkbox)
        trigger_layout.addWidget(self.trigger_ext_checkbox)
        trigger_layout.addWidget(self.trigger_imm_checkbox)
        trigger_layout.addWidget(self.trigger_timer_checkbox)
        
        trigger_group.setLayout(trigger_layout)
        layout.addWidget(trigger_group)
        
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
        layout.addWidget(interface_group)
        
        # === SEZIONE DOCUMENTAZIONE ===
        docs_group = QGroupBox(self.translator.t("documentation_group"))
        docs_layout = QFormLayout()
        
        self.documentation_path = QLineEdit()
        self.notes = QTextEdit()
        self.notes.setMaximumHeight(100)
        
        docs_layout.addRow(self.translator.t("documentation_path_label"), self.documentation_path)
        docs_layout.addRow(self.translator.t("notes_label"), self.notes)
        
        docs_group.setLayout(docs_layout)
        layout.addWidget(docs_group)
        
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
        
        layout.addLayout(button_layout)
        
        scroll_widget.setLayout(layout)
        scroll.setWidget(scroll_widget)
        scroll.setWidgetResizable(True)
        
        main_layout = QVBoxLayout()
        main_layout.addWidget(scroll)
        self.setLayout(main_layout)
        
    def load_existing_series(self):
        """Carica le serie esistenti di datalogger"""
        try:
            series_list = self.load_instruments.get_series("datalogger") or []
            self.existing_series_combo.clear()
            
            for series in series_list:
                series_name = series.get('series_name', series.get('series_id', self.translator.t('ilb_unknown_series')))
                self.existing_series_combo.addItem(series_name, series)
                
        except Exception as e:
            logger.warning("Loading the existing series failed: %s", e)
            
    def toggle_series_controls(self, checked):
        """Abilita/disabilita i controlli per serie esistenti/nuove"""
        if self.existing_series_radio.isChecked():
            self.existing_series_combo.setEnabled(True)
            self.new_series_widget.setEnabled(False)
        else:
            self.existing_series_combo.setEnabled(False)
            self.new_series_widget.setEnabled(True)
            
    def save_instrument(self):
        """Salva lo strumento nella libreria"""
        if not self.validate_input():
            return
            
        try:
            # Determina se usare serie esistente o crearne una nuova
            if self.existing_series_radio.isChecked():
                selected_series = self.existing_series_combo.currentData()
                if not selected_series:
                    show_problem(self, self.translator.t("error"), self.translator.t("select_existing_series"), code="VALID-004")
                    return
                target_series_id = selected_series.get('series_id')
            else:
                target_series_id = self.new_series_id.text().strip()
                if not target_series_id or not self.new_series_name.text().strip():
                    show_problem(self, self.translator.t("error"), self.translator.t("complete_new_series_fields"), code="VALID-004")
                    return
            
            # Crea l'entry del nuovo strumento
            instrument_data = self.create_instrument_entry()
            
            # Salva nella libreria
            success = self.save_to_library(instrument_data, target_series_id)
            
            if success:
                QMessageBox.information(self, self.translator.t("success"), self.translator.t("datalogger_added"))
                self.accept()
                
        except Exception as e:
            show_problem(self, self.translator.t("error"), f"{self.translator.t('save_instrument_error')} {str(e)}", code="LIB-008", exception=e, level="critical")
            
    def validate_input(self):
        """Valida l'input dell'utente"""
        if not self.model_name.text().strip():
            show_problem(self, self.translator.t("error"), self.translator.t("model_name_required"), code="VALID-004")
            return False
            
        if not self.manufacturer.text().strip():
            show_problem(self, self.translator.t("error"), self.translator.t("manufacturer_required"), code="VALID-004")
            return False
            
        return True
        
    def create_instrument_entry(self):
        """Crea l'entry per il nuovo strumento"""
        # Crea le interfacce supportate
        interfaces = []
        if self.usb_checkbox.isChecked():
            interfaces.append({
                "type": "USB-TMC",
                "visa_resource_id_template": f"USB_DL_{{{self.model_id.text() or 'ID'}}}",
                "address_format_example": "USB0::{VENDOR_ID}::{PRODUCT_ID}::{SERIAL_NUMBER}::INSTR"
            })
        if self.ethernet_checkbox.isChecked():
            interfaces.append({
                "type": "LXI",
                "visa_resource_id_template": f"LXI_DL_{{{self.model_id.text() or 'ID'}}}",
                "address_format_example": "TCPIP0::{IP_ADDRESS}::inst0::INSTR"
            })
        if self.gpib_checkbox.isChecked():
            interfaces.append({
                "type": "GPIB",
                "visa_resource_id_template": f"GPIB_DL_{{{self.model_id.text() or 'ID'}}}",
                "address_format_example": "GPIB0::{GPIB_ADDRESS}::INSTR"
            })
            
        # Crea i tipi di misura
        measurement_types = []
        if self.voltage_dc_checkbox.isChecked():
            measurement_types.append("VOLT:DC")
        if self.voltage_ac_checkbox.isChecked():
            measurement_types.append("VOLT:AC")
        if self.current_dc_checkbox.isChecked():
            measurement_types.append("CURR:DC")
        if self.current_ac_checkbox.isChecked():
            measurement_types.append("CURR:AC")
        if self.temperature_checkbox.isChecked():
            measurement_types.append("TEMP")
        if self.resistance_checkbox.isChecked():
            measurement_types.append("RES")
        if self.frequency_checkbox.isChecked():
            measurement_types.append("FREQ")
            
        # Crea le sorgenti trigger
        trigger_sources = []
        if self.trigger_bus_checkbox.isChecked():
            trigger_sources.append("BUS")
        if self.trigger_ext_checkbox.isChecked():
            trigger_sources.append("EXT")
        if self.trigger_imm_checkbox.isChecked():
            trigger_sources.append("IMM")
        if self.trigger_timer_checkbox.isChecked():
            trigger_sources.append("TIM")
            
        instrument = {
            "id": f"DL_{self.manufacturer.text().replace(' ', '')}_{self.model_id.text()}",
            "name": self.model_name.text(),
            "manufacturer": self.manufacturer.text(),
            "model": self.model_id.text() or self.model_name.text(),
            "interface": {
                "supported_connection_types": interfaces
            },
            "capabilities": {
                "channels": self.num_channels.value(),
                "max_sample_rate_sps": self.max_sample_rate.value(),
                "measurement_types": measurement_types,
                "trigger_source": trigger_sources,
                "internal_memory_kpoints": self.internal_memory.value()
            },
            "scpi_commands": {
                "setup_voltage_range": {
                    "description": "setup voltage range",
                    "set": {
                        "syntax": "SENS:VOLT:DC:RANG {range},(@{channels})",
                        "args": ["range", "channels"]
                    },
                    "query": None,
                    "parameters": {
                        "range": {
                            "type": "float"
                        },
                        "channels": {
                            "type": "string"
                        }
                    }
                }
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
            from frontend.core.LoadInstruments import get_library_path
            library_path = get_library_path()
            
            with open(library_path, 'r', encoding='utf-8') as f:
                library = json.load(f)
                
            # Se serve creare una nuova serie
            if self.new_series_radio.isChecked():
                new_series = {
                    "series_id": target_series_id,
                    "series_name": self.new_series_name.text(),
                    "common_scpi_commands": {
                        "reset": {
                            "description": "reset",
                            "set": {
                                "syntax": "*RST"
                            },
                            "query": None
                        },
                        "clear_status": {
                            "description": "clear status",
                            "set": {
                                "syntax": "*CLS"
                            },
                            "query": None
                        },
                        "identification_query": {
                            "description": "identification query",
                            "set": None,
                            "query": {
                                "syntax": "*IDN?",
                                "return_type": "string"
                            }
                        },
                        "error_query": {
                            "description": "error query",
                            "set": None,
                            "query": {
                                "syntax": "SYST:ERR?",
                                "return_type": "string"
                            }
                        },
                        "select_channels": {
                            "description": "select channels",
                            "set": {
                                "syntax": "ROUT:SCAN (@{channels})",
                                "args": ["channels"]
                            },
                            "query": None,
                            "parameters": {
                                "channels": {
                                    "type": "string"
                                }
                            }
                        },
                        "read_scan": {
                            "description": "read scan",
                            "set": None,
                            "query": {
                                "syntax": "READ?",
                                "return_type": "string"
                            }
                        },
                        "trigger_bus": {
                            "description": "trigger bus",
                            "set": {
                                "syntax": "*TRG"
                            },
                            "query": None
                        }
                    },
                    "models": [instrument_data]
                }
                
                # Aggiungi alla libreria
                if "dataloggers_series" not in library:
                    library["dataloggers_series"] = []
                library["dataloggers_series"].append(new_series)
            else:
                # Aggiungi alla serie esistente
                found = False
                for series in library.get("dataloggers_series", []):
                    if series.get("series_id") == target_series_id:
                        series["models"].append(instrument_data)
                        found = True
                        break
                        
                if not found:
                    raise ValueError(f"{self.translator.t('ilb_series_not_found')}: {target_series_id}")
                    
            # Salva la libreria aggiornata
            with open(library_path, 'w', encoding='utf-8') as f:
                json.dump(library, f, indent=2, ensure_ascii=False)
                
            return True
            
        except Exception as e:
            logger.error("Saving to the library failed: %s", e)
            return False
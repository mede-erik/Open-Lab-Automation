import json
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QComboBox, QSpinBox, 
    QDialogButtonBox, QLabel, QMessageBox, QTextEdit
)

class AddInstrumentDialog(QDialog):
    def __init__(self, load_instruments, translator, parent=None):
        super().__init__(parent)
        self.load_instruments = load_instruments
        self.translator = translator
        
        t = getattr(self.translator, 't', lambda s: s)
        self.setWindowTitle(t('add_new_instrument'))
        
        self.main_layout = QVBoxLayout(self)
        
        # Form
        self.form_layout = QFormLayout()
        
        # Instrument Type
        self.type_combo = QComboBox()
        self.instrument_types = self.load_instruments.get_all_types()
        self.type_combo.addItems([t(it) for it in self.instrument_types])
        self.form_layout.addRow(QLabel(t('instrument_type')), self.type_combo)
        
        # Series
        self.series_combo = QComboBox()
        self.series_combo.setEditable(True)
        self.form_layout.addRow(QLabel(t('instrument_series')), self.series_combo)
        
        # Model Name
        self.model_name_edit = QLineEdit()
        self.form_layout.addRow(QLabel(t('model_name')), self.model_name_edit)
        
        # Manufacturer
        self.manufacturer_edit = QLineEdit()
        self.form_layout.addRow(QLabel(t('manufacturer')), self.manufacturer_edit)
        
        # Model ID
        self.model_id_edit = QLineEdit()
        self.form_layout.addRow(QLabel(t('model_id')), self.model_id_edit)
        
        # Number of Channels
        self.channels_spin = QSpinBox()
        self.channels_spin.setRange(0, 128)
        self.form_layout.addRow(QLabel(t('number_of_channels')), self.channels_spin)
        
        # Documentation Path
        self.doc_path_edit = QLineEdit()
        self.form_layout.addRow(QLabel(t('documentation_path')), self.doc_path_edit)
        
        # Notes
        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(80)
        self.form_layout.addRow(QLabel(t('notes')), self.notes_edit)
        
        self.main_layout.addLayout(self.form_layout)
        
        # Buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.main_layout.addWidget(self.button_box)
        
        self.setLayout(self.main_layout)
        
        # Connections
        self.type_combo.currentTextChanged.connect(self.update_series_combo)
        self.update_series_combo(self.type_combo.currentText())

    def update_series_combo(self, type_text):
        # Map translated type back to internal key
        type_key = next((key for key in self.instrument_types if self.translator.t(key) == type_text), None)
        if not type_key:
            return
            
        self.series_combo.clear()
        series_list = self.load_instruments.get_series(type_key)
        series_names = [s.get('series_name', s.get('series_id')) for s in series_list]
        self.series_combo.addItems(series_names)

    def get_instrument_data(self):
        # Map translated type back to internal key
        type_text = self.type_combo.currentText()
        type_key = next((key for key in self.instrument_types if self.translator.t(key) == type_text), None)

        return {
            "type": type_key,
            "series": self.series_combo.currentText(),
            "model_name": self.model_name_edit.text(),
            "manufacturer": self.manufacturer_edit.text(),
            "model_id": self.model_id_edit.text(),
            "num_channels": self.channels_spin.value(),
            "documentation_path": self.doc_path_edit.text(),
            "notes": self.notes_edit.toPlainText()
        }

    def accept(self):
        """Override accept to validate and save the instrument"""
        if not self.validate_input():
            return
            
        try:
            self.save_to_library()
            super().accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save instrument: {str(e)}")

    def validate_input(self):
        """Validate user input"""
        if not self.model_name_edit.text().strip():
            QMessageBox.warning(self, "Validation Error", "Model name is required")
            return False
        if not self.manufacturer_edit.text().strip():
            QMessageBox.warning(self, "Validation Error", "Manufacturer is required")
            return False
        if not self.model_id_edit.text().strip():
            QMessageBox.warning(self, "Validation Error", "Model ID is required")
            return False
        return True

    def save_to_library(self):
        """Save the new instrument to instruments_lib.json"""
        import os
        # Costruisci il percorso della libreria strumenti
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        library_path = os.path.join(base_path, 'Instruments_LIB', 'instruments_lib.json')
        
        # Read current library
        with open(library_path, 'r', encoding='utf-8') as f:
            library_data = json.load(f)
        
        # Get instrument data
        instrument_data = self.get_instrument_data()
        
        # Create new instrument entry
        new_instrument = self.create_instrument_entry(instrument_data)
        
        # Find or create series
        type_key = instrument_data["type"]
        series_key = f"{type_key}_series"
        
        if series_key not in library_data["instrument_library"]:
            library_data["instrument_library"][series_key] = []
        
        # Find existing series or create new one
        series_name = instrument_data["series"]
        existing_series = None
        for series in library_data["instrument_library"][series_key]:
            if series.get("series_name") == series_name:
                existing_series = series
                break
        
        if existing_series:
            # Add to existing series
            existing_series["models"].append(new_instrument)
        else:
            # Create new series
            new_series = self.create_series_entry(instrument_data, new_instrument)
            library_data["instrument_library"][series_key].append(new_series)
        
        # Save back to file
        with open(library_path, 'w', encoding='utf-8') as f:
            json.dump(library_data, f, indent=2, ensure_ascii=False)

    def create_instrument_entry(self, data):
        """Create a new instrument entry"""
        channels = []
        for i in range(data["num_channels"]):
            channels.append({
                "channel_id": f"CH{i+1}",
                "label": f"Channel {i+1}",
                "voltage_output": {"min": 0.0, "max": 0.0, "resolution": 3, "units": "V"},
                "current_output": {"min": 0.0, "max": 0.0, "resolution": 3, "units": "A"}
            })
        
        instrument = {
            "id": data["model_id"],
            "name": data["model_name"],
            "manufacturer": data["manufacturer"],
            "model": data["model_name"].split()[-1] if " " in data["model_name"] else data["model_name"],
            "documentation_path": data["documentation_path"] or f"docs/{data['manufacturer']}/manual.pdf",
            "interface": {
                "supported_connection_types": [
                    {
                        "type": "USB-TMC",
                        "visa_resource_id_template": f"USB_{data['type'].upper()}_{'{serial_number}'}",
                        "address_format_example": "USB0::{VENDOR_ID}::{PRODUCT_ID}::{SERIAL_NUMBER}::INSTR"
                    }
                ]
            },
            "capabilities": {
                "number_of_channels": data["num_channels"],
                "channels": channels,
                "read_voltage": True,
                "read_current": True
            },
            "scpi_commands": {}
        }
        
        if data["notes"]:
            instrument["notes"] = data["notes"]
            
        return instrument

    def create_series_entry(self, data, instrument):
        """Create a new series entry"""
        return {
            "series_id": f"{data['manufacturer']}_{data['series']}_Series",
            "series_name": f"{data['manufacturer']} {data['series']} Series",
            "common_scpi_commands": {
                "reset": "*RST",
                "clear_status": "*CLS",
                "identification_query": "*IDN?",
                "error_query": "SYST:ERR?",
                "self_test": "*TST?"
            },
            "models": [instrument]
        }


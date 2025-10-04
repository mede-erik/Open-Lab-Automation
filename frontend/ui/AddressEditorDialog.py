import json
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QComboBox, QLabel, QLineEdit, QDialogButtonBox, QWidget, QFormLayout
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox
from frontend.core.LoadInstruments import LoadInstruments


class AddressEditorDialog(QDialog):
    def __init__(self, instrument, load_instruments: LoadInstruments, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Address Editor")
        self.instrument = instrument
        self.load_instruments = load_instruments
        self.address = instrument.get('address', '')
        self.conn_type = None
        self.fields = {}
        self.templates = self.get_templates_for_instrument()
        self.init_ui()

    def get_templates_for_instrument(self):
        t = self.instrument.get('type', '').lower()
        series_id = self.instrument.get('series', '')
        model_id = self.instrument.get('model_id', self.instrument.get('model', ''))
        # Usa LoadInstruments per ottenere i template VISA
        visa_templates = self.load_instruments.find_instrument(type_name=t, series_id=series_id, model_id=model_id)
        if visa_templates and 'interface' in visa_templates and 'visa_templates' in visa_templates['interface']:
            return visa_templates['interface']['visa_templates']
        # Default
        return {
            'LXI': 'TCPIP0::{ip}::INSTR',
            'USB': 'USB0::{vendor_id}::{product_id}::{serial}::INSTR',
            'GPIB': 'GPIB0::{gpib_addr}::INSTR'
        }

    def init_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        # Tipo connessione
        self.conn_combo = QComboBox()
        self.conn_combo.addItems(list(self.templates.keys()))
        self.conn_combo.currentTextChanged.connect(self.on_conn_type_changed)
        form.addRow("Tipo connessione", self.conn_combo)
        # Placeholder per campi dinamici
        self.fields_widget = QWidget()
        self.fields_layout = QFormLayout(self.fields_widget)
        form.addRow(self.fields_widget)
        layout.addLayout(form)
        # Pulsanti OK/Annulla
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
        # Mostra campi iniziali
        self.on_conn_type_changed(self.conn_combo.currentText())

    def on_conn_type_changed(self, conn_type):
        self.conn_type = conn_type
        # Pulisci campi precedenti
        while self.fields_layout.count():
            child = self.fields_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.fields = {}
        # Analizza template per trovare i parametri richiesti
        template = self.templates.get(conn_type, '')
        params = [p[1] for p in list(__import__('string').Formatter().parse(template)) if p[1]]
        for param in params:
            edit = QLineEdit()
            self.fields[param] = edit
            self.fields_layout.addRow(param, edit)
        # Se già presente un indirizzo, prova a precompilare i campi
        if self.address and '{' in template:
            try:
                import re
                vals = re.findall(r'([\w]+)=([\w\.:]+)', self.address)
                for k, v in vals:
                    if k in self.fields:
                        self.fields[k].setText(v)
            except Exception:
                pass

    def get_address(self):
        # Compila la stringa secondo il template
        template = self.templates.get(self.conn_type, '')
        vals = {k: self.fields[k].text() for k in self.fields}
        try:
            addr = template.format(**vals)
        except Exception:
            addr = template
        return addr

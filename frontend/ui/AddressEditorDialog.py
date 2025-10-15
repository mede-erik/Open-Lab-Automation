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
        t = self.instrument.get('instrument_type', self.instrument.get('type', '')).lower()
        series_id = self.instrument.get('series', '')
        model_id = self.instrument.get('model_id', self.instrument.get('model', ''))
        
        print(f"[AddressEditor] Cercando templates per: type={t}, series={series_id}, model={model_id}")
        
        # Cerca nella libreria strumenti i tipi di comunicazione supportati
        instrument_data = self.load_instruments.find_instrument(type_name=t, series_id=series_id, model_id=model_id)
        
        if instrument_data and 'interface' in instrument_data:
            interface_data = instrument_data['interface']
            
            # Controlla se ha 'supported_connection_types' (nuovo formato)
            if 'supported_connection_types' in interface_data:
                templates = {}
                for conn_type in interface_data['supported_connection_types']:
                    conn_name = conn_type.get('type', '')
                    template = conn_type.get('address_format_example', '')
                    
                    if conn_name == 'LXI':
                        templates['LXI (VXI-11)'] = 'TCPIP0::{ip}::inst0::INSTR'
                    elif conn_name == 'USB-TMC':
                        templates['USB-TMC'] = 'USB0::{vendor_id}::{product_id}::{serial}::INSTR'
                    elif conn_name == 'GPIB':
                        templates['GPIB'] = 'GPIB0::{gpib_addr}::INSTR'
                    elif conn_name == 'SERIAL':
                        templates['SERIAL'] = 'ASRL{com_port}::INSTR'
                    elif conn_name == 'USB-SERIAL':
                        templates['USB-SERIAL'] = 'ASRL{com_port}::INSTR'
                    elif template:
                        # Usa il template personalizzato se disponibile
                        templates[conn_name] = template
                
                if templates:
                    print(f"[AddressEditor] Templates trovati: {templates}")
                    return templates
            
            # Fallback per formato legacy 'visa_templates'
            if 'visa_templates' in interface_data:
                print(f"[AddressEditor] Usando templates legacy")
                return interface_data['visa_templates']
        
        print(f"[AddressEditor] Nessun template trovato, usando default")
        # Default con tutte le opzioni disponibili
        return {
            'LXI (VXI-11)': 'TCPIP0::{ip}::inst0::INSTR',
            'LXI (HiSLIP)': 'TCPIP0::{ip}::hislip0::INSTR', 
            'LXI (Socket)': 'TCPIP0::{ip}::{port}::SOCKET',
            'USB-TMC': 'USB0::{vendor_id}::{product_id}::{serial}::INSTR',
            'GPIB': 'GPIB0::{gpib_addr}::INSTR',
            'SERIAL': 'ASRL{com_port}::INSTR',
            'USB-SERIAL': 'ASRL{com_port}::INSTR'
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
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
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
            if child and child.widget():
                child.widget().deleteLater()
        self.fields = {}
        
        # Analizza template per trovare i parametri richiesti
        template = self.templates.get(conn_type, '') if conn_type else ''
        params = [p[1] for p in list(__import__('string').Formatter().parse(template)) if p[1]]
        
        # Crea campi per ogni parametro
        for param in params:
            edit = QLineEdit()
            
            # Aggiungi suggerimenti per campi specifici
            if param == 'com_port':
                edit.setPlaceholderText("es: 3 (per COM3)")
                edit.setToolTip("Numero della porta COM (Windows) o /dev/ttyUSB* (Linux)")
            elif param == 'ip':
                edit.setPlaceholderText("es: 192.168.1.100")
                edit.setToolTip("Indirizzo IP dello strumento")
            elif param == 'gpib_addr':
                edit.setPlaceholderText("es: 7")
                edit.setToolTip("Indirizzo GPIB (1-30)")
            elif param == 'vendor_id':
                edit.setPlaceholderText("es: 0x0957")
                edit.setToolTip("Vendor ID USB in formato hex")
            elif param == 'product_id':
                edit.setPlaceholderText("es: 0x2007")
                edit.setToolTip("Product ID USB in formato hex")
            elif param == 'serial':
                edit.setPlaceholderText("es: MY12345678")
                edit.setToolTip("Numero seriale del dispositivo")
            elif param == 'port':
                edit.setPlaceholderText("es: 5025")
                edit.setToolTip("Porta TCP per connessione socket")
            
            self.fields[param] = edit
            self.fields_layout.addRow(param.replace('_', ' ').title(), edit)
        
        # Aggiungi info speciali per comunicazione seriale
        if conn_type in ['SERIAL', 'USB-SERIAL']:
            info_label = QLabel("⚠️ Comunicazione seriale: Assicurarsi che i parametri seriali siano corretti (9600 baud, 8N1)")
            info_label.setWordWrap(True)
            info_label.setStyleSheet("color: orange; font-size: 10px; margin: 5px;")
            self.fields_layout.addRow(info_label)
        
        # Se già presente un indirizzo, prova a precompilare i campi
        if self.address and template and '{' in template:
            self.populate_fields_from_address()
    
    def populate_fields_from_address(self):
        """Cerca di estrarre i valori dall'indirizzo esistente"""
        try:
            # Per indirizzi ASRL (seriali)
            if 'ASRL' in self.address:
                import re
                match = re.search(r'ASRL(\d+)::INSTR', self.address)
                if match and 'com_port' in self.fields:
                    self.fields['com_port'].setText(match.group(1))
            
            # Per indirizzi TCPIP
            elif 'TCPIP' in self.address:
                import re
                match = re.search(r'TCPIP0::([^:]+)::', self.address)
                if match and 'ip' in self.fields:
                    self.fields['ip'].setText(match.group(1))
            
            # Per indirizzi GPIB
            elif 'GPIB' in self.address:
                import re
                match = re.search(r'GPIB0::(\d+)::INSTR', self.address)
                if match and 'gpib_addr' in self.fields:
                    self.fields['gpib_addr'].setText(match.group(1))
            
            # Per indirizzi USB
            elif 'USB' in self.address:
                import re
                match = re.search(r'USB0::([^:]+)::([^:]+)::([^:]+)::INSTR', self.address)
                if match:
                    if 'vendor_id' in self.fields:
                        self.fields['vendor_id'].setText(match.group(1))
                    if 'product_id' in self.fields:
                        self.fields['product_id'].setText(match.group(2))
                    if 'serial' in self.fields:
                        self.fields['serial'].setText(match.group(3))
                        
        except Exception as e:
            print(f"[AddressEditor] Errore nel parsing dell'indirizzo esistente: {e}")

    def get_address(self):
        # Compila la stringa secondo il template
        if not self.conn_type:
            return self.address
            
        template = self.templates.get(self.conn_type, '')
        if not template:
            return self.address
            
        vals = {k: self.fields[k].text() for k in self.fields}
        
        try:
            # Validazione speciale per campi seriali
            if self.conn_type in ['SERIAL', 'USB-SERIAL'] and 'com_port' in vals:
                com_port = vals['com_port'].strip()
                if not com_port.isdigit():
                    QMessageBox.warning(self, "Errore validazione", 
                                      "La porta COM deve essere un numero (es: 3 per COM3)")
                    return None
                vals['com_port'] = com_port
            
            # Validazione per GPIB
            elif self.conn_type == 'GPIB' and 'gpib_addr' in vals:
                gpib_addr = vals['gpib_addr'].strip()
                if not gpib_addr.isdigit() or not (1 <= int(gpib_addr) <= 30):
                    QMessageBox.warning(self, "Errore validazione", 
                                      "L'indirizzo GPIB deve essere un numero tra 1 e 30")
                    return None
            
            addr = template.format(**vals)
            print(f"[AddressEditor] Indirizzo generato: {addr}")
            return addr
            
        except Exception as e:
            print(f"[AddressEditor] Errore nella formattazione: {e}")
            QMessageBox.warning(self, "Errore", f"Errore nella formattazione dell'indirizzo: {e}")
            return None

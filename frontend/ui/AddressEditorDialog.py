# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

import logging
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QComboBox, QLabel, QLineEdit, QDialogButtonBox, QWidget, QFormLayout
from PyQt6.QtWidgets import QHBoxLayout, QPushButton
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QMessageBox
from frontend.core import gpib_settings
from frontend.core.LoadInstruments import LoadInstruments
from frontend.core.Translator import Translator
from frontend.ui.module_translator import CatalogTranslator
from ola.gpib_adapter import FAMILY_PROLOGIX, FAMILY_VISA, GpibError
from frontend.ui.theme_utils import set_class

logger = logging.getLogger('frontend.ui.AddressEditorDialog')


class AddressEditorDialog(QDialog):
    def __init__(self, instrument, load_instruments: LoadInstruments, parent=None):
        super().__init__(parent)
        lang = QSettings('LabAutomation', 'App').value('language', '', type=str) or None
        # the language of the application: the one of the window that opens the editor
        self.translator = getattr(parent, 'translator', None) or Translator(default_lang=lang or 'en')
        self.setWindowTitle(self._t("addr_title"))
        self.instrument = instrument
        self.load_instruments = load_instruments
        # the .inst file keeps the address as visa_address: show it when the editor opens
        self.address = instrument.get('visa_address', instrument.get('address', ''))
        self.conn_type = None
        self.address_type = None  # the connection type of the address, see type_of_address
        self.fields = {}
        self.templates = self.get_templates_for_instrument()
        # GPIB: the adapters configured in Tools > GPIB adapters (GPIB0, GPIB1, Prologix...)
        self.gpib_adapters = gpib_settings.adapters_or_default()
        self.adapter_combo = None
        self.gpib_tr = CatalogTranslator("gpib", lang=lang)
        self.init_ui()

    def _t(self, key):
        return str(self.translator.t(key))

    def get_templates_for_instrument(self):
        t = self.instrument.get('instrument_type', self.instrument.get('type', '')).lower()
        series_id = self.instrument.get('series', '')
        model_id = self.instrument.get('model_id', self.instrument.get('model', ''))
        
        logger.debug(f"Looking for templates: type={t}, series={series_id}, model={model_id}")
        
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
                    elif conn_name == 'WAVEFORMS':
                        # Digilent device through the WaveForms runtime, not VISA
                        templates['WAVEFORMS'] = 'DWF::{serial}'
                    elif template:
                        # Usa il template personalizzato se disponibile
                        templates[conn_name] = template
                
                if templates:
                    logger.debug(f"Templates found: {list(templates.keys())}")
                    return templates
            
            if 'visa_templates' in interface_data:
                logger.debug("Using legacy templates")
                return interface_data['visa_templates']
        
        logger.debug("No templates found, using defaults")
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
        form.addRow(self._t("connection_type"), self.conn_combo)
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
        # an existing address opens the editor on its own connection type
        self.address_type = self.type_of_address(self.address)
        if self.address_type:
            self.conn_combo.setCurrentText(self.address_type)
        elif self.address:
            # the library lists no connection of this kind for the model: say so, and keep the
            # address unless a field is filled in
            note = QLabel("⚠️ " + self._t("addr_not_in_library").format(address=self.address))
            note.setWordWrap(True)
            set_class(note, "warning")
            layout.insertWidget(0, note)
        # Mostra campi iniziali
        self.on_conn_type_changed(self.conn_combo.currentText())

    @staticmethod
    def is_gpib_address(address):
        a = (address or '').strip().upper()
        return a.startswith('GPIB') or a.startswith('PROLOGIX::')

    def type_of_address(self, address):
        """The connection type of the list that builds ``address`` (None if none does: the first
        type is shown, and the address is kept until a field is filled in)."""
        a = (address or '').strip().upper()
        if not a:
            return None
        if self.is_gpib_address(a):
            return next((k for k in self.templates if self.is_gpib_type(k)), None)
        for name, template in self.templates.items():
            if a == 'DWF' and (template or '').upper().startswith('DWF'):
                return name  # a Digilent device with no serial: the first one found
            prefix = (template or '').split('{', 1)[0].upper()
            if not prefix:
                continue
            if a.startswith(prefix) and (
                ('::INST0::' in a) == ('::INST0::' in template.upper())
                and ('::HISLIP' in a) == ('::HISLIP' in template.upper())
                and a.endswith('::SOCKET') == template.upper().endswith('::SOCKET')
            ):
                return name
        return None

    def is_gpib_type(self, conn_type):
        template = self.templates.get(conn_type, '') or ''
        return template.upper().startswith('GPIB') and '{gpib_addr}' in template

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
            t = self._t
            if param == 'com_port':
                edit.setPlaceholderText(t("addr_com_port_placeholder"))
                edit.setToolTip(t("addr_com_port_tip"))
                try:  # suggest the ports that are present
                    from PyQt6.QtWidgets import QCompleter
                    from serial.tools import list_ports
                    edit.setCompleter(QCompleter([p.device for p in list_ports.comports()], edit))
                except Exception:
                    pass  # pyserial missing: the port is typed by hand
            elif param == 'ip':
                edit.setPlaceholderText(t("addr_example").format(example="192.168.1.100"))
                edit.setToolTip(t("addr_ip_tip"))
            elif param == 'gpib_addr':
                edit.setPlaceholderText(t("addr_example").format(example="7"))
                edit.setToolTip(t("addr_gpib_tip"))
            elif param == 'vendor_id':
                edit.setPlaceholderText(t("addr_example").format(example="0x0957"))
                edit.setToolTip(t("addr_vendor_tip"))
            elif param == 'product_id':
                edit.setPlaceholderText(t("addr_example").format(example="0x2007"))
                edit.setToolTip(t("addr_product_tip"))
            elif param == 'serial' and conn_type == 'WAVEFORMS':
                edit.setPlaceholderText(t("addr_dwf_placeholder"))
                edit.setToolTip(t("addr_dwf_tip"))
                try:  # suggest the devices WaveForms sees now
                    from PyQt6.QtWidgets import QCompleter
                    from ola.drivers.waveforms import DwfApi, load_library
                    serials = [d['serial'][3:] if d['serial'].upper().startswith('SN:') else d['serial']
                               for d in DwfApi(load_library()).enumerate()]
                    edit.setCompleter(QCompleter(serials, edit))
                except Exception:
                    pass  # the WaveForms runtime is not installed or sees nothing
            elif param == 'serial':
                edit.setPlaceholderText(t("addr_example").format(example="MY12345678"))
                edit.setToolTip(t("addr_serial_tip"))
            elif param == 'port':
                edit.setPlaceholderText(t("addr_example").format(example="5025"))
                edit.setToolTip(t("addr_port_tip"))

            self.fields[param] = edit
            label = self._t(f"addr_field_{param}")
            if label == f"addr_field_{param}":  # a field of a template of the library
                label = param.replace('_', ' ').title()
            self.fields_layout.addRow(label, edit)
        
        # GPIB: scelta dell'adattatore e degli strumenti trovati sul bus
        self.adapter_combo = None
        if self.is_gpib_type(conn_type):
            self.add_gpib_widgets()

        # Aggiungi info speciali per comunicazione seriale
        if conn_type in ['SERIAL', 'USB-SERIAL']:
            info_label = QLabel("⚠️ " + self._t("addr_serial_warning"))
            info_label.setWordWrap(True)
            set_class(info_label, "warning")
            info_label.setStyleSheet("font-size: 10px; margin: 5px;")
            self.fields_layout.addRow(info_label)
        
        # Se già presente un indirizzo, prova a precompilare i campi
        if self.address and template and '{' in template:
            self.populate_fields_from_address()
    
    def add_gpib_widgets(self):
        """Adapter selector and 'Pick from the GPIB bus...' button (Tools > GPIB adapters)."""
        t = self.gpib_tr.t
        self.adapter_combo = QComboBox()
        for cfg in self.gpib_adapters:
            self.adapter_combo.addItem(f"{cfg.name}  ({cfg.address(1).replace('::1::', '::n::')})")
        self.fields_layout.insertRow(0, t("gpb_pick_adapter"), self.adapter_combo)
        row = QHBoxLayout()
        self.pick_button = QPushButton(t("gpb_pick"))
        self.pick_button.clicked.connect(self.pick_from_bus)
        row.addWidget(self.pick_button)
        row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        self.fields_layout.addRow(holder)

    @property
    def gpib_adapter(self):
        """The adapter chosen for a GPIB address (None if the type is not GPIB)."""
        if self.adapter_combo is None:
            return None
        return self.gpib_adapters[max(0, self.adapter_combo.currentIndex())]

    def pick_from_bus(self):
        """Choose the instrument among those found on the bus of the selected adapter."""
        from frontend.ui.GpibDevicePickerDialog import GpibDevicePickerDialog

        dlg = GpibDevicePickerDialog(self.gpib_adapter, self.gpib_tr, self)
        if dlg.exec() and dlg.chosen is not None and 'gpib_addr' in self.fields:
            self.fields['gpib_addr'].setText(str(dlg.chosen.address))

    def select_gpib_adapter(self, address):
        """Select the adapter an existing address belongs to (GPIB<board> or PROLOGIX::<port>)."""
        import re
        from ola.prologix import is_prologix_address, parse_address
        if self.adapter_combo is None:
            return
        if is_prologix_address(address):
            try:
                port, pad, _ = parse_address(address)
            except Exception:
                return

            def match(c):
                return c.family == FAMILY_PROLOGIX and c.port.strip().lower() == port.lower()
        else:
            m = re.match(r'GPIB(\d*)::(\d+)', address.strip(), re.I)
            if not m:
                return
            board, pad = int(m.group(1) or 0), int(m.group(2))

            def match(c):
                return c.family == FAMILY_VISA and c.board == board
        index = next((i for i, c in enumerate(self.gpib_adapters) if match(c)), None)
        if index is not None:
            self.adapter_combo.setCurrentIndex(index)
        if 'gpib_addr' in self.fields:
            self.fields['gpib_addr'].setText(str(pad))

    def populate_fields_from_address(self):
        """Cerca di estrarre i valori dall'indirizzo esistente"""
        try:
            # Per indirizzi DWF (Digilent, WaveForms)
            if self.address.upper().startswith('DWF'):
                value = self.address.split('::', 1)[1] if '::' in self.address else ''
                if 'serial' in self.fields:
                    self.fields['serial'].setText(value[3:] if value.upper().startswith('SN:') else value)

            # Per indirizzi ASRL (seriali)
            elif 'ASRL' in self.address:
                import re
                from ola.serial_config import serial_port_of_address
                port = serial_port_of_address(self.address)
                if port and 'com_port' in self.fields:
                    self.fields['com_port'].setText(port)
            
            # Per indirizzi TCPIP
            elif 'TCPIP' in self.address:
                import re
                match = re.search(r'TCPIP0::([^:]+)::', self.address)
                if match and 'ip' in self.fields:
                    self.fields['ip'].setText(match.group(1))
                socket = re.search(r'TCPIP0::[^:]+::(\d+)::SOCKET', self.address, re.I)
                if socket and 'port' in self.fields:
                    self.fields['port'].setText(socket.group(1))
            
            # Per indirizzi GPIB (qualsiasi scheda GPIBn o adattatore Prologix)
            elif self.is_gpib_address(self.address):
                self.select_gpib_adapter(self.address)
            
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
            logger.error(f"Error parsing existing address: {e}")

    def get_address(self):
        # Compila la stringa secondo il template
        if not self.conn_type:
            return self.address
            
        template = self.templates.get(self.conn_type, '')
        if not template:
            return self.address
            
        vals = {k: self.fields[k].text() for k in self.fields}
        if self.address and not self.address_type and not any(v.strip() for v in vals.values()):
            return self.address  # an address the library does not list for the model: unchanged
        
        try:
            # Validazione speciale per campi seriali
            if self.conn_type in ['SERIAL', 'USB-SERIAL'] and 'com_port' in vals:
                from ola.serial_config import serial_port_value
                try:
                    vals['com_port'] = serial_port_value(vals['com_port'])
                except ValueError:
                    QMessageBox.warning(
                        self, self._t("addr_invalid_title"), self._t("addr_invalid_port"))
                    return None
            
            # Validazione per GPIB
            elif self.is_gpib_type(self.conn_type) and 'gpib_addr' in vals:
                gpib_addr = vals['gpib_addr'].strip()
                if not gpib_addr.isdigit() or not (1 <= int(gpib_addr) <= 30):
                    QMessageBox.warning(
                        self, self._t("addr_invalid_title"), self._t("addr_invalid_gpib"))
                    return None
                if self.gpib_adapter is not None:
                    try:
                        addr = self.gpib_adapter.address(int(gpib_addr))
                    except GpibError as exc:
                        QMessageBox.warning(self, self._t("addr_invalid_title"), str(exc))
                        return None
                    logger.debug(f"Generated address: {addr}")
                    return addr
            
            if self.conn_type == 'WAVEFORMS':
                serial = vals.get('serial', '').strip()
                serial = serial[3:] if serial.upper().startswith('SN:') else serial
                addr = f'DWF::{serial}' if serial else 'DWF'  # empty: the first device found
            else:
                addr = template.format(**vals)
            logger.debug(f"Generated address: {addr}")
            return addr
            
        except Exception as e:
            logger.error(f"Address format error: {e}")
            QMessageBox.warning(self, self._t("error"), f"{self._t('addr_format_error')} {e}")
            return None

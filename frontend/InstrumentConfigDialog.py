import json
from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QListWidget, QFormLayout, QLineEdit, QPushButton, QLabel, QTableWidget, QTableWidgetItem, QCheckBox, QComboBox, QMessageBox, QWidget, QVBoxLayout, QSpinBox
)
from AddressEditorDialog import AddressEditorDialog
from Translator import Translator   
from PowerSupplyConfigDialog import PowerSupplyConfigDialog
from ElectronicLoadConfigDialog import ElectronicLoadConfigDialog
from DataloggerConfigDialog import DataloggerConfigDialog
from LoadInstruments import LoadInstruments


class InstrumentConfigDialog(QDialog):
    def __init__(self, inst_file_path, load_instruments: LoadInstruments, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurazione strumenti")
        self.inst_file_path = inst_file_path
        self.load_instruments = load_instruments
        self.translator = Translator()
        self.resize(900, 500)
        self.instruments = []
        self.current_instrument = None
        self.suppress_save = False
        self.load_instruments_file()
        self.init_ui()

    def load_instruments_file(self):
        try:
            with open(self.inst_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.instruments = data.get('instruments', [])
        except Exception:
            self.instruments = []

    def save_instruments(self):
        if self.suppress_save:
            return
        try:
            with open(self.inst_file_path, 'w', encoding='utf-8') as f:
                json.dump({'instruments': self.instruments}, f, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "Errore salvataggio", str(e))

    def init_ui(self):
        layout = QHBoxLayout(self)
        
        # Left panel with list and buttons
        left_panel = QVBoxLayout()
        
        # Button panel
        button_panel = QHBoxLayout()
        add_btn = QPushButton("Aggiungi strumento")
        add_btn.clicked.connect(self.add_instrument_dialog)
        save_btn = QPushButton("Salva configurazione")
        save_btn.clicked.connect(self.save_instruments)
        button_panel.addWidget(add_btn)
        button_panel.addWidget(save_btn)
        left_panel.addLayout(button_panel)
        
        # Instrument list
        self.list_widget = QListWidget()
        for inst in self.instruments:
            name = inst.get('name', 'Strumento')
            self.list_widget.addItem(name)
        self.list_widget.currentRowChanged.connect(self.on_instrument_selected)
        left_panel.addWidget(self.list_widget, 1)
        
        layout.addLayout(left_panel, 2)
        
        # Editor panel
        self.editor_widget = QWidget()
        self.editor_layout = QVBoxLayout(self.editor_widget)
        layout.addWidget(self.editor_widget, 5)
        
        if self.instruments:
            self.list_widget.setCurrentRow(0)
        else:
            self.show_empty_editor()

    def show_empty_editor(self):
        self.clear_editor()
        label = QLabel("Nessuno strumento presente nel file.")
        self.editor_layout.addWidget(label)

    def clear_editor(self):
        while self.editor_layout.count():
            child = self.editor_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def on_instrument_selected(self, row):
        if row < 0 or row >= len(self.instruments):
            self.current_instrument = None
            self.show_empty_editor()
            return
        self.current_instrument = self.instruments[row]
        self.show_instrument_editor(self.current_instrument)

    def show_instrument_editor(self, inst):
        self.clear_editor()
        form = QFormLayout()
        # Nome assegnato
        name_edit = QLineEdit(inst.get('name', ''))
        name_edit.textChanged.connect(lambda val: self.on_name_changed(val))
        form.addRow("Nome strumento", name_edit)
        # Address editor
        addr_btn = QPushButton("Address Editor")
        addr_btn.clicked.connect(self.open_address_editor)
        form.addRow("Indirizzo", addr_btn)
        # Mostra indirizzo attuale
        addr_label = QLabel(inst.get('address', ''))
        form.addRow("VISA Address", addr_label)
        self.addr_label = addr_label
        # Tipo strumento
        type_label = QLabel(inst.get('type', ''))
        form.addRow("Tipo", type_label)
        self.editor_layout.addLayout(form)
        # Editor specifico per tipo
        t = inst.get('type', '').lower()
        if t in ['power_supply', 'alimentatore']:
            self.show_channel_table(inst, is_power=True)
        elif t in ['electronic_load', 'carico_elettronico']:
            self.show_channel_table(inst, is_power=True)
        elif t in ['datalogger']:
            self.show_channel_table(inst, is_power=False)
        elif t in ['multimeter', 'multimetro']:
            self.show_channel_table(inst, is_power=False, is_multimeter=True)
        elif t in ['oscilloscope', 'oscilloscopio']:
            # Solo address
            pass
        # Spazio per pulsanti aggiuntivi se servono
        self.editor_layout.addStretch()

    def on_name_changed(self, val):
        if self.current_instrument is not None:
            self.current_instrument['name'] = val
            self.save_instruments()
            self.list_widget.currentItem().setText(val)

    def open_address_editor(self):
        if self.current_instrument is None:
            return
        dlg = AddressEditorDialog(self.current_instrument, self.load_instruments, self)
        if dlg.exec_() == QDialog.Accepted:
            # Aggiorna indirizzo
            self.current_instrument['address'] = dlg.get_address()
            self.addr_label.setText(self.current_instrument['address'])
            self.save_instruments()

    def show_channel_table(self, inst, is_power=False, is_multimeter=False):
        # Ricava info capabilities dal modello selezionato
        model_id = inst.get('model_id')
        type_name = inst.get('type', '').lower()
        series_id = inst.get('series', '')
        model_caps = self.load_instruments.get_model_capabilities(type_name, series_id, model_id)
        n = model_caps.get('number_of_channels', inst.get('num_channels', 0)) if model_caps else inst.get('num_channels', 0)
        channel_ids = model_caps.get('channel_ids', []) if model_caps else []
        max_voltage = model_caps.get('max_voltage') if model_caps else None
        max_current = model_caps.get('max_current') if model_caps else None
        measurement_types = model_caps.get('measurement_types', []) if model_caps else []
        channels = inst.get('channels', [])
        # Ricostruisci la lista canali mantenendo i dati esistenti dove possibile
        new_channels = []
        for i in range(n):
            ch = channels[i] if i < len(channels) else {}
            ch['enabled'] = ch.get('enabled', False)
            ch['name'] = ch.get('name', channel_ids[i] if i < len(channel_ids) else f'CH{i+1}')
            if is_power:
                ch['max_current'] = ch.get('max_current', max_current if max_current is not None else 0.0)
                ch['max_voltage'] = ch.get('max_voltage', max_voltage if max_voltage is not None else 0.0)
            elif measurement_types:
                ch['meas_type'] = ch.get('meas_type', measurement_types[0] if measurement_types else '')
                ch['attenuation'] = ch.get('attenuation', 1.0)
                ch['unit'] = ch.get('unit', 'V')
                ch['integration_time'] = ch.get('integration_time', 0.0)
            new_channels.append(ch)
        inst['channels'] = new_channels
        channels = new_channels
        # Costruisci tabella
        if is_power:
            from PowerSupplyConfigDialog import PowerSupplyConfigDialog
            callbacks = {
                'enabled': self.on_channel_enabled_changed,
                'max_current': self.on_channel_current_changed,
                'max_voltage': self.on_channel_voltage_changed,
                'name': self.on_channel_name_changed
            }
            table = PowerSupplyConfigDialog.create_channel_table(channels, channel_ids, max_current, max_voltage, self, callbacks)
        elif measurement_types:
            from DataloggerConfigDialog import DataloggerConfigDialog
            callbacks = {
                'enabled': self.on_channel_enabled_changed,
                'meas_type': self.on_channel_meas_type_changed,
                'attenuation': self.on_channel_attenuation_changed,
                'unit': self.on_channel_unit_changed,
                'integration_time': self.on_channel_integration_time_changed
            }
            table = DataloggerConfigDialog.create_channel_table(channels, channel_ids, measurement_types, self, callbacks)
        else:
            table = QTableWidget(len(channels), 6 if not is_power else 3)
            headers = ["Abilita", "Nome variabile", "Tipo misura", "Attenuazione", "Unità", "Tempo integrazione"]
            table.setHorizontalHeaderLabels(headers)
            for row, ch in enumerate(channels):
                name_edit = QLineEdit(ch.get('name', f'CH{row+1}'))
                name_edit.textChanged.connect(lambda val, r=row: self.on_channel_name_changed(r, val))
                table.setCellWidget(row, 1, name_edit)
                type_edit = QLineEdit(ch.get('meas_type', ''))
                type_edit.textChanged.connect(lambda val, r=row: self.on_channel_meas_type_changed(r, val))
                table.setCellWidget(row, 2, type_edit)
                att_edit = QLineEdit(str(ch.get('attenuation', 1.0)))
                att_edit.textChanged.connect(lambda val, r=row: self.on_channel_attenuation_changed(r, val))
                table.setCellWidget(row, 3, att_edit)
                unit_edit = QLineEdit(ch.get('unit', ''))
                unit_edit.textChanged.connect(lambda val, r=row: self.on_channel_unit_changed(r, val))
                table.setCellWidget(row, 4, unit_edit)
                tint_edit = QLineEdit(str(ch.get('integration_time', 0.0)))
                tint_edit.textChanged.connect(lambda val, r=row: self.on_channel_integration_time_changed(r, val))
                table.setCellWidget(row, 5, tint_edit)
            table.resizeColumnsToContents()
        self.editor_layout.addWidget(table)
        self.channel_table = table

    # Metodi di callback per salvataggio immediato
    def on_channel_enabled_changed(self, row, state):
        if self.current_instrument is not None:
            self.current_instrument['channels'][row]['enabled'] = bool(state)
            self.save_instruments()
    def on_channel_name_changed(self, row, val):
        if self.current_instrument is not None:
            self.current_instrument['channels'][row]['name'] = val
            self.save_instruments()
    def on_channel_current_changed(self, row, val):
        if self.current_instrument is not None:
            try:
                self.current_instrument['channels'][row]['max_current'] = float(val)
            except Exception:
                self.current_instrument['channels'][row]['max_current'] = 0.0
            self.save_instruments()

    def on_channel_voltage_changed(self, row, val):
        if self.current_instrument is not None:
            try:
                self.current_instrument['channels'][row]['max_voltage'] = float(val)
            except Exception:
                self.current_instrument['channels'][row]['max_voltage'] = 0.0
            self.save_instruments()

    def on_channel_meas_type_changed(self, row, val):
        if self.current_instrument is not None:
            self.current_instrument['channels'][row]['meas_type'] = val
            self.save_instruments()
    def on_channel_attenuation_changed(self, row, val):
        if self.current_instrument is not None:
            try:
                self.current_instrument['channels'][row]['attenuation'] = float(val)
            except Exception:
                self.current_instrument['channels'][row]['attenuation'] = 1.0
            self.save_instruments()
    def on_channel_unit_changed(self, row, val):
        if self.current_instrument is not None:
            self.current_instrument['channels'][row]['unit'] = val
            self.save_instruments()
    def on_channel_integration_time_changed(self, row, val):
        if self.current_instrument is not None:
            try:
                self.current_instrument['channels'][row]['integration_time'] = float(val)
            except Exception:
                self.current_instrument['channels'][row]['integration_time'] = 0.0
            self.save_instruments()

    def add_instrument_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Aggiungi strumento")
        form = QFormLayout(dlg)
        # Tipo: solo quelli presenti in libreria
        type_combo = QComboBox()
        type_map = {}
        for t in self.load_instruments.get_all_types():
            type_map[t] = t
            type_combo.addItem(t)
        form.addRow("Tipo", type_combo)
        # Serie: aggiornata in base al tipo
        series_combo = QComboBox()
        model_combo = QComboBox()
        def update_series():
            series_combo.clear()
            model_combo.clear()
            t = type_combo.currentText()
            series_list = self.load_instruments.get_series(t)
            for s in series_list or []:
                label = s.get('series_name', s.get('series_id', str(s)))
                series_combo.addItem(label, s.get('series_id', label))
            update_models()  # Aggiorna anche i modelli
        def update_models():
            model_combo.clear()
            t = type_combo.currentText()
            series_id = series_combo.currentData()
            models = self.load_instruments.get_models(t, series_id)
            model_combo.model_map = {}
            for m in models or []:
                model_name = m.get('name', str(m))
                model_id = m.get('id', model_name)
                num_channels = m.get('channels', m.get('num_channels', 1))
                model_combo.addItem(model_name)
                model_combo.model_map[model_name] = (model_id, num_channels)
        type_combo.currentTextChanged.connect(update_series)
        series_combo.currentIndexChanged.connect(update_models)
        update_series()
        form.addRow("Serie", series_combo)
        form.addRow("Modello", model_combo)
        # Nome
        name_edit = QLineEdit()
        form.addRow("Nome", name_edit)
        # Pulsanti
        btns = QHBoxLayout()
        ok_btn = QPushButton("Aggiungi")
        cancel_btn = QPushButton("Annulla")
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        form.addRow(btns)
        ok_btn.clicked.connect(dlg.accept)
        cancel_btn.clicked.connect(dlg.reject)
        if dlg.exec_() == QDialog.Accepted:
            t = type_combo.currentText()
            name = name_edit.text().strip() or t
            series = series_combo.currentData()
            model = model_combo.currentText().strip()
            model_id, num_channels = model_combo.model_map.get(model, (model, 1))
            new_inst = {
                'type': t,
                'name': name,
                'series': series,
                'model': model,
                'model_id': model_id,
                'num_channels': num_channels,
                'channels': []
            }
            self.instruments.append(new_inst)
            self.save_instruments()
            self.list_widget.addItem(name)
            self.list_widget.setCurrentRow(self.list_widget.count()-1)

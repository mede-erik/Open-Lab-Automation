import json
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QListWidget, QFormLayout, QLineEdit, QPushButton, QLabel, QTableWidget, QTableWidgetItem, QCheckBox, QComboBox, QMessageBox, QWidget, QVBoxLayout, QSpinBox, QMenu, QDialogButtonBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QLocale
from PyQt6.QtGui import QAction, QDoubleValidator
from frontend.ui.AddressEditorDialog import AddressEditorDialog
from frontend.core.Translator import Translator   
from frontend.ui.PowerSupplyConfigDialog import PowerSupplyConfigDialog
from frontend.ui.ElectronicLoadConfigDialog import ElectronicLoadConfigDialog
from frontend.ui.OscilloscopeConfigDialog import OscilloscopeConfigDialog
from frontend.ui.DataloggerConfigDialog import DataloggerConfigDialog
from frontend.core.LoadInstruments import LoadInstruments

# PyVISA opzionale per discovery
try:
    import pyvisa
    PYVISA_AVAILABLE = True
except Exception:
    pyvisa = None
    PYVISA_AVAILABLE = False


class InstrumentConfigDialog(QDialog):
    # Emesso ogni volta che la configurazione strumenti viene salvata
    instruments_changed = pyqtSignal(str)  # arg: percorso del file .inst
    
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
        self.instruments_modified = False  # Flag per tracciare le modifiche
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
            print("[DEBUG] Salvataggio strumenti: stato attuale self.instruments:", self.instruments)
            # Serializza attenuation come float con 10 cifre decimali (no notazione scientifica)
            def fix_attenuation(obj):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if k == 'channels' and isinstance(v, list):
                            for ch in v:
                                if 'attenuation' in ch:
                                    print(f"[DEBUG] Prima della serializzazione: ch['attenuation'] = {ch['attenuation']} (type: {type(ch['attenuation'])})")
                                    if isinstance(ch['attenuation'], float):
                                        ch['attenuation'] = float(f"{ch['attenuation']:.10f}")
                                    print(f"[DEBUG] Dopo la serializzazione: ch['attenuation'] = {ch['attenuation']} (type: {type(ch['attenuation'])})")
                        else:
                            fix_attenuation(v)
                elif isinstance(obj, list):
                    for item in obj:
                        fix_attenuation(item)
            data = {'instruments': self.instruments}
            fix_attenuation(data)
            print("[DEBUG] Dati serializzati pronti per il salvataggio:", data)
            with open(self.inst_file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self.instruments_modified = True  # Segnala che ci sono state modifiche
            # Notifica i listener che il file .inst è stato modificato/salvato
            try:
                self.instruments_changed.emit(self.inst_file_path)
            except Exception:
                # Ignora se il segnale non è connesso o in caso di errori di runtime
                pass
        except Exception as e:
            print(f"[DEBUG] Errore durante il salvataggio strumenti: {e}")
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
        # Pulsante: Cerca strumenti nella rete
        discover_btn = QPushButton("Cerca strumenti nella rete")
        discover_btn.clicked.connect(self.open_network_scan_dialog)
        button_panel.addWidget(add_btn)
        button_panel.addWidget(save_btn)
        button_panel.addWidget(discover_btn)
        left_panel.addLayout(button_panel)

        # Instrument list
        self.list_widget = QListWidget()
        for inst in self.instruments:
            name = inst.get('instance_name', inst.get('name', 'Strumento'))
            self.list_widget.addItem(name)
        self.list_widget.currentRowChanged.connect(self.on_instrument_selected)

        # Enable context menu for right-click
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self.show_context_menu)

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

    def show_context_menu(self, position):
        """Mostra il menu contestuale per la lista strumenti"""
        item = self.list_widget.itemAt(position)
        if item is None:
            return
            
        menu = QMenu(self)
        # Azione duplica strumento
        duplicate_action = QAction("Duplica strumento", self)
        duplicate_action.triggered.connect(self.duplicate_instrument)
        menu.addAction(duplicate_action)

        # Azione cancella strumento
        delete_action = QAction("Cancella strumento", self)
        delete_action.triggered.connect(self.delete_instrument)
        menu.addAction(delete_action)

        # Mostra il menu solo se c'è almeno un elemento selezionato
        if self.list_widget.currentItem() is not None:
            menu.exec(self.list_widget.mapToGlobal(position))

    def duplicate_instrument(self):
        """Duplica lo strumento selezionato"""
        current_row = self.list_widget.currentRow()
        if current_row < 0 or current_row >= len(self.instruments):
            return
            
        # Copia profonda dello strumento corrente per includere canali
        import copy
        original_instrument = copy.deepcopy(self.instruments[current_row])
        
        # Modifica il nome per evitare duplicati
        original_name = original_instrument.get('name', 'Strumento')
        new_name = f"{original_name} - Copia"
        
        # Assicurati che il nome sia unico
        counter = 1
        while any(inst.get('name') == new_name for inst in self.instruments):
            new_name = f"{original_name} - Copia ({counter})"
            counter += 1
            
        original_instrument['name'] = new_name
        
        # Se ha un instance_name, aggiorna anche quello
        if 'instance_name' in original_instrument:
            original_instance = original_instrument.get('instance_name', '')
            new_instance = f"{original_instance}_copy"
            
            # Assicura unicità dell'instance_name
            counter = 1
            while any(inst.get('instance_name') == new_instance for inst in self.instruments):
                new_instance = f"{original_instance}_copy{counter}"
                counter += 1
                
            original_instrument['instance_name'] = new_instance
        
        # Aggiorna i nomi dei canali se presenti
        if 'channels' in original_instrument and isinstance(original_instrument['channels'], list):
            for i, channel in enumerate(original_instrument['channels']):
                if isinstance(channel, dict) and 'name' in channel:
                    channel['name'] = f"{channel['name']}_copy"
        
        # Aggiungi il nuovo strumento
        self.instruments.append(original_instrument)
        
        # Aggiorna la lista UI
        self.list_widget.addItem(new_name)
        
        # Seleziona il nuovo strumento
        self.list_widget.setCurrentRow(len(self.instruments) - 1)
        
        # Salva automaticamente
        self.save_instruments()

    def delete_instrument(self):
        """Cancella lo strumento selezionato"""
        current_row = self.list_widget.currentRow()
        if current_row < 0 or current_row >= len(self.instruments):
            return
            
        instrument_name = self.instruments[current_row].get('instance_name', self.instruments[current_row].get('name', 'Strumento'))
        
        # Chiedi conferma
        reply = QMessageBox.question(
            self, 
            'Conferma cancellazione',
            f'Sei sicuro di voler cancellare lo strumento "{instrument_name}"?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Rimuovi dalla lista dati
            del self.instruments[current_row]
            
            # Rimuovi dalla lista UI
            self.list_widget.takeItem(current_row)
            
            # Aggiorna la selezione
            if self.instruments:
                if current_row >= len(self.instruments):
                    self.list_widget.setCurrentRow(len(self.instruments) - 1)
                else:
                    self.list_widget.setCurrentRow(current_row)
            else:
                self.show_empty_editor()
            
            # Salva automaticamente
            self.save_instruments()

    def show_empty_editor(self):
        self.clear_editor()
        label = QLabel("Nessuno strumento presente nel file.")
        self.editor_layout.addWidget(label)

    def clear_editor(self):
        while self.editor_layout.count():
            child = self.editor_layout.takeAt(0)
            if child is not None:
                widget = child.widget()
                if widget is not None:
                    widget.deleteLater()

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
        name_edit = QLineEdit(inst.get('instance_name', inst.get('name', '')))
        name_edit.textChanged.connect(lambda val: self.on_name_changed(val))
        form.addRow("Nome strumento", name_edit)
        # Address editor
        addr_btn = QPushButton("Address Editor")
        addr_btn.clicked.connect(self.open_address_editor)
        form.addRow("Indirizzo", addr_btn)
        # Mostra indirizzo attuale
        addr_label = QLabel(inst.get('visa_address', inst.get('address', '')))
        form.addRow("VISA Address", addr_label)
        self.addr_label = addr_label
        # Tipo strumento
        type_label = QLabel(inst.get('instrument_type', inst.get('type', '')))
        form.addRow("Tipo", type_label)
        self.editor_layout.addLayout(form)
        # Editor specifico per tipo
        t = inst.get('instrument_type', inst.get('type', '')).lower()
        if t in ['power_supply', 'power_supplies', 'alimentatore', 'alimentatori']:
            self.show_channel_table(inst, is_power=True)
        elif t in ['electronic_load', 'electronic_loads', 'carico_elettronico', 'carichi_elettronici']:
            self.show_channel_table(inst, is_power=True)
        elif t in ['datalogger', 'dataloggers']:
            self.show_channel_table(inst, is_power=False)
        elif t in ['multimeter', 'multimeters', 'multimetro', 'multimetri']:
            self.show_channel_table(inst, is_power=False, is_multimeter=True)
        elif t in ['oscilloscope', 'oscilloscopes', 'oscilloscopio', 'oscilloscopi']:
            # Mostra pulsante per aprire il dialog di configurazione canali oscilloscopio
            self.show_oscilloscope_config_button(inst)

    def show_oscilloscope_config_button(self, inst):
        """Mostra un pulsante per configurare i canali dell'oscilloscopio"""
        # Info label
        info_label = QLabel("🔧 Configura i canali dell'oscilloscopio per abilitare/disabilitare canali, assegnare nomi ai segnali e impostare le scale Volt/div.")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("QLabel { color: #555; padding: 10px; background-color: #f0f0f0; border-radius: 5px; }")
        self.editor_layout.addWidget(info_label)
        
        # Pulsante per aprire OscilloscopeConfigDialog
        config_btn = QPushButton("⚙️ Configura Canali Oscilloscopio")
        config_btn.setStyleSheet("QPushButton { padding: 10px; font-weight: bold; }")
        config_btn.clicked.connect(lambda: self.open_oscilloscope_config_dialog(inst))
        self.editor_layout.addWidget(config_btn)
        
        # Mostra riepilogo canali configurati
        channels = inst.get('channels', [])
        if channels:
            summary_label = QLabel(f"📊 Canali configurati: {len(channels)} totali")
            enabled_count = sum(1 for ch in channels if ch.get('enabled', False))
            summary_label.setText(f"📊 Canali configurati: {len(channels)} totali, {enabled_count} abilitati")
            summary_label.setStyleSheet("QLabel { padding: 5px; color: #007acc; }")
            self.editor_layout.addWidget(summary_label)
            
            # Lista canali abilitati
            if enabled_count > 0:
                enabled_list = QLabel("Canali abilitati: " + ", ".join([
                    f"{ch.get('channel_id', '?')} ({ch.get('name', 'N/A')})" 
                    for ch in channels if ch.get('enabled', False)
                ]))
                enabled_list.setWordWrap(True)
                enabled_list.setStyleSheet("QLabel { padding: 5px; font-size: 11px; color: #666; }")
                self.editor_layout.addWidget(enabled_list)

    def open_oscilloscope_config_dialog(self, inst):
        """Apre il dialog di configurazione canali oscilloscopio"""
        dlg = OscilloscopeConfigDialog(inst, self.translator, self)
        if dlg.exec():
            # Aggiorna l'interfaccia dopo la configurazione
            self.save_instruments()
            # Ricarica l'editor per mostrare il riepilogo aggiornato
            self.show_instrument_editor(inst)

    def show_channel_table(self, inst, is_power=False, is_multimeter=False):
        """Mostra la tabella dei canali per lo strumento corrente"""
        # Ricava info capabilities dal modello selezionato
        model_id = inst.get('model_id')
        type_name = inst.get('instrument_type', inst.get('type', '')).lower()
        series_id = inst.get('series', '')
        
        try:
            model_caps = self.load_instruments.get_model_capabilities(type_name, series_id, model_id)
        except Exception:
            model_caps = None
            
        n = 0
        if model_caps:
            n = model_caps.get('number_of_channels', inst.get('num_channels', 0))
        else:
            n = inst.get('num_channels', 0)
            
        if n <= 0:
            # Mostra messaggio informativo invece di non mostrare nulla
            info_label = QLabel("ℹ️ Nessun canale configurato per questo strumento.\nVerifica le capabilities del modello nella libreria strumenti.")
            info_label.setStyleSheet("QLabel { color: #888; padding: 10px; }")
            self.editor_layout.addWidget(info_label)
            return
            
        # Ottieni o crea lista canali
        channels = inst.get('channels', [])
        
        # Sincronizza canali con il numero previsto
        channel_ids = []
        if model_caps:
            channel_ids = model_caps.get('channel_ids', [])
            
        while len(channels) < n:
            idx = len(channels)
            ch_id = channel_ids[idx] if idx < len(channel_ids) else f'CH{idx+1}'
            new_ch = {
                'enabled': False,
                'name': ch_id,
            }
            if is_power:
                new_ch['max_current'] = model_caps.get('max_current', 0.0) if model_caps else 0.0
                new_ch['max_voltage'] = model_caps.get('max_voltage', 0.0) if model_caps else 0.0
            elif is_multimeter:
                new_ch['meas_type'] = 'DC_V'
                new_ch['attenuation'] = 1.0
                new_ch['unit'] = 'V'
                new_ch['integration_time'] = 0.0
            else:
                # datalogger o altro
                new_ch['meas_type'] = 'DC_V'
                new_ch['unit'] = 'V'
            channels.append(new_ch)
            
        inst['channels'] = channels[:n]
        
        # Crea tabella
        if is_power:
            # Power supply / Electronic load
            table = QTableWidget(n, 4)
            table.setHorizontalHeaderLabels(["Abilita", "Nome", "Corrente max (A)", "Tensione max (V)"])
            
            for row, ch in enumerate(inst['channels']):
                # Abilita
                chk = QCheckBox()
                chk.setChecked(ch.get('enabled', False))
                chk.stateChanged.connect(lambda state, r=row: self.on_channel_enabled_changed(r, state))
                table.setCellWidget(row, 0, chk)
                
                # Nome
                name_edit = QLineEdit(ch.get('name', f'CH{row+1}'))
                name_edit.textChanged.connect(lambda val, r=row: self.on_channel_name_changed(r, val))
                table.setCellWidget(row, 1, name_edit)
                
                # Corrente max
                curr_edit = QLineEdit(str(ch.get('max_current', 0.0)))
                curr_edit.textChanged.connect(lambda val, r=row: self.on_channel_current_changed(r, val))
                table.setCellWidget(row, 2, curr_edit)
                
                # Tensione max
                volt_edit = QLineEdit(str(ch.get('max_voltage', 0.0)))
                volt_edit.textChanged.connect(lambda val, r=row: self.on_channel_voltage_changed(r, val))
                table.setCellWidget(row, 3, volt_edit)
                
        elif is_multimeter:
            # Multimetro
            table = QTableWidget(n, 6)
            table.setHorizontalHeaderLabels(["Abilita", "Nome", "Tipo misura", "Attenuazione", "Unità", "Tempo integrazione"])
            
            for row, ch in enumerate(inst['channels']):
                # Abilita
                chk = QCheckBox()
                chk.setChecked(ch.get('enabled', False))
                chk.stateChanged.connect(lambda state, r=row: self.on_channel_enabled_changed(r, state))
                table.setCellWidget(row, 0, chk)
                
                # Nome
                name_edit = QLineEdit(ch.get('name', f'CH{row+1}'))
                name_edit.textChanged.connect(lambda val, r=row: self.on_channel_name_changed(r, val))
                table.setCellWidget(row, 1, name_edit)
                
                # Tipo misura
                meas_combo = QComboBox()
                meas_combo.addItems(['DC_V', 'DC_A', 'AC_V', 'AC_A', 'RES', 'FREQ'])
                meas_combo.setCurrentText(ch.get('meas_type', 'DC_V'))
                meas_combo.currentTextChanged.connect(lambda val, r=row: self.on_channel_meas_type_changed(r, val))
                table.setCellWidget(row, 2, meas_combo)
                
                # Attenuazione
                # Forza la visualizzazione attenuazione in formato decimale con punto
                att_val = ch.get('attenuation', 1.0)
                if isinstance(att_val, float):
                    att_str = f"{att_val:.10f}".rstrip('0').rstrip('.') if '.' in f"{att_val:.10f}" else str(att_val)
                else:
                    att_str = str(att_val).replace(',', '.')
                att_edit = QLineEdit(att_str)
                # Validator con locale C per forzare il punto decimale
                validator = QDoubleValidator(0.0000000001, 1e6, 10, att_edit)
                validator.setLocale(QLocale(QLocale.Language.C))
                validator.setNotation(QDoubleValidator.Notation.StandardNotation)
                att_edit.setValidator(validator)
                att_edit.setPlaceholderText("Es: 0.5 (shunt 0.5Ω), 10.0 (amplif. x10)")
                att_edit.setToolTip("Fattore di attenuazione/amplificazione (max 10 cifre decimali).\n" +
                                  "• Shunt: Resistenza in Ω (es: 0.1 per shunt 0.1Ω)\n" +
                                  "• Amplificatore: Guadagno (es: 10.0 per amplif. x10)\n" +
                                  "• Default: 1.0 (nessuna attenuazione)")
                att_edit.textChanged.connect(lambda val, r=row: self.on_channel_attenuation_changed(r, val))
                table.setCellWidget(row, 3, att_edit)
                
                # Unità
                unit_edit = QLineEdit(ch.get('unit', 'V'))
                unit_edit.textChanged.connect(lambda val, r=row: self.on_channel_unit_changed(r, val))
                table.setCellWidget(row, 4, unit_edit)
                
                # Tempo integrazione
                tint_edit = QLineEdit(str(ch.get('integration_time', 0.0)))
                tint_edit.setValidator(QDoubleValidator(0.0, 1e6, 3, tint_edit))
                tint_edit.setPlaceholderText("Tempo in secondi")
                tint_edit.textChanged.connect(lambda val, r=row: self.on_channel_integration_time_changed(r, val))
                table.setCellWidget(row, 5, tint_edit)
        else:
            # Datalogger o generico
            # Aggiunta colonna Attenuazione per permettere l'inserimento di shunt/guadagni
            table = QTableWidget(n, 5)
            table.setHorizontalHeaderLabels(["Abilita", "Nome", "Tipo misura", "Attenuazione", "Unità"])
            
            for row, ch in enumerate(inst['channels']):
                # Abilita
                chk = QCheckBox()
                chk.setChecked(ch.get('enabled', False))
                chk.stateChanged.connect(lambda state, r=row: self.on_channel_enabled_changed(r, state))
                table.setCellWidget(row, 0, chk)
                
                # Nome
                name_edit = QLineEdit(ch.get('name', f'CH{row+1}'))
                name_edit.textChanged.connect(lambda val, r=row: self.on_channel_name_changed(r, val))
                table.setCellWidget(row, 1, name_edit)
                
                # Tipo misura
                meas_combo = QComboBox()
                meas_combo.addItems(['DC_V', 'DC_A', 'AC_V', 'AC_A', 'RES', 'FREQ', 'TEMP'])
                meas_combo.setCurrentText(ch.get('meas_type', 'DC_V'))
                meas_combo.currentTextChanged.connect(lambda val, r=row: self.on_channel_meas_type_changed(r, val))
                table.setCellWidget(row, 2, meas_combo)
                
                # Attenuazione (supporta 10 cifre decimali) - visualizzazione forzata decimale con punto
                att_val = ch.get('attenuation', 1.0)
                if isinstance(att_val, float):
                    att_str = f"{att_val:.10f}".rstrip('0').rstrip('.') if '.' in f"{att_val:.10f}" else str(att_val)
                else:
                    att_str = str(att_val).replace(',', '.')
                att_edit = QLineEdit(att_str)
                # Validator con locale C per forzare il punto decimale
                validator = QDoubleValidator(0.0000000001, 1e6, 10, att_edit)
                validator.setLocale(QLocale(QLocale.Language.C))
                validator.setNotation(QDoubleValidator.Notation.StandardNotation)
                att_edit.setValidator(validator)
                att_edit.setPlaceholderText("Es: 0.5 (shunt 0.5Ω), 10.0 (amplif. x10)")
                att_edit.setToolTip("Fattore di attenuazione/amplificazione (max 10 cifre decimali).\n" +
                                  "• Shunt: Resistenza in Ω (es: 0.1 per shunt 0.1Ω)\n" +
                                  "• Amplificatore: Guadagno (es: 10.0 per amplif. x10)\n" +
                                  "• Default: 1.0 (nessuna attenuazione)")
                att_edit.textChanged.connect(lambda val, r=row: self.on_channel_attenuation_changed(r, val))
                table.setCellWidget(row, 3, att_edit)
                
                # Unità
                unit_edit = QLineEdit(ch.get('unit', 'V'))
                unit_edit.textChanged.connect(lambda val, r=row: self.on_channel_unit_changed(r, val))
                table.setCellWidget(row, 4, unit_edit)
                
        table.resizeColumnsToContents()
        self.editor_layout.addWidget(table)
        self.channel_table = table

    def on_name_changed(self, val):
        if self.current_instrument is not None:
            self.current_instrument['instance_name'] = val
            self.save_instruments()
            item = self.list_widget.currentItem()
            if item is not None:
                item.setText(val)

    def open_address_editor(self):
        if self.current_instrument is None:
            return
        dlg = AddressEditorDialog(self.current_instrument, self.load_instruments, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # Aggiorna indirizzo
            self.current_instrument['visa_address'] = dlg.get_address()
            self.addr_label.setText(self.current_instrument['visa_address'])
            self.save_instruments()
    def open_network_scan_dialog(self):
        """Scansiona le risorse VISA disponibili e permette di applicare un indirizzo allo strumento selezionato."""
        from PyQt6.QtWidgets import QApplication
        if not PYVISA_AVAILABLE or pyvisa is None:
            QMessageBox.information(self, "Scansione non disponibile", "PyVISA non è installato o il backend non è disponibile.")
            return
        
        dlg = QDialog(self)
        dlg.setWindowTitle("Strumenti trovati in rete (VISA)")
        vbox = QVBoxLayout(dlg)
        
        # Barra filtro: Solo USB
        filter_bar = QHBoxLayout()
        usb_only_cb = QCheckBox("Solo USB")
        filter_bar.addWidget(usb_only_cb)
        filter_bar.addStretch(1)
        vbox.addLayout(filter_bar)
        
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["Indirizzo", "IDN", "Interfaccia"])
        vbox.addWidget(table)
        
        btns = QDialogButtonBox()
        btn_copy = QPushButton("Copia indirizzo")
        btn_apply = QPushButton("Imposta su strumento selezionato")
        btn_close = QPushButton("Chiudi")
        btns.addButton(btn_copy, QDialogButtonBox.ButtonRole.ActionRole)
        btns.addButton(btn_apply, QDialogButtonBox.ButtonRole.ActionRole)
        btns.addButton(btn_close, QDialogButtonBox.ButtonRole.RejectRole)
        vbox.addWidget(btns)

        # Esegui discovery
        resources = []
        idn_cache = {}  # addr -> (idn, iface)
        try:
            if pyvisa is not None:
                try:
                    rm = pyvisa.ResourceManager('@py')
                except Exception:
                    rm = pyvisa.ResourceManager()
                try:
                    resources = list(rm.list_resources())
                except Exception:
                    resources = []
                for addr in resources:
                    idn = ""
                    iface = addr.split("::", 1)[0] if "::" in addr else ""
                    try:
                        inst = rm.open_resource(addr)
                        try:
                            inst.timeout = 1000
                        except Exception:
                            pass
                        try:
                            setattr(inst, 'write_termination', '\n')
                            setattr(inst, 'read_termination', '\n')
                        except Exception:
                            pass
                        try:
                            q = getattr(inst, 'query', None)
                            if callable(q):
                                idn = q("*IDN?")
                            else:
                                w = getattr(inst, 'write', None)
                                r = getattr(inst, 'read', None)
                                if callable(w):
                                    try:
                                        w("*IDN?")
                                    except Exception:
                                        pass
                                if callable(r):
                                    try:
                                        idn = r()
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                        inst.close()
                    except Exception:
                        pass
                    idn_cache[addr] = (idn, iface)
        except Exception as e:
            QMessageBox.warning(self, "Errore scansione", str(e))

        def is_usb(addr_iface_tuple):
            _, iface_val = addr_iface_tuple
            return "USB" in iface_val.upper()

        def populate_table(only_usb=False):
            table.setRowCount(0)
            for addr, (idn_text, iface_val) in idn_cache.items():
                if only_usb and not is_usb((addr, iface_val)):
                    continue
                row = table.rowCount()
                table.insertRow(row)
                table.setItem(row, 0, QTableWidgetItem(addr))
                table.setItem(row, 1, QTableWidgetItem(idn_text))
                table.setItem(row, 2, QTableWidgetItem(iface_val))
            table.resizeColumnsToContents()

        populate_table(only_usb=False)
        usb_only_cb.stateChanged.connect(lambda _state: populate_table(usb_only_cb.isChecked()))
        table.cellDoubleClicked.connect(lambda row, _col: btn_apply.click())

        def copy_selected():
            row = table.currentRow()
            if row < 0:
                return
            addr_item = table.item(row, 0)
            if addr_item is None:
                return
            addr = addr_item.text()
            clipboard = QApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(addr)

        def apply_selected():
            row = table.currentRow()
            if row < 0:
                return
            addr_item = table.item(row, 0)
            if addr_item is None:
                return
            addr = addr_item.text()
            if self.current_instrument is not None:
                self.current_instrument['visa_address'] = addr
                if hasattr(self, 'addr_label'):
                    self.addr_label.setText(addr)
                self.save_instruments()

        btn_copy.clicked.connect(copy_selected)
        btn_apply.clicked.connect(apply_selected)
        btn_close.clicked.connect(dlg.reject)
        dlg.exec()

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
                print(f"[DEBUG] Input attenuazione ricevuto: {val} (row: {row})")
                val = str(val).replace(',', '.')
                parsed = float(val)
                print(f"[DEBUG] Valore attenuazione convertito in float: {parsed}")
                self.current_instrument['channels'][row]['attenuation'] = parsed
            except Exception as e:
                print(f"[DEBUG] Errore conversione attenuazione: {e}")
                self.current_instrument['channels'][row]['attenuation'] = 1.0
            print(f"[DEBUG] Stato canale dopo set attenuazione: {self.current_instrument['channels'][row]}")
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
        model_map = {}
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
            model_map.clear()
            for m in models or []:
                model_name = m.get('name', str(m))
                model_id = m.get('id', model_name)
                num_channels = m.get('channels', m.get('num_channels', 1))
                model_combo.addItem(model_name)
                model_map[model_name] = (model_id, num_channels)
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
        if dlg.exec() == QDialog.DialogCode.Accepted:
            t = type_combo.currentText()
            name = name_edit.text().strip() or t
            series = series_combo.currentData()
            model = model_combo.currentText().strip()
            model_id, guessed_num_channels = model_map.get(model, (model, 1))
            # Ricava num_channels dalle capabilities quando possibile
            caps = None
            try:
                caps = self.load_instruments.get_model_capabilities(t, series, model_id)
            except Exception:
                caps = None
            num_channels = (
                (caps.get('number_of_channels') if isinstance(caps, dict) else None)
                or (caps.get('channels') if isinstance(caps, dict) and isinstance(caps.get('channels'), int) else None)
                or (caps.get('number_of_slots') if isinstance(caps, dict) else None)
                or guessed_num_channels
            )
            new_inst = {
                'instrument_type': t,
                'instance_name': name,
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

import json
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QListWidget, QPushButton, QLabel, QLineEdit, QComboBox, QTextEdit, QFormLayout, QSizePolicy
from PyQt5.QtCore import Qt
from AddressEditorDialog import AddressEditorDialog
from Translator import Translator
from PowerSupplyConfigDialog import PowerSupplyConfigDialog
from ElectronicLoadConfigDialog import ElectronicLoadConfigDialog
from DataloggerConfigDialog import DataloggerConfigDialog
from PyQt5.QtWidgets import QListWidgetItem, QHBoxLayout, QWidget
from LoadInstruments import LoadInstruments

# =========================
# InstFileDialog
# =========================
class InstFileDialog(QDialog):
    """
    Dialog per la modifica di un file .inst (strumenti).
    Permette di aggiungere strumenti dalla libreria instruments_lib.json con dettagli istanza.
    Selezione strumento: tipo → serie → modello.
    """
    def __init__(self, file_path, load_instruments: LoadInstruments, translator, parent=None):
        super().__init__(parent)
        self.translator = translator
        self.file_path = file_path
        self.load_instruments = load_instruments
        self.setWindowTitle(self.translator.t('edit_inst_file'))
        self.setModal(True)
        layout = QVBoxLayout()
        # Nuova mappa: type_key -> (label, type_name)
        self.type_map = {
            'power_supply': (self.translator.t('power_supply') if hasattr(self.translator, 't') else 'Alimentatore', 'power_supply'),
            'datalogger': (self.translator.t('datalogger') if hasattr(self.translator, 't') else 'Datalogger', 'datalogger'),
        }
        # Carica dati file .inst
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                self.inst_data = json.load(f)
        except Exception:
            self.inst_data = {"instruments": []}
        # Editor JSON raw (opzionale, solo per debug)
        self.data_edit = QTextEdit()
        self.data_edit.setText(json.dumps(self.inst_data, indent=2))
        # Lista strumenti già aggiunti
        layout.addWidget(QLabel(self.translator.t('added_instruments') if hasattr(self.translator, 't') else 'Strumenti aggiunti'))
        self.instruments_list_widget = QListWidget()
        layout.addWidget(self.instruments_list_widget)
        self.refresh_instruments_list()
        remove_btn = QPushButton(self.translator.t('remove_selected') if hasattr(self.translator, 't') else 'Rimuovi selezionato')
        remove_btn.clicked.connect(self.remove_selected_instrument)
        layout.addWidget(remove_btn)
        # Permetti doppio click per editare canali
        self.instruments_list_widget.itemDoubleClicked.connect(self.edit_instrument_channels)
        # --- Form per aggiunta nuovo strumento ---
        layout.addWidget(QLabel(self.translator.t('add_new_instrument') if hasattr(self.translator, 't') else 'Aggiungi nuovo strumento'))
        form = QFormLayout()
        self.instance_name_edit = QLineEdit()
        form.addRow(self.translator.t('instance_name') if hasattr(self.translator, 't') else 'Nome istanza', self.instance_name_edit)
        # Menu tipo strumento
        self.type_combo = QComboBox()
        for k, (v, _) in self.type_map.items():
            self.type_combo.addItem(v, k)
        self.type_combo.currentIndexChanged.connect(self.update_series_combo)
        form.addRow(self.translator.t('instrument_type') if hasattr(self.translator, 't') else 'Tipo strumento', self.type_combo)
        # Menu serie
        self.series_combo = QComboBox()
        self.series_combo.currentIndexChanged.connect(self.update_model_combo)
        form.addRow(self.translator.t('series') if hasattr(self.translator, 't') else 'Serie', self.series_combo)
        # Menu modello
        self.model_combo = QComboBox()
        self.model_combo.currentIndexChanged.connect(self.update_connection_types)
        form.addRow(self.translator.t('model') if hasattr(self.translator, 't') else 'Modello', self.model_combo)
        # Tipo connessione
        self.connection_type_combo = QComboBox()
        form.addRow(self.translator.t('connection_type') if hasattr(self.translator, 't') else 'Tipo connessione', self.connection_type_combo)
        # Sostituisco QLineEdit con QPushButton e QLabel (readonly)
        self.visa_address_btn = QPushButton(self.translator.t('compose_visa_address'))
        self.visa_address_btn.clicked.connect(self.open_visa_address_dialog)
        self.visa_address_label = QLabel('')
        self.visa_address_label.setStyleSheet('background:#eee; border:1px solid #ccc; padding:2px;')
        form.addRow(self.translator.t('visa_address'), self.visa_address_btn)
        form.addRow(self.translator.t('composed_address'), self.visa_address_label)
        # Canali: layout verticale con pulsanti e lista scrollabile
        channel_box = QVBoxLayout()
        btn_row = QHBoxLayout()
        self.enable_all_btn = QPushButton(self.translator.t('enable_all') if hasattr(self.translator, 't') else 'Attiva tutti')
        self.disable_all_btn = QPushButton(self.translator.t('disable_all') if hasattr(self.translator, 't') else 'Disattiva tutti')
        self.enable_all_btn.clicked.connect(self.enable_all_channels)
        self.disable_all_btn.clicked.connect(self.disable_all_channels)
        btn_row.addWidget(self.enable_all_btn)
        btn_row.addWidget(self.disable_all_btn)
        channel_box.addLayout(btn_row)
        # Lista canali scrollabile
        self.channels_widget = QListWidget()
        self.channels_widget.setMinimumHeight(120)
        self.channels_widget.setMaximumHeight(200)
        self.channels_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        channel_box.addWidget(self.channels_widget)
        form.addRow(self.translator.t('channel_assignments') if hasattr(self.translator, 't') else 'Assegnazione canali', QWidget())
        form.itemAt(form.rowCount()-1, QFormLayout.FieldRole).widget().setLayout(channel_box)
        self.model_combo.currentIndexChanged.connect(self.update_channels_widget)
        layout.addLayout(form)
        add_btn = QPushButton(self.translator.t('add_instrument') if hasattr(self.translator, 't') else 'Aggiungi strumento')
        add_btn.clicked.connect(self.add_instrument_to_inst)
        layout.addWidget(add_btn)
        # --- Fine form ---
        # Editor JSON raw (opzionale, solo per debug)
        self.data_edit = QTextEdit()
        self.data_edit.setText(json.dumps(self.inst_data, indent=2))
        layout.addWidget(QLabel(self.translator.t('raw_json') if hasattr(self.translator, 't') else 'JSON grezzo'))
        layout.addWidget(self.data_edit)
        save_btn = QPushButton(self.translator.t('save'))
        save_btn.clicked.connect(self.save_changes)
        layout.addWidget(save_btn)
        self.setLayout(layout)
        self.update_series_combo()

    def enable_all_channels(self):
        """
        Abilita tutti i canali nella lista canali.
        """
        for i in range(self.channels_widget.count()):
            ch_conf = self.channels_widget.item(i).data(Qt.UserRole)
            ch_conf['used'] = True
            # Aggiorna label
            label = self.channels_widget.item(i).text()
            if label.startswith('[DIS] '):
                self.channels_widget.item(i).setText(label[6:])
        self.channels_widget.repaint()

    def disable_all_channels(self):
        """
        Disabilita tutti i canali nella lista canali.
        """
        for i in range(self.channels_widget.count()):
            ch_conf = self.channels_widget.item(i).data(Qt.UserRole)
            ch_conf['used'] = False
            # Aggiorna label
            label = self.channels_widget.item(i).text()
            if not label.startswith('[DIS] '):
                self.channels_widget.item(i).setText('[DIS] ' + label)
        self.channels_widget.repaint()

    def update_series_combo(self):
        """
        Aggiorna la combo delle serie in base al tipo selezionato.
        Gestisce struttura a lista di oggetti (series_id, series_name, models).
        """
        type_key = self.type_combo.currentData()
        self.series_combo.clear()
        self._current_series_list = []  # Salva la lista per uso in update_model_combo
        if not type_key or type_key not in self.type_map:
            return
        type_name = self.type_map[type_key][1]
        series_list = self.load_instruments.get_series(type_name)
        if not series_list:
            return
        for s in series_list:
            label = s.get('series_name', s.get('series_id', str(s)))
            self.series_combo.addItem(label, s.get('series_id', label))
        self._current_series_list = series_list
        self.update_model_combo()

    def update_model_combo(self):
        """
        Aggiorna la combo dei modelli in base alla serie selezionata.
        Gestisce struttura a lista di oggetti.
        """
        type_key = self.type_combo.currentData()
        series_id = self.series_combo.currentData()
        self.model_combo.clear()
        if not type_key or not series_id or not hasattr(self, '_current_series_list'):
            return
        type_name = self.type_map[type_key][1]
        models = self.load_instruments.get_models(type_name, series_id)
        if not models:
            return
        for m in models:
            label = m.get('name', m.get('id', str(m)))
            self.model_combo.addItem(label, m.get('id', label))
        self._current_model_list = models
        self.update_connection_types()

    def update_connection_types(self):
        """
        Aggiorna la combo dei tipi di connessione in base al modello selezionato.
        """
        type_key = self.type_combo.currentData()
        series_id = self.series_combo.currentData()
        model_id = self.model_combo.currentData()
        self.connection_type_combo.clear()
        if not type_key or not series_id or not model_id or not hasattr(self, '_current_model_list'):
            return
        type_name = self.type_map[type_key][1]
        conn_types = self.load_instruments.get_supported_connections(type_name, series_id, model_id)
        if not conn_types:
            return
        for conn in conn_types:
            label = conn.get('type', conn.get('address_format_example', str(conn)))
            self.connection_type_combo.addItem(label, label)
        self.update_channels_widget()

    def update_channels_widget(self):
        """
        Aggiorna la visualizzazione dei canali per il modello selezionato.
        Mostra solo i canali usati e precompila i campi se già configurati.
        Di default tutti i canali sono disattivato (used: False).
        """
       
        self.channels_widget.clear()
        type_key = self.type_combo.currentData()
        series_id = self.series_combo.currentData()
        model_id = self.model_combo.currentData()
        if not type_key or not series_id or not model_id or not hasattr(self, '_current_model_list'):
            return
        type_name = self.type_map[type_key][1]
        channels = self.load_instruments.get_channel_info(type_name, series_id, model_id)
        n_channels = len(channels) if channels else 0
        channel_labels = [ch.get('label', f"Ch{i+1}") for i, ch in enumerate(channels)] if channels else []
        # Cerca se esiste già una configurazione per questo strumento
        instance_name = self.instance_name_edit.text().strip()
        existing = None
        for inst in self.inst_data.get('instruments', []):
            if inst.get('instance_name', '') == instance_name:
                existing = inst
                break
        used_channels = existing.get('channels', []) if existing else []
        for ch_idx in range(n_channels):
            # Cerca se già configurato
            ch_conf = next((c for c in used_channels if c.get('index', -1) == ch_idx), None)
            if not ch_conf:
                ch_conf = {'index': ch_idx, 'used': False}  # Di default disattivato
                if type_key == 'dataloggers':
                    ch_conf['measured_variable'] = ''
                    ch_conf['attenuation'] = 1.0
                    ch_conf['measure_type'] = 'voltage'
                else:
                    ch_conf['variable'] = ''
                    ch_conf['attenuation'] = 1.0
            label = channel_labels[ch_idx] if ch_idx < len(channel_labels) else f"Ch{ch_idx+1}"
            if not ch_conf.get('used', False):
                label = '[DIS] ' + label
            if type_key == 'dataloggers':
                label += f" ({ch_conf.get('measured_variable','')})"
            elif type_key in ['power_supplies', 'electronic_loads']:
                label += f" ({ch_conf.get('variable','')})"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, ch_conf)
            self.channels_widget.addItem(item)

    def add_instrument_to_inst(self):
        """
        Aggiunge o aggiorna uno strumento nella lista, salvando solo i canali usati e tutte le variabili.
        """
        instance_name = self.instance_name_edit.text().strip()
        type_key = self.type_combo.currentData()
        series = self.series_combo.currentData()
        model = self.model_combo.currentData()
        conn_type = self.connection_type_combo.currentData()
        visa_addr = self.visa_address_label.text().strip()
        # Raccogli configurazione canali dalla QListWidget
        channels = []
        for i in range(self.channels_widget.count()):
            ch_conf = self.channels_widget.item(i).data(Qt.UserRole)
            # Salva solo se usato
            if ch_conf.get('used', True):
                channels.append(ch_conf)
        # Aggiorna o aggiungi
        found = False
        for inst in self.inst_data['instruments']:
            if inst.get('instance_name','') == instance_name:
                inst.update({
                    'instrument_type': type_key,
                    'series': series,
                    'model': model,
                    'connection_type': conn_type,
                    'visa_address': visa_addr,
                    'channels': channels
                })
                found = True
                break
        if not found:
            self.inst_data['instruments'].append({
                'instance_name': instance_name,
                'instrument_type': type_key,
                'series': series,
                'model': model,
                'connection_type': conn_type,
                'visa_address': visa_addr,
                'channels': channels
            })
        self.refresh_instruments_list()
        self.save_instruments()
        self.update_channels_widget()

    def edit_instrument_channels(self, item):
        """
        Apre la ChannelConfigDialog specializzata per modificare i canali e l'indirizzo VISA dello strumento selezionato.
        """
        inst = item.data(Qt.UserRole)
        # Scegli il dialog corretto in base al tipo di strumento
        if inst.get('instrument_type') == 'power_supply':
            dlg = PowerSupplyConfigDialog(inst, self)
        elif inst.get('instrument_type') == 'electronic_load':
            dlg = ElectronicLoadConfigDialog(inst, self)
        elif inst.get('instrument_type') == 'datalogger':
            dlg = DataloggerConfigDialog(inst, self)
        else:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, self.translator.t('error'), self.translator.t('unknown_instrument_type') if hasattr(self.translator, 't') else 'Tipo strumento sconosciuto')
            return 
        if dlg.exec_() == QDialog.Accepted:
            # Aggiorna indirizzo VISA e canali
            inst['visa_address'] = dlg.get_visa_address()
            inst['channels'] = dlg.get_channels()
            self.refresh_instruments_list()
            self.save_instruments()

    def open_visa_address_dialog(self):
        """
        Dialog per comporre l'indirizzo VISA (placeholder, da implementare secondo necessità).
        """
        from PyQt5.QtWidgets import QInputDialog
        addr, ok = QInputDialog.getText(self, self.translator.t('compose_visa_address'), self.translator.t('enter_visa_address'))
        if ok:
            self.visa_address_label.setText(addr)

    def save_changes(self):
        """
        Salva i dati attuali nel file .inst e chiude la dialog.
        Mostra un messaggio di errore se il salvataggio fallisce.
        """
        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(self.inst_data, f, indent=2)
            self.accept()
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, self.translator.t('error'), f"Errore salvataggio .inst: {e}")

    def refresh_instruments_list(self):
        """
        Aggiorna la QListWidget degli strumenti aggiunti, mostrando nome istanza, tipo, modello e canali abilitati.
        """
        self.instruments_list_widget.clear()
        for inst in self.inst_data.get('instruments', []):
            instance_name = inst.get('instance_name', '')
            type_key = inst.get('instrument_type', '')
            model = inst.get('model', '')
            channels = inst.get('channels', [])
            # Mostra solo i canali abilitati
            enabled_channels = [ch for ch in channels if ch.get('used', True)]
            ch_descr = ', '.join(
                ch.get('measured_variable', ch.get('variable', f"Ch{ch.get('index', '?')+1}"))
                for ch in enabled_channels
            )
            label = f"{instance_name} [{type_key}] {model} | Canali: {ch_descr}"
            item = QListWidgetItem(label)
            # Salva l'intero dict per doppio click/modifica
            item.setData(Qt.UserRole, inst)
            self.instruments_list_widget.addItem(item)

    def remove_selected_instrument(self):
        """
        Rimuove lo strumento selezionato dalla lista e aggiorna il file .inst.
        """
        selected = self.instruments_list_widget.currentRow()
        if selected < 0:
            return
        # Rimuovi dallo storage
        if 0 <= selected < len(self.inst_data.get('instruments', [])):
            del self.inst_data['instruments'][selected]
            self.refresh_instruments_list()
            self.save_inst_file()

    def save_inst_file(self):
        """
        Salva i dati attuali di self.inst_data nel file .inst associato.
        Mostra un messaggio di errore se il salvataggio fallisce.
        """
        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(self.inst_data, f, indent=2)
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, self.translator.t('error'), f"Errore salvataggio .inst: {e}")

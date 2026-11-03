import json
import logging
logger = logging.getLogger(__name__)
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit, QMessageBox
from PyQt6.QtCore import Qt

# =========================
# WasFileDialog
# =========================
class WasFileDialog(QDialog):
    """
    Dialog per la modifica di un file .was (oscilloscope settings).
    Permette di configurare i canali abilitati, volt/div per canale e tempo/div globale.
    """
    def __init__(self, file_path, translator, project_data=None, parent=None):
        """
        Inizializza la finestra di dialogo per la modifica di un file .was.
        :param file_path: Percorso del file .was da modificare.
        :param translator: Istanza del traduttore per la localizzazione.
        :param project_data: Dati del progetto (opzionale, per recuperare info strumenti)
        :param parent: Widget genitore.
        """
        super().__init__(parent)
        from PyQt6.QtWidgets import (QLineEdit, QFormLayout, QVBoxLayout, QHBoxLayout, 
                                      QLabel, QTextEdit, QPushButton, QGroupBox, QComboBox, QCheckBox)
        self.translator = translator
        self.file_path = file_path
        self.project_data = project_data
        self.setWindowTitle(self.translator.t('edit_was_file'))
        self.setModal(True)
        
        # Layout principale orizzontale: sinistra parametri, destra JSON
        main_layout = QHBoxLayout()
        
        # --- Sezione sinistra: parametri ---
        left_layout = QVBoxLayout()
        
        # --- Sezione Canali Oscilloscopio ---
        self.setup_channels_section(left_layout)
        
        # --- Sezione Tempo/Div ---
        self.setup_timing_section(left_layout)

        # --- Sezione Trigger ---
        self.setup_trigger_section(left_layout)
        
        # Pulsante per applicare i parametri al JSON
        self.apply_params_btn = QPushButton(self.translator.t('apply_to_data'))
        self.apply_params_btn.clicked.connect(self.apply_params_to_json)
        left_layout.addWidget(self.apply_params_btn)
        left_layout.addStretch()
        
        # --- Sezione destra: editor JSON ---
        right_layout = QVBoxLayout()
        self.data_edit = QTextEdit()
        
        # Carica il contenuto del file .was
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
            self.data_edit.setText(json.dumps(self.data, indent=2))
        except (OSError, ValueError) as e:
            logger.warning(f"Cannot read .was file {self.file_path}, using defaults: {e}")
            self.data = {"type": "oscilloscope_settings", "channels": [], "settings": {}}
            self.data_edit.setText(json.dumps(self.data, indent=2))
        
        right_layout.addWidget(QLabel(self.translator.t('oscilloscope_settings_data')))
        right_layout.addWidget(self.data_edit)
        
        # Pulsante per salvare le modifiche
        save_btn = QPushButton(self.translator.t('save'))
        save_btn.clicked.connect(self.save_changes)
        right_layout.addWidget(save_btn)
        
        # --- Unione layout ---
        main_layout.addLayout(left_layout, 1)
        main_layout.addLayout(right_layout, 2)
        self.setLayout(main_layout)
        
        # Precompila i parametri a sinistra se già presenti nel JSON
        self.populate_params_from_json()
        
        # Sincronizza i parametri se il JSON viene modificato manualmente
        self.data_edit.textChanged.connect(self.sync_params_from_json)

    def get_oscilloscopes(self):
        """
        Recupera gli oscilloscopi configurati nel file .inst del progetto.
        Ritorna una lista di dict: {'instance_name', 'model_id', 'channels'}.
        Accetta sia il tipo singolare ('oscilloscope') che plurale ('oscilloscopes').
        """
        if not self.project_data:
            return []

        inst_file = self.project_data.get('inst_file')
        if not inst_file:
            return []

        import os
        project_dir = os.path.dirname(self.file_path)
        inst_file_path = os.path.join(project_dir, inst_file)

        try:
            with open(inst_file_path, 'r', encoding='utf-8') as f:
                inst_data = json.load(f)
            instruments = inst_data.get('instruments', [])
            scopes = []
            for inst in instruments:
                if inst.get('instrument_type') in ('oscilloscope', 'oscilloscopes'):
                    scopes.append({
                        'instance_name': inst.get('instance_name', 'OSC'),
                        'model_id': inst.get('model_id', inst.get('model', '')),
                        'channels': inst.get('channels', []),
                    })
            return scopes
        except Exception as e:
            print(f"Errore nel caricamento file .inst: {e}")
            return []

    def get_oscilloscope_channels(self, instance_name=None):
        """
        Recupera i canali di un oscilloscopio dal file .inst del progetto.
        :param instance_name: Nome istanza dell'oscilloscopio (opzionale; usa il primo).
        :return: Lista di dict con info sui canali.
        """
        scopes = self.get_oscilloscopes()
        if not scopes:
            return []
        if instance_name is not None:
            scope = next((s for s in scopes if s['instance_name'] == instance_name), None)
            if scope:
                return scope['channels']
        return scopes[0]['channels']

    def setup_channels_section(self, layout):
        """
        Crea la sezione per configurare i canali dell'oscilloscopio.
        Permette di selezionare l'oscilloscopio quando il progetto ne ha più di uno.
        """
        from PyQt6.QtWidgets import QGroupBox, QComboBox, QHBoxLayout

        self.scopes = self.get_oscilloscopes()
        self.channel_widgets = []

        group = QGroupBox(self.translator.t('oscilloscope_channels'))
        group_layout = QVBoxLayout()

        if self.scopes:
            # Selettore oscilloscopio
            selector_layout = QHBoxLayout()
            selector_label = QLabel(self.translator.t('select_oscilloscope'))
            self.scope_combo = QComboBox()
            for s in self.scopes:
                label = s['instance_name']
                if s['model_id']:
                    label += f" ({s['model_id']})"
                self.scope_combo.addItem(label, s['instance_name'])
            self.scope_combo.currentIndexChanged.connect(self.on_scope_changed)
            selector_layout.addWidget(selector_label)
            selector_layout.addWidget(self.scope_combo, 1)
            group_layout.addLayout(selector_layout)
        else:
            # Nessun oscilloscopio configurato - mostra canali di default
            info_label = QLabel(self.translator.t('no_oscilloscope_configured'))
            info_label.setWordWrap(True)
            info_label.setStyleSheet("color: orange; padding: 5px;")
            group_layout.addWidget(info_label)

        self.channels_group_layout = group_layout
        self._channel_layouts = []
        group.setLayout(group_layout)
        layout.addWidget(group)

        # Crea i widget canali per l'oscilloscopio selezionato (o default)
        channels = self.get_oscilloscope_channels() or []
        if not channels:
            channels = [
                {'channel_id': f'CH{i+1}', 'name': f'CH{i+1}', 'enabled': False,
                 'volt_per_div': '1V', 'probe_attenuation': 1.0}
                for i in range(4)
            ]
        self._rebuild_channel_widgets(channels)

    def on_scope_changed(self, index):
        """Ricostruisce i widget canali quando cambia l'oscilloscopio selezionato."""
        instance_name = self.scope_combo.itemData(index) if self.scopes else None
        channels = self.get_oscilloscope_channels(instance_name)
        if not channels:
            channels = []
        self._rebuild_channel_widgets(channels)
        # Aggiorna i canali disponibili per la sorgente trigger
        self._update_trigger_source_combo()
        # Riapplica i valori del file .was sui nuovi widget
        if hasattr(self, 'data'):
            self.populate_params_from_json()

    def _rebuild_channel_widgets(self, channels):
        """Rigenera i widget dei canali nel layout del gruppo."""
        from PyQt6.QtWidgets import QVBoxLayout, QCheckBox, QLabel, QComboBox

        # Rimuove i layout dei canali precedentemente creati (selettore/info restano)
        for sub in self._channel_layouts:
            while sub.count():
                sub_item = sub.takeAt(0)
                if sub_item.widget():
                    sub_item.widget().deleteLater()
            self.channels_group_layout.removeItem(sub)
            if hasattr(sub, 'deleteLater'):
                sub.deleteLater()
        self._channel_layouts = []

        self.channel_widgets = []
        for ch in channels:
            ch_layout = QVBoxLayout()

            # Checkbox per abilitare il canale
            ch_enable = QCheckBox(f"{ch.get('channel_id', 'CH?')} - {ch.get('name', 'Signal')}")
            ch_enable.setChecked(ch.get('enabled', False))
            ch_layout.addWidget(ch_enable)

            # Combobox per Volt/div
            volt_label = QLabel(self.translator.t('volt_per_div'))
            volt_combo = QComboBox()
            volt_options = ["1mV", "2mV", "5mV", "10mV", "20mV", "50mV",
                           "100mV", "200mV", "500mV", "1V", "2V", "5V", "10V", "20V", "50V", "100V"]
            volt_combo.addItems(volt_options)
            current_vdiv = ch.get('volt_per_div', '1V')
            idx = volt_combo.findText(current_vdiv)
            if idx >= 0:
                volt_combo.setCurrentIndex(idx)

            ch_layout.addWidget(volt_label)
            ch_layout.addWidget(volt_combo)

            # Salva riferimenti ai widget
            self.channel_widgets.append({
                'channel_id': ch.get('channel_id', f'CH{len(self.channel_widgets)+1}'),
                'name': ch.get('name', 'Signal'),
                'enable_widget': ch_enable,
                'volt_div_widget': volt_combo,
                'probe_attenuation': ch.get('probe_attenuation', 1.0)
            })

            self.channels_group_layout.addLayout(ch_layout)
            self._channel_layouts.append(ch_layout)

    def setup_timing_section(self, layout):
        """
        Crea la sezione per configurare il tempo/div.
        """
        from PyQt6.QtWidgets import QGroupBox, QFormLayout, QLineEdit
        
        group = QGroupBox(self.translator.t('timing_settings'))
        form = QFormLayout()
        
        # Campo per tempo/div (accetta anche notazione 100k, 1n1, ecc.)
        self.time_div_edit = QLineEdit()
        self.time_div_edit.setPlaceholderText(self.translator.t('time_div_placeholder'))
        form.addRow(self.translator.t('time_div_label'), self.time_div_edit)
        
        group.setLayout(form)
        layout.addWidget(group)

    def setup_trigger_section(self, layout):
        """
        Crea la sezione per configurare il trigger: sorgente (canale), fronte
        (rise/fall), livello e modalità.
        """
        from PyQt6.QtWidgets import QGroupBox, QFormLayout, QComboBox, QLineEdit
        from PyQt6.QtGui import QDoubleValidator

        group = QGroupBox(self.translator.t('trigger_settings'))
        form = QFormLayout()

        # Sorgente trigger (canali dell'oscilloscopio selezionato)
        self.trigger_source_combo = QComboBox()
        form.addRow(self.translator.t('trigger_source'), self.trigger_source_combo)

        # Fronte trigger (rise/fall)
        self.trigger_slope_combo = QComboBox()
        self.trigger_slope_combo.addItem(self.translator.t('trigger_rise'), 'RISE')
        self.trigger_slope_combo.addItem(self.translator.t('trigger_fall'), 'FALL')
        form.addRow(self.translator.t('trigger_slope'), self.trigger_slope_combo)

        # Livello trigger (volt)
        self.trigger_level_edit = QLineEdit()
        self.trigger_level_edit.setPlaceholderText("1.5")
        validator = QDoubleValidator(-10000.0, 10000.0, 3, self.trigger_level_edit)
        self.trigger_level_edit.setValidator(validator)
        form.addRow(self.translator.t('trigger_level'), self.trigger_level_edit)

        # Modalità trigger
        self.trigger_mode_combo = QComboBox()
        self.trigger_mode_combo.addItem('AUTO', 'AUTO')
        self.trigger_mode_combo.addItem('NORM', 'NORM')
        form.addRow(self.translator.t('trigger_mode'), self.trigger_mode_combo)

        group.setLayout(form)
        layout.addWidget(group)

        # Popola la combo sorgente con i canali dell'oscilloscopio selezionato
        self._update_trigger_source_combo()

    def _update_trigger_source_combo(self):
        """
        Aggiorna la combo sorgente trigger con i canali dell'oscilloscopio selezionato.
        Preserva la selezione se il canale è ancora disponibile.
        """
        if not hasattr(self, 'trigger_source_combo'):
            return
        current = self.trigger_source_combo.currentData()
        self.trigger_source_combo.blockSignals(True)
        self.trigger_source_combo.clear()
        channel_ids = [w['channel_id'] for w in getattr(self, 'channel_widgets', [])]
        if not channel_ids:
            channel_ids = ['CH1', 'CH2', 'CH3', 'CH4']
        for cid in channel_ids:
            self.trigger_source_combo.addItem(cid, cid)
        if current and self.trigger_source_combo.findData(current) >= 0:
            self.trigger_source_combo.setCurrentIndex(self.trigger_source_combo.findData(current))
        self.trigger_source_combo.blockSignals(False)

    def _parse_voltage(self, s):
        """Converte una stringa livello trigger ('1,5' -> 1.5) in float o None."""
        try:
            return float(str(s).strip().replace(',', '.'))
        except (ValueError, TypeError):
            return None

    def trigger_values(self):
        """
        Ritorna il dict trigger {source, slope, level, mode} dai widget della sezione.
        Level è incluso solo se valorizzato correttamente.
        """
        source = self.trigger_source_combo.currentData()
        if not source:
            return None
        values = {
            'source': source,
            'slope': self.trigger_slope_combo.currentData(),
            'mode': self.trigger_mode_combo.currentData(),
        }
        level_edit = getattr(self, 'trigger_level_edit', None)
        level = self._parse_voltage(level_edit.text()) if level_edit else None
        if level is not None:
            values['level'] = level
        return values


    def parse_time(self, s):
        """
        Converte una stringa tempo in secondi (float).
        Accetta numeri semplici ('0.001', '1e-3') e suffissi SI con o senza 's':
        'ks', 'k', 's', 'ms', 'm', 'us', 'u', 'µs', 'ns', 'n', 'ps', 'p' (es. '100us', '1ms').
        Restituisce None se la stringa non è valida.
        """
        text = s.strip().lower().replace(',', '.').replace(' ', '').replace('µ', 'u')
        if text.endswith('s'):
            text = text[:-1]
        multipliers = {'k': 1e3, 'm': 1e-3, 'u': 1e-6, 'n': 1e-9, 'p': 1e-12}
        factor = 1.0
        if text and text[-1] in multipliers:
            factor = multipliers[text[-1]]
            text = text[:-1]
        try:
            return float(text) * factor
        except ValueError:
            return None

    def populate_params_from_json(self):
        """
        Popola i campi del form a sinistra leggendo i dati dal JSON (se presenti).
        """
        settings = self.data.get('settings', {})
        tdiv = settings.get('time_per_div', '')
        
        if tdiv and hasattr(self, 'time_div_edit'):
            self.time_div_edit.setText(str(tdiv))
        
        # Popola i canali se presenti
        channels_data = self.data.get('channels', [])
        if hasattr(self, 'channel_widgets') and channels_data:
            for ch_widget in self.channel_widgets:
                # Trova i dati corrispondenti per questo canale
                ch_id = ch_widget['channel_id']
                ch_data = next((ch for ch in channels_data if ch.get('channel_id') == ch_id), None)
                
                if ch_data:
                    ch_widget['enable_widget'].setChecked(ch_data.get('enabled', False))
                    vdiv = ch_data.get('volt_per_div', '1V')
                    idx = ch_widget['volt_div_widget'].findText(vdiv)
                    if idx >= 0:
                        ch_widget['volt_div_widget'].setCurrentIndex(idx)

        # Popola la sezione trigger se presente
        trigger = self.data.get('trigger', {})
        if hasattr(self, 'trigger_source_combo'):
            src = trigger.get('source')
            if src and self.trigger_source_combo.findData(src) >= 0:
                self.trigger_source_combo.setCurrentIndex(self.trigger_source_combo.findData(src))
            slope = trigger.get('slope', 'RISE')
            idx = self.trigger_slope_combo.findData(slope)
            if idx >= 0:
                self.trigger_slope_combo.setCurrentIndex(idx)
            if 'level' in trigger:
                self.trigger_level_edit.setText(str(trigger['level']))
            mode = trigger.get('mode', 'AUTO')
            idx = self.trigger_mode_combo.findData(mode)
            if idx >= 0:
                self.trigger_mode_combo.setCurrentIndex(idx)

    def apply_params_to_json(self):
        """
        Aggiorna il JSON a destra in base ai parametri inseriti a sinistra.
        Converte i valori e aggiorna il dizionario settings, channels e trigger.
        """
        # Tempo/div globale
        tdiv = self.parse_time(self.time_div_edit.text()) if hasattr(self, 'time_div_edit') else None
        
        if tdiv is not None:
            if 'settings' not in self.data:
                self.data['settings'] = {}
            self.data['settings']['time_per_div'] = tdiv
        
        # Canali
        if hasattr(self, 'channel_widgets'):
            channels = []
            for ch_widget in self.channel_widgets:
                if ch_widget['enable_widget'].isChecked():
                    channels.append({
                        'channel_id': ch_widget['channel_id'],
                        'name': ch_widget['name'],
                        'enabled': True,
                        'volt_per_div': ch_widget['volt_div_widget'].currentText(),
                        'probe_attenuation': ch_widget.get('probe_attenuation', 1.0)
                    })
            
            self.data['channels'] = channels

        # Trigger
        trigger = self.trigger_values() if hasattr(self, 'trigger_values') else None
        if trigger:
            self.data['trigger'] = trigger
        
        # Aggiorna il visualizzatore JSON
        self.data_edit.setText(json.dumps(self.data, indent=2))

    def sync_params_from_json(self):
        """
        Aggiorna i parametri a sinistra se il JSON viene modificato manualmente.
        """
        try:
            self.data = json.loads(self.data_edit.toPlainText())
            self.populate_params_from_json()
        except Exception:
            logger.warning("Failed to sync params from JSON (invalid JSON in editor)")

    def save_changes(self):
        """
        Salva i dati attuali nel file .was e chiude la dialog.
        Mostra un messaggio di errore se il salvataggio fallisce.
        """
        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2)
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, self.translator.t('error'), str(e))


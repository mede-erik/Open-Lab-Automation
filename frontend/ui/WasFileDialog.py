import json
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
        except Exception as e:
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

    def get_oscilloscope_channels(self):
        """
        Recupera i canali dell'oscilloscopio dal file .inst del progetto.
        Ritorna una lista di dict con info sui canali.
        """
        if not self.project_data:
            return []
        
        # Il project_data è il file .json del progetto
        # Dobbiamo caricare il file .inst per avere gli strumenti
        inst_file = self.project_data.get('inst_file')
        if not inst_file:
            return []
        
        # Costruisci il percorso completo del file .inst
        import os
        project_dir = os.path.dirname(self.file_path)
        inst_file_path = os.path.join(project_dir, inst_file)
        
        # Carica il file .inst
        try:
            with open(inst_file_path, 'r', encoding='utf-8') as f:
                inst_data = json.load(f)
            
            # Cerca l'oscilloscopio negli strumenti
            instruments = inst_data.get('instruments', [])
            for inst in instruments:
                if inst.get('instrument_type') == 'oscilloscopes':
                    return inst.get('channels', [])
        except Exception as e:
            print(f"Errore nel caricamento file .inst: {e}")
            return []
        
        return []

    def setup_channels_section(self, layout):
        """
        Crea la sezione per configurare i canali dell'oscilloscopio.
        """
        from PyQt6.QtWidgets import QGroupBox, QVBoxLayout, QCheckBox, QLabel, QComboBox, QFormLayout
        
        group = QGroupBox(self.translator.t('oscilloscope_channels'))
        group_layout = QVBoxLayout()
        
        # Recupera i canali dall'oscilloscopio nel progetto
        osc_channels = self.get_oscilloscope_channels()
        
        if not osc_channels:
            # Nessun oscilloscopio configurato - mostra canali di default
            info_label = QLabel(self.translator.t('no_oscilloscope_configured'))
            info_label.setWordWrap(True)
            info_label.setStyleSheet("color: orange; padding: 5px;")
            group_layout.addWidget(info_label)
            
            # Crea canali di default
            osc_channels = [
                {'channel_id': f'CH{i+1}', 'name': f'CH{i+1}', 'enabled': False, 
                 'volt_per_div': '1V', 'probe_attenuation': 1.0}
                for i in range(4)
            ]
        
        # Crea widget per ogni canale
        self.channel_widgets = []
        form = QFormLayout()
        
        for ch in osc_channels:
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
            
            group_layout.addLayout(ch_layout)
        
        group.setLayout(group_layout)
        layout.addWidget(group)

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


    def parse_time(self, s):
        """
        Converte una stringa tipo '100k', '1n1', '0.001' in float secondi.
        Accetta anche notazione con suffissi k, m, u, n, p.
        """
        s = s.strip().lower().replace(',', '.')
        try:
            if 'k' in s:
                return float(s.replace('k','')) * 1e3
            if 'm' in s:
                return float(s.replace('m','')) * 1e-3
            if 'u' in s:
                return float(s.replace('u','')) * 1e-6
            if 'n' in s:
                return float(s.replace('n','')) * 1e-9
            if 'p' in s:
                return float(s.replace('p','')) * 1e-12
            if '1n1' in s:
                return 1e-9
            return float(s)
        except Exception:
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

    def apply_params_to_json(self):
        """
        Aggiorna il JSON a destra in base ai parametri inseriti a sinistra.
        Converte i valori e aggiorna il dizionario settings e channels.
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
            pass

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


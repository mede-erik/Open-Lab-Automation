import json
from PyQt5.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit
from PyQt5.QtCore import Qt

# =========================
# WasFileDialog
# =========================
class WasFileDialog(QDialog):
    """
    Dialog per la modifica di un file .was (oscilloscope settings), con modulo a sinistra per tempo/div e volt/div e editor JSON a destra.
    """
    def __init__(self, file_path, translator, parent=None):
        """
        Inizializza la finestra di dialogo per la modifica di un file .was.
        :param file_path: Percorso del file .was da modificare.
        :param translator: Istanza del traduttore per la localizzazione.
        :param parent: Widget genitore.
        """
        super().__init__(parent)
        from PyQt5.QtWidgets import QLineEdit, QFormLayout, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton
        self.translator = translator
        self.file_path = file_path
        self.setWindowTitle(self.translator.t('edit_was_file'))
        self.setModal(True)
        # Layout principale orizzontale: sinistra parametri, destra JSON
        main_layout = QHBoxLayout()
        # --- Sezione sinistra: parametri tempo/div e volt/div ---
        left_layout = QVBoxLayout()
        form = QFormLayout()
        # Campo per tempo/div (accetta anche notazione 100k, 1n1, ecc.)
        self.time_div_edit = QLineEdit()
        self.time_div_edit.setPlaceholderText(self.translator.t('time_div_placeholder'))
        form.addRow(self.translator.t('time_div_label'), self.time_div_edit)
        # Campo per volt/div
        self.volt_div_edit = QLineEdit()
        self.volt_div_edit.setPlaceholderText(self.translator.t('volt_div_placeholder'))
        form.addRow(self.translator.t('volt_div_label'), self.volt_div_edit)
        left_layout.addLayout(form)
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
            self.data = {"type": "oscilloscope_settings", "settings": {}}
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
        vdiv = settings.get('volt_per_div', '')
        if tdiv:
            self.time_div_edit.setText(str(tdiv))
        if vdiv:
            self.volt_div_edit.setText(str(vdiv))
        # Seleziona le variabili se presenti nel JSON
        sweep_var = self.data.get('sweep_variable', None)
        measured_var = self.data.get('measured_variable', None)
        if hasattr(self, 'sweep_var_combo') and sweep_var:
            idx = self.sweep_var_combo.findData(sweep_var)
            if idx >= 0:
                self.sweep_var_combo.setCurrentIndex(idx)
        if hasattr(self, 'measured_var_combo') and measured_var:
            idx = self.measured_var_combo.findData(measured_var)
            if idx >= 0:
                self.measured_var_combo.setCurrentIndex(idx)

    def apply_params_to_json(self):
        """
        Aggiorna il JSON a destra in base ai parametri inseriti a sinistra.
        Converte i valori e aggiorna il dizionario settings.
        """
        tdiv = self.parse_time(self.time_div_edit.text())
        try:
            vdiv = float(self.volt_div_edit.text().replace(',', '.'))
        except Exception:
            vdiv = None
        if tdiv is not None and vdiv is not None:
            self.data['settings']['time_per_div'] = tdiv
            self.data['settings']['volt_per_div'] = vdiv
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
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, self.translator.t('error'), str(e))


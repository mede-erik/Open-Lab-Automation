import json
from PyQt5.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout, QLabel , QLineEdit, QPushButton, QTextEdit, QComboBox
from PyQt5.QtCore import Qt 

# =========================
# EffFileDialog
# =========================
class EffFileDialog(QDialog):
    """
    Dialog for editing a .eff (efficiency) file.
    """
    def __init__(self, file_path, translator, parent=None):
        """
        Initialize the dialog and load the .eff file data.
        :param file_path: Path to the .eff file.
        :param translator: Translator instance.
        :param parent: Parent widget.
        """
        super().__init__(parent)
        self.translator = translator
        self.file_path = file_path
        self.setWindowTitle(self.translator.t('edit_eff_file'))
        self.setModal(True)
        import PyQt5.QtWidgets as QtW
        # Main horizontal layout: left parameters, right JSON editor
        main_layout = QtW.QHBoxLayout()
        # --- Left section: Vin Sweep parameters ---
        self.left_layout = QtW.QVBoxLayout()
        self.setup_dynamic_variable_selectors()  # <--- AGGIUNTA QUI
        group_vin = QtW.QGroupBox(self.translator.t('vin_sweep'))
        form_vin = QtW.QFormLayout()
        # Input mode: list of values or range
        self.mode_group = QtW.QButtonGroup(self)
        self.list_radio = QtW.QRadioButton(self.translator.t('vin_list_mode'))
        self.range_radio = QtW.QRadioButton(self.translator.t('vin_range_mode'))
        self.mode_group.addButton(self.list_radio)
        self.mode_group.addButton(self.range_radio)
        self.list_radio.setChecked(True)
        form_vin.addRow(self.list_radio)
        # Field for list of Vin values
        self.vin_list_edit = QtW.QLineEdit()
        self.vin_list_edit.setPlaceholderText(self.translator.t('vin_list_placeholder'))
        form_vin.addRow(self.vin_list_edit)
        # Field for Vin range (start, stop, n points)
        form_vin.addRow(self.range_radio)
        self.vin_start_edit = QtW.QLineEdit()
        self.vin_start_edit.setPlaceholderText(self.translator.t('vin_start_placeholder'))
        self.vin_stop_edit = QtW.QLineEdit()
        self.vin_stop_edit.setPlaceholderText(self.translator.t('vin_stop_placeholder'))
        self.vin_points_spin = QtW.QSpinBox()
        self.vin_points_spin.setMinimum(2)
        self.vin_points_spin.setMaximum(1000)
        self.vin_points_spin.setValue(5)
        range_row_vin = QtW.QHBoxLayout()
        range_row_vin.addWidget(self.vin_start_edit)
        range_row_vin.addWidget(self.vin_stop_edit)
        range_row_vin.addWidget(QtW.QLabel(self.translator.t('vin_points_label')))
        range_row_vin.addWidget(self.vin_points_spin)
        form_vin.addRow(range_row_vin)
        group_vin.setLayout(form_vin)
        self.left_layout.addWidget(group_vin)
        # --- Iout Sweep section ---
        group_iout = QtW.QGroupBox(self.translator.t('iout_sweep'))
        form_iout = QtW.QFormLayout()
        self.iout_mode_group = QtW.QButtonGroup(self)
        self.iout_list_radio = QtW.QRadioButton(self.translator.t('iout_list_mode'))
        self.iout_range_radio = QtW.QRadioButton(self.translator.t('iout_range_mode'))
        self.iout_mode_group.addButton(self.iout_list_radio)
        self.iout_mode_group.addButton(self.iout_range_radio)
        self.iout_list_radio.setChecked(True)
        form_iout.addRow(self.iout_list_radio)
        # Field for list of Iout values
        self.iout_list_edit = QtW.QLineEdit()
        self.iout_list_edit.setPlaceholderText(self.translator.t('iout_list_placeholder'))
        form_iout.addRow(self.iout_list_edit)
        # Field for Iout range (start, stop, n points)
        form_iout.addRow(self.iout_range_radio)
        self.iout_start_edit = QtW.QLineEdit()
        self.iout_start_edit.setPlaceholderText(self.translator.t('iout_start_placeholder'))
        self.iout_stop_edit = QtW.QLineEdit()
        self.iout_stop_edit.setPlaceholderText(self.translator.t('iout_stop_placeholder'))
        self.iout_points_spin = QtW.QSpinBox()
        self.iout_points_spin.setMinimum(2)
        self.iout_points_spin.setMaximum(1000)
        self.iout_points_spin.setValue(5)
        range_row_iout = QtW.QHBoxLayout()
        range_row_iout.addWidget(self.iout_start_edit)
        range_row_iout.addWidget(self.iout_stop_edit)
        range_row_iout.addWidget(QtW.QLabel(self.translator.t('iout_points_label')))
        range_row_iout.addWidget(self.iout_points_spin)
        form_iout.addRow(range_row_iout)
        group_iout.setLayout(form_iout)
        self.left_layout.addWidget(group_iout)
        # Button to apply parameters to JSON
        self.apply_params_btn = QtW.QPushButton(self.translator.t('apply_to_data'))
        self.apply_params_btn.clicked.connect(self.apply_params_to_json)
        self.left_layout.addWidget(self.apply_params_btn)
        self.left_layout.addStretch()
        # --- Right section: JSON editor ---
        right_layout = QtW.QVBoxLayout()
        self.data_edit = QtW.QTextEdit()
        # Load the .eff file content
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
            self.data_edit.setText(json.dumps(self.data, indent=2))
        except Exception as e:
            self.data = {"type": "efficiency", "data": {}}
            self.data_edit.setText(json.dumps(self.data, indent=2))
        right_layout.addWidget(QtW.QLabel(self.translator.t('efficiency_data')))
        right_layout.addWidget(self.data_edit)
        # Button to save changes
        save_btn = QtW.QPushButton(self.translator.t('save'))
        save_btn.clicked.connect(self.save_changes)
        right_layout.addWidget(save_btn)
        # --- Combine layouts ---
        main_layout.addLayout(self.left_layout, 1)
        main_layout.addLayout(right_layout, 2)
        self.setLayout(main_layout)
        # Prefill parameters on the left if present in JSON
        self.populate_params_from_json()
        # Sync parameters if JSON is manually modified
        self.data_edit.textChanged.connect(self.sync_params_from_json)

    def get_inst_file_variables(self):
        """
        Carica i nomi delle variabili di setpoint (VAR_set) e misura (VAR) dal file .inst associato al progetto.
        Restituisce due liste: setpoint_vars, measured_vars.
        """
        import os, json
        # Trova la directory del progetto e il file .inst associato
        project_dir = os.path.dirname(self.file_path)
        # Cerca il file .json del progetto nella stessa cartella
        project_json = None
        for f in os.listdir(project_dir):
            if f.endswith('.json'):
                try:
                    with open(os.path.join(project_dir, f), 'r', encoding='utf-8') as pj:
                        data = json.load(pj)
                    if 'inst_file' in data:
                        project_json = data
                        break
                except Exception:
                    continue
        if not project_json:
            return [], []
        inst_file = project_json.get('inst_file')
        inst_path = os.path.join(project_dir, inst_file)
        if not os.path.isfile(inst_path):
            return [], []
        try:
            with open(inst_path, 'r', encoding='utf-8') as f:
                inst_data = json.load(f)
        except Exception:
            return [], []
        setpoint_vars = []
        measured_vars = []
        # Estrai variabili dai canali degli strumenti
        for inst in inst_data.get('instruments', []):
            type_key = inst.get('instrument_type', '')
            channels = inst.get('channels', [])
            if type_key in ['power_supplies', 'electronic_loads']:
                for ch in channels:
                    var = ch.get('variable', '')
                    if var:
                        setpoint_vars.append(var)
            elif type_key in ['dataloggers']:
                for ch in channels:
                    var = ch.get('measured_variable', '')
                    if var:
                        measured_vars.append(var)
        # Rimuovi duplicati e ordina
        setpoint_vars = sorted(set(setpoint_vars))
        measured_vars = sorted(set(setpoint_vars + measured_vars))
        return setpoint_vars, measured_vars

    def setup_dynamic_variable_selectors(self):
        """
        Crea le combobox per la selezione delle variabili sweep (setpoint) e misura, usando i nomi dinamici dal .inst.
        """
        set_vars, meas_vars = self.get_inst_file_variables()
        # Sweep variable (setpoint)
        self.sweep_var_combo = QComboBox()
        for v in set_vars:
            self.sweep_var_combo.addItem(f"{v}_set", v)
        self.sweep_var_combo.setToolTip(self.translator.t('select_sweep_variable'))
        # Measured variable
        self.measured_var_combo = QComboBox()
        for v in meas_vars:
            self.measured_var_combo.addItem(v, v)
        self.measured_var_combo.setToolTip(self.translator.t('select_measured_variable'))
        # Inserisci le combobox in cima al layout a sinistra
        self.left_layout.insertWidget(0, QLabel(self.translator.t('sweep_variable_label')))
        self.left_layout.insertWidget(1, self.sweep_var_combo)
        self.left_layout.insertWidget(2, QLabel(self.translator.t('measured_variable_label')))
        self.left_layout.insertWidget(3, self.measured_var_combo)

    def populate_params_from_json(self):
        """
        Popola i campi del form a sinistra leggendo i dati dal JSON (se presenti), incluse le variabili dinamiche.
        """
        vin = self.data.get('data', {}).get('Vin loop', None)
        if isinstance(vin, list):
            self.list_radio.setChecked(True)
            self.vin_list_edit.setText(','.join(str(v) for v in vin))
        elif isinstance(vin, dict):
            self.range_radio.setChecked(True)
            self.vin_start_edit.setText(str(vin.get('start', '')))
            self.vin_stop_edit.setText(str(vin.get('stop', '')))
            self.vin_points_spin.setValue(int(vin.get('points', 5)))
        iout = self.data.get('data', {}).get('Iout loop', None)
        if isinstance(iout, list):
            self.iout_list_radio.setChecked(True)
            self.iout_list_edit.setText(','.join(str(i) for i in iout))
        elif isinstance(iout, dict):
            self.iout_range_radio.setChecked(True)
            self.iout_start_edit.setText(str(iout.get('start', '')))
            self.iout_stop_edit.setText(str(iout.get('stop', '')))
            self.iout_points_spin.setValue(int(iout.get('points', 5)))
        # Seleziona le variabili se presenti nel JSON
        sweep_var = self.data.get('sweep_variable', None)
        measured_var = self.data.get('measured_variable', None)
        if hasattr(self, 'sweep_var_combo') and sweep_var:
            idx = self.sweep_var_combo.findData(sweep_var)
            if idx >= 0:
                self.sweep_var_combo.setCurrentIndex(idx)

            if measured_var:
                self.measured_var_combo.setCurrentText(measured_var)

    def save_changes(self):
        """
        Salva i dati modificati nel file .eff, includendo le variabili sweep e misura selezionate.
        Mostra un messaggio di errore se il salvataggio fallisce.
        """
        try:
            data = json.loads(self.data_edit.toPlainText())
            # Salva le variabili selezionate
            data['sweep_variable'] = self.sweep_var_combo.currentData()
            data['measured_variable'] = self.sweep_var_combo.currentData()
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            self.accept()
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, self.translator.t('error'), str(e))


    def apply_params_to_json(self):
        """
        Applica i parametri inseriti nei campi Vin/Iout (lista o range) al JSON e aggiorna l'editor.
        """
        data = self.data
        # Vin
        if self.list_radio.isChecked():
            vin_list = [float(v.strip()) for v in self.vin_list_edit.text().split(',') if v.strip()]
            data.setdefault('data', {})['Vin loop'] = vin_list
        elif self.range_radio.isChecked():
            try:
                start = float(self.vin_start_edit.text())
                stop = float(self.vin_stop_edit.text())
                points = int(self.vin_points_spin.value())
                data.setdefault('data', {})['Vin loop'] = {'start': start, 'stop': stop, 'points': points}
            except Exception:
                pass
        # Iout
        if self.iout_list_radio.isChecked():
            iout_list = [float(v.strip()) for v in self.iout_list_edit.text().split(',') if v.strip()]
            data.setdefault('data', {})['Iout loop'] = iout_list
        elif self.iout_range_radio.isChecked():
            try:
                start = float(self.iout_start_edit.text())
                stop = float(self.iout_stop_edit.text())
                points = int(self.iout_points_spin.value())
                data.setdefault('data', {})['Iout loop'] = {'start': start, 'stop': stop, 'points': points}
            except Exception:
                pass
        # Aggiorna editor JSON
        self.data_edit.setText(json.dumps(data, indent=2))

    def sync_params_from_json(self):
        """
        Aggiorna i campi del form a sinistra leggendo i dati dal JSON editor (quando modificato manualmente).
        """
        try:
            self.data = json.loads(self.data_edit.toPlainText())
            self.populate_params_from_json()
        except Exception:
            pass



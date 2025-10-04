import json
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QPushButton, 
    QTextEdit, QComboBox, QMessageBox, QGroupBox, QFormLayout, QSpinBox,
    QRadioButton, QButtonGroup, QListWidget, QListWidgetItem, QDoubleSpinBox
)
from PyQt6.QtCore import Qt 

# =========================
# EffFileDialog
# =========================
class EffFileDialog(QDialog):
    """
    Dialog for editing a .eff (efficiency) file with multi-variable nested sweep support.
    """
    def __init__(self, file_path, translator, project_data=None, parent=None):
        """
        Initialize the dialog and load the .eff file data.
        :param file_path: Path to the .eff file.
        :param translator: Translator instance.
        :param project_data: Dictionary with project data including control_variables and measure_variables.
        :param parent: Parent widget.
        """
        super().__init__(parent)
        self.translator = translator
        self.file_path = file_path
        self.project_data = project_data or {}
        self.setWindowTitle(self.translator.t('edit_eff_file'))
        self.setModal(True)
        self.resize(1000, 700)
        
        # Dictionary to store sweep configurations for each variable
        self.sweep_configs = {}
        
        # Main horizontal layout: left parameters, right JSON editor
        main_layout = QHBoxLayout()
        
        # --- Left section: Sweep parameters ---
        self.left_layout = QVBoxLayout()
        
        # Sweep order section
        self.setup_sweep_order_section()
        
        # Timing parameters section
        self.setup_timing_section()
        
        # Selected variable configuration section
        self.setup_variable_config_section()
        
        # Button to apply parameters to JSON
        self.apply_params_btn = QPushButton(self.translator.t('apply_to_data'))
        self.apply_params_btn.clicked.connect(self.apply_params_to_json)
        self.left_layout.addWidget(self.apply_params_btn)
        
        self.left_layout.addStretch()
        
        # --- Right section: JSON editor ---
        right_layout = QVBoxLayout()
        self.data_edit = QTextEdit()
        
        # Load the .eff file content
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
            self.data_edit.setText(json.dumps(self.data, indent=2))
        except Exception as e:
            self.data = {"type": "efficiency", "sweeps": [], "timing": {}}
            self.data_edit.setText(json.dumps(self.data, indent=2))
        
        right_layout.addWidget(QLabel(self.translator.t('efficiency_data')))
        right_layout.addWidget(self.data_edit)
        
        # Button to save changes
        save_btn = QPushButton(self.translator.t('save'))
        save_btn.clicked.connect(self.save_changes)
        right_layout.addWidget(save_btn)
        
        # --- Combine layouts ---
        main_layout.addLayout(self.left_layout, 1)
        main_layout.addLayout(right_layout, 2)
        self.setLayout(main_layout)
        
        # Load existing configuration from JSON
        self.populate_params_from_json()

    def get_project_variables(self):
        """
        Ottiene le variabili di controllo e misura dal project_data.
        Restituisce due liste: control_vars, measure_vars.
        """
        control_vars = self.project_data.get('control_variables', [])
        measure_vars = self.project_data.get('measure_variables', [])
        return control_vars, measure_vars

    def setup_sweep_order_section(self):
        """Crea la sezione per definire l'ordine degli sweep."""
        group = QGroupBox(self.translator.t('sweep_order_section'))
        layout = QVBoxLayout()
        
        layout.addWidget(QLabel(self.translator.t('sweep_order_description')))
        
        # List widget to show and reorder sweep variables
        self.sweep_order_list = QListWidget()
        self.sweep_order_list.currentItemChanged.connect(self.on_sweep_variable_selected)
        layout.addWidget(self.sweep_order_list)
        
        # Buttons to manage sweep order
        btn_layout = QHBoxLayout()
        
        self.add_sweep_btn = QPushButton(self.translator.t('add_sweep_variable'))
        self.add_sweep_btn.clicked.connect(self.add_sweep_variable)
        btn_layout.addWidget(self.add_sweep_btn)
        
        self.remove_sweep_btn = QPushButton(self.translator.t('remove_sweep_variable'))
        self.remove_sweep_btn.clicked.connect(self.remove_sweep_variable)
        btn_layout.addWidget(self.remove_sweep_btn)
        
        layout.addLayout(btn_layout)
        
        # Buttons to reorder
        order_btn_layout = QHBoxLayout()
        
        self.move_up_btn = QPushButton("↑ " + self.translator.t('move_up'))
        self.move_up_btn.clicked.connect(self.move_sweep_up)
        order_btn_layout.addWidget(self.move_up_btn)
        
        self.move_down_btn = QPushButton("↓ " + self.translator.t('move_down'))
        self.move_down_btn.clicked.connect(self.move_sweep_down)
        order_btn_layout.addWidget(self.move_down_btn)
        
        layout.addLayout(order_btn_layout)
        
        # Combo to select available control variables
        control_vars, _ = self.get_project_variables()
        self.available_sweep_combo = QComboBox()
        if control_vars:
            for v in control_vars:
                self.available_sweep_combo.addItem(v, v)
        else:
            self.available_sweep_combo.addItem(self.translator.t('no_variables_available'), None)
            self.available_sweep_combo.setEnabled(False)
            self.add_sweep_btn.setEnabled(False)
        
        layout.addWidget(QLabel(self.translator.t('available_control_variables')))
        layout.addWidget(self.available_sweep_combo)
        
        group.setLayout(layout)
        self.left_layout.addWidget(group)

    def setup_timing_section(self):
        """Crea la sezione per i parametri di timing."""
        group = QGroupBox(self.translator.t('timing_parameters'))
        layout = QFormLayout()
        
        # Delay between points (in seconds)
        self.delay_between_points = QDoubleSpinBox()
        self.delay_between_points.setRange(0, 3600)
        self.delay_between_points.setDecimals(3)
        self.delay_between_points.setValue(0.5)
        self.delay_between_points.setSuffix(" s")
        layout.addRow(self.translator.t('delay_between_points'), self.delay_between_points)
        
        # Delay between loops (in seconds)
        self.delay_between_loops = QDoubleSpinBox()
        self.delay_between_loops.setRange(0, 3600)
        self.delay_between_loops.setDecimals(3)
        self.delay_between_loops.setValue(1.0)
        self.delay_between_loops.setSuffix(" s")
        layout.addRow(self.translator.t('delay_between_loops'), self.delay_between_loops)
        
        group.setLayout(layout)
        self.left_layout.addWidget(group)

    def setup_variable_config_section(self):
        """Crea la sezione per configurare i parametri di sweep della variabile selezionata."""
        self.config_group = QGroupBox(self.translator.t('variable_sweep_config'))
        layout = QVBoxLayout()
        
        self.config_var_label = QLabel(self.translator.t('select_variable_to_configure'))
        layout.addWidget(self.config_var_label)
        
        # Input mode: list of values or range
        self.mode_group = QButtonGroup(self)
        self.list_radio = QRadioButton(self.translator.t('list_mode'))
        self.range_radio = QRadioButton(self.translator.t('range_mode'))
        self.mode_group.addButton(self.list_radio)
        self.mode_group.addButton(self.range_radio)
        self.list_radio.setChecked(True)
        
        layout.addWidget(self.list_radio)
        
        # Field for list of values
        self.value_list_edit = QLineEdit()
        self.value_list_edit.setPlaceholderText(self.translator.t('value_list_placeholder'))
        layout.addWidget(self.value_list_edit)
        
        # Field for range (start, stop, n points)
        layout.addWidget(self.range_radio)
        
        range_form = QFormLayout()
        self.value_start_edit = QLineEdit()
        self.value_start_edit.setPlaceholderText(self.translator.t('start_placeholder'))
        range_form.addRow(self.translator.t('start_value'), self.value_start_edit)
        
        self.value_stop_edit = QLineEdit()
        self.value_stop_edit.setPlaceholderText(self.translator.t('stop_placeholder'))
        range_form.addRow(self.translator.t('stop_value'), self.value_stop_edit)
        
        self.value_points_spin = QSpinBox()
        self.value_points_spin.setMinimum(2)
        self.value_points_spin.setMaximum(10000)
        self.value_points_spin.setValue(5)
        range_form.addRow(self.translator.t('num_points'), self.value_points_spin)
        
        layout.addLayout(range_form)
        
        # Button to apply configuration to selected variable
        self.apply_var_config_btn = QPushButton(self.translator.t('apply_variable_config'))
        self.apply_var_config_btn.clicked.connect(self.apply_variable_config)
        self.apply_var_config_btn.setEnabled(False)
        layout.addWidget(self.apply_var_config_btn)
        
        self.config_group.setLayout(layout)
        self.left_layout.addWidget(self.config_group)

    def add_sweep_variable(self):
        """Aggiunge una variabile di sweep alla lista."""
        var_name = self.available_sweep_combo.currentData()
        if not var_name:
            return
        
        # Check if already in list
        for i in range(self.sweep_order_list.count()):
            if self.sweep_order_list.item(i).data(Qt.ItemDataRole.UserRole) == var_name:
                QMessageBox.warning(self, self.translator.t('warning'), 
                                  self.translator.t('variable_already_in_list'))
                return
        
        # Add to list
        item = QListWidgetItem(var_name)
        item.setData(Qt.ItemDataRole.UserRole, var_name)
        self.sweep_order_list.addItem(item)
        
        # Initialize default configuration
        if var_name not in self.sweep_configs:
            self.sweep_configs[var_name] = {
                'mode': 'list',
                'values': []
            }

    def remove_sweep_variable(self):
        """Rimuove la variabile di sweep selezionata."""
        current_item = self.sweep_order_list.currentItem()
        if not current_item:
            return
        
        var_name = current_item.data(Qt.ItemDataRole.UserRole)
        
        # Remove from list
        row = self.sweep_order_list.row(current_item)
        self.sweep_order_list.takeItem(row)
        
        # Remove configuration
        if var_name in self.sweep_configs:
            del self.sweep_configs[var_name]

    def move_sweep_up(self):
        """Sposta la variabile selezionata verso l'alto (sweep esterno)."""
        current_row = self.sweep_order_list.currentRow()
        if current_row > 0:
            item = self.sweep_order_list.takeItem(current_row)
            self.sweep_order_list.insertItem(current_row - 1, item)
            self.sweep_order_list.setCurrentRow(current_row - 1)

    def move_sweep_down(self):
        """Sposta la variabile selezionata verso il basso (sweep interno)."""
        current_row = self.sweep_order_list.currentRow()
        if current_row < self.sweep_order_list.count() - 1:
            item = self.sweep_order_list.takeItem(current_row)
            self.sweep_order_list.insertItem(current_row + 1, item)
            self.sweep_order_list.setCurrentRow(current_row + 1)

    def on_sweep_variable_selected(self, current, previous):
        """Gestisce la selezione di una variabile di sweep per configurarla."""
        if not current:
            self.config_var_label.setText(self.translator.t('select_variable_to_configure'))
            self.apply_var_config_btn.setEnabled(False)
            return
        
        var_name = current.data(Qt.ItemDataRole.UserRole)
        self.config_var_label.setText(f"{self.translator.t('configuring_variable')}: {var_name}")
        self.apply_var_config_btn.setEnabled(True)
        
        # Load existing configuration
        if var_name in self.sweep_configs:
            config = self.sweep_configs[var_name]
            if config['mode'] == 'list':
                self.list_radio.setChecked(True)
                if config.get('values'):
                    self.value_list_edit.setText(','.join(str(v) for v in config['values']))
                else:
                    self.value_list_edit.clear()
            else:  # range
                self.range_radio.setChecked(True)
                self.value_start_edit.setText(str(config.get('start', '')))
                self.value_stop_edit.setText(str(config.get('stop', '')))
                self.value_points_spin.setValue(config.get('points', 5))

    def apply_variable_config(self):
        """Applica la configurazione alla variabile selezionata."""
        current_item = self.sweep_order_list.currentItem()
        if not current_item:
            return
        
        var_name = current_item.data(Qt.ItemDataRole.UserRole)
        
        if self.list_radio.isChecked():
            # List mode
            try:
                values = [float(v.strip()) for v in self.value_list_edit.text().split(',') if v.strip()]
                if not values:
                    QMessageBox.warning(self, self.translator.t('warning'),
                                      self.translator.t('empty_value_list'))
                    return
                self.sweep_configs[var_name] = {
                    'mode': 'list',
                    'values': values
                }
                QMessageBox.information(self, self.translator.t('success'),
                                      f"{self.translator.t('configuration_saved')}: {var_name}")
            except ValueError:
                QMessageBox.warning(self, self.translator.t('error'),
                                  self.translator.t('invalid_number_format'))
        else:
            # Range mode
            try:
                start = float(self.value_start_edit.text())
                stop = float(self.value_stop_edit.text())
                points = int(self.value_points_spin.value())
                self.sweep_configs[var_name] = {
                    'mode': 'range',
                    'start': start,
                    'stop': stop,
                    'points': points
                }
                QMessageBox.information(self, self.translator.t('success'),
                                      f"{self.translator.t('configuration_saved')}: {var_name}")
            except ValueError:
                QMessageBox.warning(self, self.translator.t('error'),
                                  self.translator.t('invalid_number_format'))

    def apply_params_to_json(self):
        """Costruisce il JSON completo con tutti i parametri di sweep."""
        # Get sweep order
        sweep_order = []
        for i in range(self.sweep_order_list.count()):
            item = self.sweep_order_list.item(i)
            var_name = item.data(Qt.ItemDataRole.UserRole)
            if var_name in self.sweep_configs:
                sweep_order.append({
                    'variable': var_name,
                    'config': self.sweep_configs[var_name]
                })
        
        # Get all variables to measure (control + measure variables)
        control_vars, measure_vars = self.get_project_variables()
        all_measured_vars = list(set(control_vars + measure_vars))  # Remove duplicates
        all_measured_vars.sort()  # Sort for consistency
        
        # Build new data structure
        data = {
            'type': 'efficiency',
            'sweeps': sweep_order,
            'measured_variables': all_measured_vars,
            'timing': {
                'delay_between_points': self.delay_between_points.value(),
                'delay_between_loops': self.delay_between_loops.value()
            }
        }
        
        self.data = data
        self.data_edit.setText(json.dumps(data, indent=2))
        
        QMessageBox.information(self, self.translator.t('success'),
                              self.translator.t('parameters_applied'))

    def populate_params_from_json(self):
        """Carica i parametri dal JSON esistente."""
        # Load sweeps
        sweeps = self.data.get('sweeps', [])
        for sweep in sweeps:
            var_name = sweep.get('variable')
            config = sweep.get('config', {})
            
            # Add to list
            item = QListWidgetItem(var_name)
            item.setData(Qt.ItemDataRole.UserRole, var_name)
            self.sweep_order_list.addItem(item)
            
            # Store configuration
            self.sweep_configs[var_name] = config
        
        # Load timing
        timing = self.data.get('timing', {})
        self.delay_between_points.setValue(timing.get('delay_between_points', 0.5))
        self.delay_between_loops.setValue(timing.get('delay_between_loops', 1.0))

    def save_changes(self):
        """Salva i dati modificati nel file .eff."""
        try:
            data = json.loads(self.data_edit.toPlainText())
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, self.translator.t('error'), str(e))



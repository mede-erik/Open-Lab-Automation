import os
import json
try:
    import pyvisa
    PYVISA_AVAILABLE = True
except (ImportError, ValueError) as e:
    pyvisa = None
    PYVISA_AVAILABLE = False
    print(f"PyVISA non disponibile: {e}")
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QGroupBox, QLineEdit, QPushButton, QHBoxLayout, QMessageBox
from PyQt5.QtCore import QTimer
from LoadInstruments import LoadInstruments


# =========================
# RemoteControlTab
# =========================

class RemoteControlTab(QWidget):
    """
    Tab for remote control of instruments.
    For each power supply/electronic load channel, shows a box to set voltage/current.
    On top, a single box shows all measurements from dataloggers/multimeters.
    Uses pyvisa for direct communication, using SCPI commands from LoadInstruments.
    """
    def __init__(self, load_instruments):
        """
        Initialize the RemoteControlTab.
        Sets up the layout, measurement group, and channels container.
        """
        super().__init__()
        self.load_instruments = load_instruments
        self.main_layout = QVBoxLayout()
        self.label = QLabel('Remote control of instruments')
        self.main_layout.addWidget(self.label)
        self.meas_group = QGroupBox('Measurements (Datalogger/Multimeter)')
        self.meas_layout = QVBoxLayout()
        self.meas_group.setLayout(self.meas_layout)
        self.main_layout.addWidget(self.meas_group)
        self.channels_container = QWidget()
        self.channels_layout = QVBoxLayout()
        self.channels_container.setLayout(self.channels_layout)
        self.main_layout.addWidget(self.channels_container)
        self.main_layout.addStretch()
        self.setLayout(self.main_layout)
        self.current_channel_widgets = []  # Stores references to current channel widgets
        
        # Initialize VISA resource manager if available
        if PYVISA_AVAILABLE and pyvisa is not None:
            try:
                self.rm = pyvisa.ResourceManager('@py')  # Use pyvisa-py backend
            except Exception as e:
                try:
                    self.rm = pyvisa.ResourceManager()  # Try default backend
                except Exception as e2:
                    print(f"Errore inizializzazione VISA: {e2}")
                    self.rm = None
        else:
            self.rm = None
        
        self.visa_connections = {}  # Stores active VISA connections
        self.meas_labels = {}  # Stores measurement labels for dataloggers

    def get_scpi_cmd(self, inst, ch, action):
        """
        Get the SCPI command for the given instrument/channel/action from the library.
        action: 'set_voltage', 'set_current', 'read_voltage', 'read_current', 'read_measurement'
        """
        type_name = inst.get('instrument_type', '')
        series_id = inst.get('series', '')
        model_id = inst.get('model_id', inst.get('model', ''))
        scpi_dict = self.load_instruments.get_model_scpi(type_name, series_id, model_id)
        if not scpi_dict:
            # Fallback standard
            if action == 'set_voltage':
                return 'VOLT {value}'
            if action == 'set_current':
                return 'CURR {value}'
            if action == 'read_voltage':
                return 'MEAS:VOLT?'
            if action == 'read_current':
                return 'MEAS:CURR?'
            if action == 'read_measurement':
                return 'MEAS?'
            return ''
        # Mappa azione → chiave SCPI
        action_map = {
            'set_voltage': ['set_voltage', 'VOLT'],
            'set_current': ['set_current', 'CURR'],
            'read_voltage': ['read_voltage', 'MEAS:VOLT?'],
            'read_current': ['read_current', 'MEAS:CURR?'],
            'read_measurement': ['read_measurement', 'MEAS?']
        }
        for key in action_map.get(action, []):
            if key in scpi_dict:
                return scpi_dict[key]
        # Fallback
        return ''

    def update_translation(self, translator):
        """
        Update UI elements with translated text.
        :param translator: Translator instance for language translation.
        """
        self.label.setText(translator.t('remote_control'))
        self.meas_group.setTitle(translator.t('measurements') if hasattr(translator, 't') else 'Measurements (Datalogger/Multimeter)')
        # Optionally update channel group titles
        for group in self.current_channel_widgets:
            inst = group.property('instrument')
            ch = group.property('channel')
            if inst and ch:
                group.setTitle(f"{inst.get('instance_name', '')} - {ch.get('name', '')}")

    def load_instruments(self, inst_file_path):
        """
        Load instruments from the specified .inst file and create corresponding UI controls.
        :param inst_file_path: Path to the .inst file to load.
        """
        # Clear previous controls
        for i in reversed(range(self.channels_layout.count())):
            widget = self.channels_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        self.current_channel_widgets.clear()
        # Clear measurement area
        for i in reversed(range(self.meas_layout.count())):
            widget = self.meas_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        self.meas_labels.clear()
        # Close previous VISA connections
        for inst in self.visa_connections.values():
            try:
                inst.close()
            except Exception:
                pass
        self.visa_connections = {}
        if not inst_file_path or not os.path.isfile(inst_file_path):
            return
        try:
            with open(inst_file_path, 'r', encoding='utf-8') as f:
                inst_data = json.load(f)
        except Exception:
            return
        # --- First, collect all datalogger/multimeter channels for measurement area ---
        meas_vars = []  # [(inst, ch)]
        for inst in inst_data.get('instruments', []):
            if inst.get('instrument_type') in ['dataloggers', 'multimeters']:
                for ch in inst.get('channels', []):
                    meas_vars.append((inst, ch))
        if meas_vars:
            for inst, ch in meas_vars:
                var = ch.get('measured_variable', ch.get('name', ''))
                label = QLabel(f"{inst.get('instance_name','')} - {var}: ...")
                self.meas_layout.addWidget(label)
                self.meas_labels[(inst.get('instance_name',''), var)] = label
            # Add a refresh button
            btn = QPushButton('Refresh Measurements')
            btn.clicked.connect(lambda: self.refresh_measurements(meas_vars))
            self.meas_layout.addWidget(btn)
        # --- Then, for each power supply/electronic load, create a group per instrument ---
        for inst in inst_data.get('instruments', []):
            if inst.get('instrument_type') in ['power_supplies', 'electronic_loads']:
                visa_addr = inst.get('visa_address', None)
                # --- Pulsante di connessione per strumento ---
                conn_btn = QPushButton('Collega')
                conn_btn.setCheckable(True)
                conn_btn.setChecked(False)
                conn_btn.setStyleSheet('border: 2px solid gray;')
                def try_connect(inst=inst, btn=conn_btn):
                    if not self.rm:
                        btn.setStyleSheet('border: 2px solid orange;')
                        btn.setChecked(False)
                        btn.setToolTip("VISA non disponibile")
                        return
                        
                    visa_addr = inst.get('visa_address', None)
                    if not visa_addr:
                        btn.setStyleSheet('border: 2px solid red;')
                        btn.setChecked(False)
                        return
                    try:
                        instr = self.rm.open_resource(visa_addr)
                        self.visa_connections[visa_addr] = instr
                        btn.setStyleSheet('border: 2px solid green;')
                        btn.setChecked(True)
                    except Exception:
                        btn.setStyleSheet('border: 2px solid red;')
                        btn.setChecked(False)
                        timer = QTimer(self)
                        timer.setSingleShot(True)
                        timer.timeout.connect(lambda: try_connect(inst, btn))
                        timer.start(5000)
                conn_btn.clicked.connect(lambda _, i=inst, b=conn_btn: try_connect(i, b))
                # --- Fine pulsante connessione ---
                # Crea un groupbox per lo strumento
                inst_group = QGroupBox(f"{inst.get('instance_name','')} ({inst.get('model','')})")
                inst_vbox = QVBoxLayout()
                inst_vbox.addWidget(conn_btn)
                # Per ogni canale, aggiungi i controlli
                for ch in inst.get('channels', []):
                    group = QGroupBox(f"{inst.get('instance_name','')} - {ch.get('name','')}")
                    group.setProperty('instrument', inst)
                    group.setProperty('channel', ch)
                    vbox = QVBoxLayout()
                    # Voltage set
                    hbox_v = QHBoxLayout()
                    hbox_v.addWidget(QLabel('Voltage (V):'))
                    v_edit = QLineEdit()
                    v_edit.setPlaceholderText('Set voltage')
                    set_v_btn = QPushButton('Set')
                    set_v_btn.clicked.connect(lambda _, i=inst, c=ch, e=v_edit: self.set_voltage(i, c, e))
                    hbox_v.addWidget(v_edit)
                    hbox_v.addWidget(set_v_btn)
                    vbox.addLayout(hbox_v)
                    # Current set
                    hbox_c = QHBoxLayout()
                    hbox_c.addWidget(QLabel('Current (A):'))
                    c_edit = QLineEdit()
                    c_edit.setPlaceholderText('Set current')
                    set_c_btn = QPushButton('Set')
                    set_c_btn.clicked.connect(lambda _, i=inst, c=ch, e=c_edit: self.set_current(i, c, e))
                    hbox_c.addWidget(c_edit)
                    hbox_c.addWidget(set_c_btn)
                    vbox.addLayout(hbox_c)
                    # Add a read actual values button
                    read_btn = QPushButton('Read Actual Values')
                    read_lbl = QLabel('V: ...  I: ...')
                    read_btn.clicked.connect(lambda _, i=inst, c=ch, l=read_lbl: self.read_actual(i, c, l))
                    vbox.addWidget(read_btn)
                    vbox.addWidget(read_lbl)
                    group.setLayout(vbox)
                    inst_vbox.addWidget(group)
                    self.current_channel_widgets.append(group)
                inst_group.setLayout(inst_vbox)
                self.channels_layout.addWidget(inst_group)
        self.channels_layout.addStretch()

    def get_visa_instrument(self, inst):
        """
        Get the VISA instrument object for the given instance.
        Opens a new connection if not already open.
        :param inst: Instrument instance data.
        :return: VISA instrument object or None if error.
        """
        if not self.rm:
            return None
            
        visa_addr = inst.get('visa_address', None)
        if not visa_addr:
            return None
        if visa_addr in self.visa_connections:
            return self.visa_connections[visa_addr]
        try:
            instr = self.rm.open_resource(visa_addr)
            self.visa_connections[visa_addr] = instr
            return instr
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, 'VISA Error', f'Cannot open {visa_addr}: {e}')
            return None

    def set_voltage(self, inst, ch, edit):
        """
        Set the voltage for the given instrument and channel using the SCPI command.
        :param inst: Instrument instance data.
        :param ch: Channel data.
        :param edit: QLineEdit widget containing the voltage value.
        """
        value = edit.text()
        instr = self.get_visa_instrument(inst)
        if not instr:
            return
        try:
            cmd = self.get_scpi_cmd(inst, ch, 'set_voltage').replace('{value}', value)
            instr.write(cmd)
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, 'Set Voltage', str(e))

    def set_current(self, inst, ch, edit):
        """
        Set the current for the given instrument and channel using the SCPI command.
        :param inst: Instrument instance data.
        :param ch: Channel data.
        :param edit: QLineEdit widget containing the current value.
        """
        value = edit.text()
        instr = self.get_visa_instrument(inst)
        if not instr:
            return
        try:
            cmd = self.get_scpi_cmd(inst, ch, 'set_current').replace('{value}', value)
            instr.write(cmd)
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, 'Set Current', str(e))

    def read_actual(self, inst, ch, label):
        """
        Read the actual voltage and current values from the instrument and update the label.
        :param inst: Instrument instance data.
        :param ch: Channel data.
        :param label: QLabel widget to update with the read values.
        """
        instr = self.get_visa_instrument(inst)
        if not instr:
            return
        try:
            v_cmd = self.get_scpi_cmd(inst, ch, 'read_voltage')
            c_cmd = self.get_scpi_cmd(inst, ch, 'read_current')
            v = instr.query(v_cmd)
            c = instr.query(c_cmd)
            label.setText(f'V: {v.strip()}  I: {c.strip()}')
        except Exception as e:
            label.setText(f'Error: {e}')

    def refresh_measurements(self, meas_vars):
        """
        Refresh the measurements displayed in the UI by querying the instruments.
        :param meas_vars: List of (instrument, channel) tuples for measurement variables.
        """
        for inst, ch in meas_vars:
            visa_addr = inst.get('visa_address', None)
            instr = self.get_visa_instrument(inst)
            var = ch.get('measured_variable', ch.get('name', ''))
            label = self.meas_labels.get((inst.get('instance_name',''), var))
            if not instr or not label:
                continue
            try:
                cmd = self.get_scpi_cmd(inst, ch, 'read_measurement')
                val = instr.query(cmd)
                label.setText(f"{inst.get('instance_name','')} - {var}: {val.strip()}")
            except Exception as e:
                label.setText(f"{inst.get('instance_name','')} - {var}: Error: {e}")
